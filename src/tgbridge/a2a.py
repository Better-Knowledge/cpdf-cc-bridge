"""Comunicação entre agentes (A2A) — RPC síncrono sobre HTTP.

Servidor separado (0.0.0.0:A2A_PORT, só na rede compartilhada) com POST /message:
roda a mensagem do agente remetente numa sessão tmux EFÊMERA (claude interativo =
assinatura) com A2A_INBOUND=1 (anti-loop, profundidade 1) e SEM os segredos de
infra no ambiente (env-scrub), captura a resposta via arquivo e devolve no corpo
HTTP. Defesas: bearer (A2A_SECRET), allowlist de remetentes e rate-limit por
remetente. O receiver de hooks (127.0.0.1:8787) segue intacto.
"""
import asyncio
import json
import logging
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request

from . import tmux
from .config import ephemeral_blocklist

log = logging.getLogger("tgbridge.a2a")


def _sanitize_sender(name: str, limit: int = 48) -> str:
    """O nome do remetente é auto-declarado (não confiável) e acaba em log/notify.
    Remove quebras de linha e limita o tamanho para não injetar no Telegram."""
    name = (name or "agente").replace("\n", " ").replace("\r", " ").strip()
    return name[:limit] or "agente"


def _registry_senders(ctx) -> list[str]:
    """Nomes do agents-registry.json — fallback da allowlist quando não há env."""
    ws = getattr(ctx.cfg, "workspace", "") or os.environ.get("AGENT_WORKSPACE", "") \
        or os.path.expanduser("~")
    path = os.path.join(ws, "agents-registry.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [a.get("name", "").strip() for a in data.get("agents", []) if a.get("name")]
    except Exception:
        return []


async def run_and_capture(sender: str, message: str, ctx, timeout: float = 120.0) -> str:
    """Roda a mensagem numa sessão efêmera e retorna a resposta (capturada por arquivo)."""
    cfg = ctx.cfg
    cwd = cfg.workspace or os.environ.get("AGENT_WORKSPACE", "") or os.path.expanduser("~")
    token = secrets.token_hex(6)
    # Arquivo de resposta DENTRO do workspace (.a2a/) — coberto pelo acceptEdits,
    # diferente de /tmp que pode exigir confirmação fora do projeto.
    a2a_dir = os.path.join(cwd, ".a2a")
    try:
        os.makedirs(a2a_dir, exist_ok=True)
    except OSError:
        a2a_dir = cwd
    outfile = os.path.join(a2a_dir, f"{token}.txt")
    s = tmux.norm(f"a2a-{sender}-{token}")
    log.info("A2A: '%s' -> sessão efêmera %s (cwd=%s)", sender, s, cwd)

    await tmux.kill_session(s)
    # A2A_INBOUND=1: o destino não pode encaminhar para um 3º agente (anti-loop).
    # env_unset: a sessão NÃO herda os segredos de infra (anti-exfil cross-agent).
    await tmux.new_session(
        s, cwd=cwd,
        env_unset=getattr(cfg, "ephemeral_env_blocklist", None) or ephemeral_blocklist(),
        env_set={"A2A_INBOUND": "1"},
    )
    await tmux.wait_ready(s)
    await asyncio.sleep(1.5)
    prompt = (
        f'[Mensagem do agente "{sender}" via A2A]\n{message}\n\n'
        f"Responda de forma objetiva. Escreva SOMENTE a sua resposta final (texto puro) "
        f"no arquivo {outfile}. Em seguida responda no chat apenas: A2A_DONE"
    )
    await tmux.send_text(s, prompt)
    await asyncio.sleep(0.5)
    await tmux.send_keys(s, "Enter")

    answer, waited, last_len = "", 0.0, -1
    while waited < timeout:
        await asyncio.sleep(2.0)
        waited += 2.0
        try:
            data = open(outfile, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if data and len(data) == last_len:   # estabilizou
            answer = data.strip()
            break
        last_len = len(data)

    await tmux.kill_session(s)
    try:
        os.remove(outfile)
    except OSError:
        pass
    if not answer:
        log.warning("A2A: '%s' não produziu resposta a tempo (%ss)", sender, timeout)
    return answer


def make_a2a_app(ctx) -> FastAPI:
    app = FastAPI(title="tgbridge-a2a")
    cfg = ctx.cfg
    expected = f"Bearer {cfg.a2a_secret}"

    # Allowlist de remetentes: env A2A_ALLOWED_SENDERS ou nomes do registry.
    # Vazia → aceita qualquer remetente autenticado (com warn). 'from' é
    # auto-declarado, então isto é defesa em profundidade (o gate forte é o bearer
    # + segredo por-agente, que é ação do operador).
    allow = set(getattr(cfg, "a2a_allowed_senders", []) or []) or set(_registry_senders(ctx))
    if not allow:
        log.warning("A2A: allowlist de remetentes vazia — aceitando qualquer remetente autenticado.")

    # Cada chamada abre uma sessão `claude` (cara) — serializa por padrão.
    sem = asyncio.Semaphore(int(os.environ.get("A2A_CONCURRENCY", "1")))
    rate_max = int(getattr(cfg, "a2a_rate_max", 30))
    rate_window = float(getattr(cfg, "a2a_rate_window", 300))
    calls: dict[str, deque] = defaultdict(deque)

    def _rate_ok(sender: str) -> bool:
        now = time.monotonic()
        dq = calls[sender]
        while dq and now - dq[0] > rate_window:
            dq.popleft()
        if len(dq) >= rate_max:
            return False
        dq.append(now)
        return True

    @app.get("/health")
    async def health():
        return {"ok": True, "agent": cfg.agent_name}

    @app.post("/message")
    async def message(request: Request, authorization: str = Header(default="")):
        if authorization != expected:
            raise HTTPException(status_code=401, detail="unauthorized")
        body = await request.json()
        sender = _sanitize_sender(body.get("from") or "agente")
        msg = (body.get("message") or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="campo 'message' obrigatório")
        if allow and sender not in allow:
            log.warning("A2A: remetente '%s' fora da allowlist — 403", sender)
            raise HTTPException(status_code=403, detail="remetente não autorizado")
        if not _rate_ok(sender):
            log.warning("A2A: rate-limit estourado por '%s' — 429", sender)
            raise HTTPException(status_code=429, detail="rate limit excedido")
        log.info("A2A: '%s' consultou %s", sender, cfg.agent_name)
        async with sem:
            answer = await run_and_capture(sender, msg, ctx)
        if cfg.a2a_notify:
            try:
                chat = int(ctx.state.get_kv("default_chat_id", cfg.default_chat_id))
                await ctx.bot.send_message(
                    chat_id=chat, text=f"💬 A2A: {sender} consultou {cfg.agent_name}.")
            except Exception:
                log.debug("A2A notify falhou", exc_info=True)
        return {"answer": answer, "from": cfg.agent_name}

    return app

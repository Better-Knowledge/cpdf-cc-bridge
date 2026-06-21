"""Agendador (APScheduler) com jobstore SQLite — jobs sobrevivem a restart.
Cada job roda numa sessão tmux EFÊMERA (`claude` interativo = assinatura, sem `-p`),
isolada do chat principal; a saída volta pelo hook Stop global (com supressão de sentinela)."""
import asyncio
import logging
import os
import time
from datetime import datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from . import tmux

log = logging.getLogger("tgbridge.scheduler")

# Modo de permissão das sessões de cron. As sessões efêmeras são não-interativas
# do ponto de vista do usuário (ninguém está olhando o TUI), então um prompt de
# permissão as trava indefinidamente.
#   - `acceptEdits`: auto-aceita edições de arquivo, mas NÃO comandos Bash; combinado
#     com a allowlist em .claude/settings.json cobre os comandos simples — porém um
#     comando composto com `set -a` (ex.: `set -a; source x; bird ...`) cai numa trava
#     de análise estática do Claude Code e pede permissão MESMO estando na allowlist.
#   - `bypassPermissions`: zero prompts (necessário p/ os crons que usam `set -a`/bird).
#     Como o container roda como root, exige IS_SANDBOX=1 (ver _cron_cmd) — o que é
#     legítimo: cada sessão é efêmera, isolada e roda um prompt fixo e confiável.
#   - vazio/`default`: `claude` puro (comportamento antigo).
# Configurável via CRON_PERMISSION_MODE.
CRON_PERMISSION_MODE = os.environ.get("CRON_PERMISSION_MODE", "bypassPermissions").strip()

# Timeout (watchdog) da sessão efêmera: se ainda estiver viva após N minutos, é
# encerrada e o usuário é avisado no Telegram. Rede de segurança para sessões que
# travam (ex.: prompt de permissão que escapou da allowlist). Default 120 min.
CRON_SESSION_TIMEOUT_S = int(os.environ.get("CRON_SESSION_TIMEOUT_MIN", "120")) * 60

# Callback de notificação (async fn(chat_id, text)); injetado pelo app no startup.
_notify = None

# Watchdog ativo por label. Cada disparo cancela o do disparo anterior do mesmo job
# (senão um watchdog velho mataria a sessão de um disparo novo → falso "excedeu N min").
_watchdogs: dict = {}


def set_notifier(fn) -> None:
    """Registra o callback usado pelo watchdog para avisar timeouts no Telegram."""
    global _notify
    _notify = fn


# System prompt das sessões de cron: a saída final é o que a bridge posta no Telegram.
# Sem isso o modelo costuma escrever o resultado e DEPOIS um comentário de fechamento —
# e o notifier (que pega o ÚLTIMO bloco de texto) acaba postando só o comentário.
CRON_SYSTEM_PROMPT = (
    "Você está rodando como uma tarefa AGENDADA (cron) numa sessão isolada e efêmera. "
    "A sua ÚLTIMA mensagem de texto é EXATAMENTE o que a bridge posta no Telegram do usuário — "
    "você NÃO tem ferramenta de envio e NÃO deve dizer que 'enviei'/'postei'/'está registrado'. "
    "Produza a resposta pedida como sua mensagem final e PARE: sem comentário, meta-comentário, "
    "saudação ou qualquer texto depois dela. Se o prompt pedir para registrar algo em memory/, "
    "faça isso ANTES da mensagem final."
)


def _cron_cmd(model: str = "", label: str = "") -> list:
    from .config import cron_blocklist
    mode = CRON_PERMISSION_MODE
    # env-scrub: a sessão de cron não herda os segredos de infra (anti-exfil); o
    # prefixo `env -u …` serve tanto p/ limpar quanto p/ injetar IS_SANDBOX=1.
    # cron_blocklist() MANTÉM BRIDGE_HOOK_SECRET — o Stop hook precisa dele p/ entregar.
    env = ["env"]
    for v in cron_blocklist():
        env += ["-u", v]
    # Rótulo do job no ambiente da sessão efêmera: o hook Stop reflete-o num header
    # (X-Tgbridge-Cron-Label, via ${TGBRIDGE_CRON_LABEL}) → o notifier colhe a sessão
    # assim que entregar, sem esperar o watchdog. Vazio/ausente na sessão principal.
    if label:
        env += [f"TGBRIDGE_CRON_LABEL={label}"]
    # Modelo por job (otimização de custo/cota): `claude --model <alias>` (ex.: haiku/sonnet).
    claude = ["claude"] + (["--model", model] if model else [])
    if mode and mode.lower() != "default":
        # bypassPermissions é recusado sob root sem IS_SANDBOX=1; o container é um sandbox
        # isolado, então habilitamos só na sessão de cron (prefixo `env`, escopo local).
        if mode == "bypassPermissions":
            env += ["IS_SANDBOX=1"]
        cmd = env + claude + ["--permission-mode", mode]
    else:
        cmd = env + claude
    cmd += ["--append-system-prompt", CRON_SYSTEM_PROMPT]
    return cmd


def _cron_model(label: str) -> str:
    """Modelo do cron resolvido por label: CRON_MODEL_<LABEL> (override) ou CRON_MODEL
    (padrão p/ todos). Vazio = modelo default do agente. Ex.: CRON_MODEL_HEARTBEAT=haiku."""
    norm = "".join(c if c.isalnum() else "_" for c in (label or "").upper())
    return (os.environ.get("CRON_MODEL_" + norm) or os.environ.get("CRON_MODEL", "")).strip()


def build_scheduler(cfg) -> AsyncIOScheduler:
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{cfg.jobs_db}")}
    return AsyncIOScheduler(jobstores=jobstores, timezone=cfg.tz)


async def _session_watchdog(session: str, label: str, chat_id: int,
                            timeout_s: float = CRON_SESSION_TIMEOUT_S) -> None:
    """Após `timeout_s` (default CRON_SESSION_TIMEOUT_S), mata a sessão se ainda estiver
    viva (travada) e avisa no Telegram. Roda como task destacada (run_scheduled_prompt é
    fire-and-forget). `timeout_s` < default é usado no re-arm de startup (tempo restante
    de uma sessão que já estava viva). Vigia SÓ a instância que o criou: se um novo
    disparo o cancelou, sai sem agir."""
    try:
        try:
            await asyncio.sleep(timeout_s)
        except asyncio.CancelledError:
            return
        if not await tmux.has_session(session):
            return  # terminou normalmente, nada a fazer
        mins = CRON_SESSION_TIMEOUT_S // 60
        log.warning("cron '%s': sessão %s excedeu %d min; encerrando (watchdog)", label, session, mins)
        await tmux.interrupt(session)        # tenta abortar o turno (Escape) antes de matar
        await asyncio.sleep(2)
        await tmux.kill_session(session)
        if _notify and chat_id:
            try:
                await _notify(
                    chat_id,
                    f"⏱️ Cron `{label}` excedeu {mins} min e foi encerrado (timeout). "
                    f"Sessão `{session}` morta — sem resultado. "
                    f"Sessão ociosa identificada.",
                )
            except Exception:
                log.exception("watchdog: falha notificando timeout de '%s'", label)
    finally:
        # remove a própria entrada só se ainda for este task (não um substituto de um novo disparo)
        if _watchdogs.get(label) is asyncio.current_task():
            _watchdogs.pop(label, None)


async def reap_cron_session(label: str) -> bool:
    """Colhe a sessão efêmera `cron-<label>` assim que o job entregou (chamado pelo
    notifier no hook Stop): mata a sessão tmux e cancela o watchdog. Sem isto o
    `claude` interativo fica OCIOSO até o watchdog (CRON_SESSION_TIMEOUT_S) — e em
    jobs 1×/dia (ex.: briefing) isso vira um falso 'excedeu N min' diário, pois não
    há disparo seguinte que colha a sessão antes do timeout. Idempotente; no-op para
    rótulo vazio (sessão principal/interativa). Retorna True se matou uma sessão."""
    if not label:
        return False
    wd = _watchdogs.pop(label, None)
    if wd and not wd.done():
        wd.cancel()
    s = tmux.norm(f"cron-{label}")
    if not await tmux.has_session(s):
        return False
    log.info("cron '%s': sessão %s colhida após entrega (hook Stop)", label, s)
    await tmux.kill_session(s)
    return True


async def rearm_cron_watchdogs(chat_id: int, main_session: str = "") -> None:
    """No startup da bridge, re-assume as sessões de cron órfãs (cujo watchdog em memória
    se perdeu no restart do processo): mata as que já estouraram o timeout e re-arma um
    watchdog (com o tempo restante) nas demais. NUNCA toca a sessão principal nem sessões
    não-cron. A idade só decide reap vs re-arm — quem É cron é decidido pelo marcador
    `@cron` (ou prefixo `cron-` p/ órfãs anteriores a este deploy). Best-effort: qualquer
    erro é logado e não propaga (não pode bloquear o boot)."""
    main = tmux.norm(main_session) if main_session else ""
    now = int(time.time())
    reaped, rearmed = [], 0
    for name, created, cron_opt in await tmux.list_cron_meta():
        if main and name == main:
            continue                       # exclusão dura da sessão principal
        if not (cron_opt or name.startswith("cron-")):
            continue                       # só sessões marcadas/prefixadas como cron
        label = cron_opt or name[len("cron-"):]
        wd = _watchdogs.get(label)
        if wd and not wd.done():
            continue                       # já supervisionada (defensivo)
        elapsed = (now - created) if created else -1
        if elapsed >= CRON_SESSION_TIMEOUT_S:
            await tmux.interrupt(name)
            await asyncio.sleep(2)
            await tmux.kill_session(name)
            reaped.append(label)
        else:
            remaining = (CRON_SESSION_TIMEOUT_S - elapsed) if elapsed >= 0 else CRON_SESSION_TIMEOUT_S
            _watchdogs[label] = asyncio.create_task(
                _session_watchdog(name, label, chat_id, timeout_s=remaining))
            rearmed += 1
    if reaped or rearmed:
        log.info("startup: cron sweep — %d reapada(s) %s, %d re-armada(s)",
                 len(reaped), reaped, rearmed)
    if reaped and _notify and chat_id:
        try:
            await _notify(
                chat_id,
                f"🧹 Reinício da bridge: limpei {len(reaped)} sessão(ões) de cron "
                f"presa(s) além do timeout — {', '.join('`' + l + '`' for l in reaped)}.",
            )
        except Exception:
            log.exception("startup sweep: falha notificando reap")


async def run_scheduled_prompt(label: str, prompt: str, chat_id: int, workspace: str = "") -> None:
    """Executa o prompt agendado numa sessão tmux efêmera `cron-<label>`.

    Referenciável por import path (necessário para o jobstore persistente).
    A sessão anterior do mesmo job é morta antes (isolamento por turno). A saída
    sai pelo hook Stop global → notifier (chat default), sujeita à supressão de sentinela.
    A sessão sobe em modo de permissão `CRON_PERMISSION_MODE` e é vigiada por um
    watchdog que a encerra após `CRON_SESSION_TIMEOUT_S` se travar.
    """
    cwd = workspace or os.environ.get("AGENT_WORKSPACE", "") or os.path.expanduser("~")
    s = tmux.norm(f"cron-{label or 'job'}")
    cmd = _cron_cmd(_cron_model(label), label)
    log.info("cron '%s' disparando em sessão efêmera %s (cwd=%s, cmd=%r)", label, s, cwd, cmd)
    # Cancela o watchdog do disparo ANTERIOR deste label — senão um watchdog velho (de um
    # disparo > timeout atrás) mataria esta sessão nova e mandaria um falso "excedeu N min".
    prev = _watchdogs.pop(label, None)
    if prev and not prev.done():
        prev.cancel()
    await tmux.kill_session(s)
    await tmux.new_session(s, cwd=cwd, cmd=cmd)
    # Marcador autoritativo p/ a varredura de startup reconhecer crons após restart da
    # bridge (a user-option vive no servidor tmux, que sobrevive ao processo da bridge).
    await tmux.set_option(s, "@cron", label or "job")
    ready = await tmux.wait_ready(s)
    if not ready:
        log.warning("cron '%s': sessão %s não ficou pronta a tempo; enviando assim mesmo", label, s)
    await asyncio.sleep(1.5)             # TUI recém-aberto precisa assentar o input antes do Enter
    await tmux.send_text(s, prompt)
    await asyncio.sleep(0.5)
    await tmux.send_keys(s, "Enter")     # reforço de submit (Enter em input vazio é no-op)
    # Watchdog destacado (fire-and-forget): mata a sessão se travar > timeout. Um por label.
    _watchdogs[label] = asyncio.create_task(_session_watchdog(s, label, chat_id))


def parse_when(when: str, tz: str):
    """Parseia só o gatilho: 'cron <expr 5 campos>' ou 'at <ISO8601>'.
    Retorna (trigger, descr). Usado pelo endpoint de scheduling."""
    toks = (when or "").split()
    mode = toks[0].lower() if toks else ""
    rest = " ".join(toks[1:]).strip()
    if mode == "cron":
        if not rest:
            raise ValueError("Expressão cron vazia. Ex.: 0 9 * * 1-5")
        return CronTrigger.from_crontab(rest, timezone=tz), f"cron {rest}"
    if mode == "at":
        return DateTrigger(run_date=datetime.fromisoformat(rest), timezone=tz), f"at {rest}"
    raise ValueError("Use 'cron <expr>' ou 'at <ISO8601>'.")


def parse_schedule(args_text: str, tz: str):
    """
    Aceita:
      'cron <expr 5 campos> | <sessão> | <prompt>'
      'at <ISO8601>          | <sessão> | <prompt>'
    Retorna (trigger, session, prompt, descr).
    """
    parts = [p.strip() for p in args_text.split("|")]
    if len(parts) < 3:
        raise ValueError(
            "Formato: /schedule cron <expr> | <sessão> | <prompt>  "
            "(ou: at <ISO8601> | <sessão> | <prompt>)"
        )
    head, session = parts[0], parts[1]
    prompt = "|".join(parts[2:]).strip()
    if not session:
        raise ValueError("Informe a sessão (ex.: meu-agente).")
    if not prompt:
        raise ValueError("Informe o prompt.")

    toks = head.split()
    mode = toks[0].lower() if toks else ""
    rest = " ".join(toks[1:]).strip()

    if mode == "cron":
        if not rest:
            raise ValueError("Expressão cron vazia. Ex.: 0 9 * * 1-5")
        return CronTrigger.from_crontab(rest, timezone=tz), session, prompt, f"cron {rest}"
    if mode == "at":
        dt = datetime.fromisoformat(rest)
        return DateTrigger(run_date=dt, timezone=tz), session, prompt, f"at {rest}"
    raise ValueError("Use 'cron <expr>' ou 'at <ISO8601>'.")

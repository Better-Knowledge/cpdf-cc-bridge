"""Parsing do transcript (Stop) + envio ao Telegram + dispatch dos eventos de hook."""
import asyncio
import json
import logging

import telegramify_markdown
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("tgbridge.notifier")

TG_LIMIT = 4000      # split de fallback (texto puro)
TG_LIMIT_MD = 4096   # limite real do Telegram para a mensagem MarkdownV2
MD_CHUNK = 3000      # tamanho do chunk em markdown ANTES da conversão (o escape expande)


def extract_last_assistant(transcript_path: str):
    """Varre o JSONL de TRÁS pra frente e pega o último registro 'assistant'
    com bloco de texto. Pula 'thinking'/'tool_use'. Retorna (uuid, texto)."""
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None, None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content") or []
        texts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        joined = "\n".join(t for t in texts if t).strip()
        if joined:
            return rec.get("uuid"), joined
    return None, None


async def read_final(transcript_path: str, retries: int = 15, interval: float = 0.2):
    """Espera o transcript ESTABILIZAR antes de extrair. O hook Stop pode disparar
    antes do registro final do assistente ser gravado; sem isso, peganos um texto
    intermediário (ex.: 'deixa eu contar...'). Lê, espera, relê; quando o uuid do
    último texto repete, é o registro final."""
    uuid, text = extract_last_assistant(transcript_path)
    for _ in range(retries):
        await asyncio.sleep(interval)
        u2, t2 = extract_last_assistant(transcript_path)
        if t2 and u2 == uuid:
            return u2, t2  # estável
        uuid, text = u2, t2
    return uuid, text


def split_message(text: str, limit: int = TG_LIMIT):
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            if cur:
                chunks.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        chunks.append(cur)
    return chunks or [""]


def split_markdown(text: str, limit: int = MD_CHUNK):
    """Divide markdown em pedaços por linha, SEM cortar dentro de bloco ``` ```.
    Cada pedaço é markdown completo → converte para MarkdownV2 válido sem quebrar
    entidades entre mensagens."""
    chunks, cur, cur_len, fence = [], [], 0, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        if cur and not fence and cur_len + len(line) + 1 > limit:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [""]


async def _send_chunk(bot, chat_id: int, chunk: str) -> None:
    converted = None
    try:
        converted = telegramify_markdown.markdownify(chunk)
    except Exception:
        log.warning("conversão markdown falhou; texto puro", exc_info=True)
    if converted and len(converted) <= TG_LIMIT_MD:
        try:
            await bot.send_message(chat_id=chat_id, text=converted, parse_mode="MarkdownV2")
            return
        except Exception:
            log.warning("envio MarkdownV2 falhou; texto puro", exc_info=True)
    for piece in split_message(chunk):
        try:
            await bot.send_message(chat_id=chat_id, text=piece)
        except Exception:
            log.exception("falha enviando mensagem ao Telegram")


async def send(bot, chat_id: int, text: str) -> None:
    """Converte Markdown (Claude) -> MarkdownV2, dividindo respostas longas por
    blocos. Fallback automático para texto puro por pedaço."""
    chunks = split_markdown(text) if len(text) > MD_CHUNK else [text]
    for chunk in chunks:
        await _send_chunk(bot, chat_id, chunk)


def _g(payload: dict, *keys, default=None):
    for k in keys:
        if k in payload and payload[k] is not None:
            return payload[k]
    return default


def _chat(ctx, session_id: str) -> int:
    bound = ctx.state.chat_for_session(session_id) if session_id else None
    if bound:
        return int(bound)
    return int(ctx.state.get_kv("default_chat_id", ctx.cfg.default_chat_id))


async def handle_event(payload: dict, ctx) -> None:
    event = _g(payload, "hook_event_name", "hookEventName", default="")
    session_id = _g(payload, "session_id", "sessionId", default="")

    if event == "SessionStart":
        chat = int(ctx.state.get_kv("default_chat_id", ctx.cfg.default_chat_id))
        ctx.state.bind_session(session_id, chat, _g(payload, "cwd", default=""))
    elif event == "SessionEnd":
        if session_id:
            ctx.state.clear_session(session_id)
    elif event == "Stop":
        await _handle_stop(payload, session_id, ctx)
    elif event == "Notification":
        await _handle_notification(payload, session_id, ctx)
    elif event in _MONITOR_LABELS:
        await _handle_monitor(event, payload, session_id, ctx)
    else:
        log.debug("evento ignorado: %s", event)


_MONITOR_LABELS = {
    "SubagentStart": "🤖 subagente iniciou",
    "SubagentStop": "🤖 subagente concluiu",
    "TaskCreated": "🧩 tarefa criada",
    "TaskCompleted": "✅ tarefa concluída",
}


async def _handle_monitor(event: str, payload: dict, session_id: str, ctx) -> None:
    """Fase 2: avisos curtos de subagente/tarefa. Schema do payload é incerto —
    lê campos defensivamente. Desligável via MONITOR_EVENTS=off."""
    if not getattr(ctx.cfg, "monitor_events", True):
        return
    detail = _g(payload, "subagent_type", "agent_type", "description",
                "task", "name", "message", default="")
    text = _MONITOR_LABELS[event] + (f": {detail}" if detail else "")
    chat = _chat(ctx, session_id)
    try:
        await ctx.bot.send_message(chat_id=chat, text=text[:500])
    except Exception:
        log.exception("falha enviando aviso de monitoramento")


async def _handle_stop(payload: dict, session_id: str, ctx) -> None:
    # Rótulo de cron (injetado pelo receiver via header): se presente, esta é uma
    # sessão efêmera de cron — colhemos a sessão tmux no finally (cobre TODOS os
    # caminhos de saída: sem texto, dedup, sentinela suprimida ou entrega normal),
    # para o REPL interativo não ficar ocioso até o watchdog. No-op p/ sessão principal.
    cron_label = (_g(payload, "cron_label", "cronLabel", default="") or "").strip()
    try:
        path = _g(payload, "transcript_path", "transcriptPath")
        chat = _chat(ctx, session_id)
        if not path:
            ctx.typing.stop(chat)
            return
        uuid, text = await read_final(path)
        ctx.typing.stop(chat)
        if not text:
            log.info("Stop sessão=%s: sem texto do assistente", session_id)
            return
        if uuid and ctx.state.last_uuid(session_id) == uuid:
            log.info("Stop sessão=%s: dedup, ignorado", session_id)
            return  # dedup
        sentinels = getattr(ctx.cfg, "suppress_sentinels", [])
        if sentinels and text.strip().upper() in sentinels:
            log.info("Stop sessão=%s: sentinela '%s' suprimido (não enviado)", session_id, text.strip())
            if uuid:
                ctx.state.set_last_uuid(session_id, uuid)
            return
        log.info("Stop sessão=%s: enviando %d chars ao chat %s", session_id, len(text), chat)
        await send(ctx.bot, chat, text)
        if uuid:
            ctx.state.set_last_uuid(session_id, uuid)
    finally:
        if cron_label:
            from . import scheduler
            try:
                await scheduler.reap_cron_session(cron_label)
            except Exception:
                log.exception("falha colhendo sessão de cron '%s'", cron_label)


async def _handle_notification(payload: dict, session_id: str, ctx) -> None:
    msg = _g(payload, "message", "body", default="O agente precisa de uma decisão.")
    chat = _chat(ctx, session_id)
    ctx.typing.stop(chat)
    log.info("permission_prompt -> chat %s: %s", chat, str(msg)[:120])
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Permitir", callback_data="perm:allow"),
        InlineKeyboardButton("❌ Negar", callback_data="perm:deny"),
    ]])
    try:
        await ctx.bot.send_message(chat_id=chat, text=f"🔐 {msg}", reply_markup=keyboard)
    except Exception:
        log.exception("falha enviando prompt de permissão")

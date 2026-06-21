"""Handlers do Telegram: gate ALLOWED_USERS, roteamento, comandos e botões."""
import logging
import os
import tempfile

from telegram.ext import CallbackQueryHandler, MessageHandler, filters

from . import router, scheduler as sched_mod, tmux, transcribe

log = logging.getLogger("tgbridge.telegram")

def _help_text(name: str) -> str:
    return (
        f"🤖 *{name} via Telegram*\n\n"
        "• Texto normal → vira prompt na sessão do agente.\n"
        "• /status → o que o agente está fazendo agora.\n"
        "• /stop → interrompe o turno atual (Escape).\n"
        "• /screenshot → últimas linhas do terminal.\n"
        "• /schedule, /schedules, /unschedule → agendamentos.\n"
        "• Qualquer /comando não-reservado vai *verbatim* ao agente "
        "(/compact, /cost, /clear, /context, /memory…).\n"
        "• Use !comando para forçar um nome reservado ao agente (ex.: !status → /status).\n"
        "• 🎙️ Áudio → transcrito e enviado como prompt (se a voz estiver ativada).\n\n"
        f"Quando o {name} pedir permissão (ex.: uma ação sensível), aparece com botões "
        "✅ Permitir / ❌ Negar.\n\n"
        "Agendamento:\n"
        f"/schedule cron 0 9 * * 1-5 | {name} | <prompt da tarefa>\n"
        f"/schedule at 2026-06-12T09:00 | {name} | <prompt da tarefa>"
    )


def register(application, ctx) -> None:
    allowed = filters.User(user_id=ctx.cfg.allowed_users)
    application.add_handler(MessageHandler(allowed & filters.TEXT, _make_handler(ctx)))
    application.add_handler(
        MessageHandler(allowed & (filters.VOICE | filters.AUDIO), _make_voice_handler(ctx))
    )
    application.add_handler(CallbackQueryHandler(_make_callback(ctx)))


async def _dispatch_text(text: str, update, ctx) -> None:
    """Classifica e roteia uma entrada (texto ou voz transcrita)."""
    chat_id = update.effective_chat.id
    kind, payload = router.classify(text)
    log.info("entrada -> %s", kind)
    if kind == "reserved":
        await _reserved(payload, text, update, ctx)
    else:  # passthrough | prompt → vai pro agente; mostra "digitando…"
        await tmux.send_text(ctx.cfg.tmux_session, payload)
        ctx.typing.start(chat_id)


def _make_handler(ctx):
    async def handler(update, _context):
        message = update.effective_message
        text = message.text or ""
        ctx.state.set_kv("default_chat_id", update.effective_chat.id)
        await _dispatch_text(text, update, ctx)

    return handler


def _make_voice_handler(ctx):
    async def handler(update, _context):
        message = update.effective_message
        chat_id = update.effective_chat.id
        ctx.state.set_kv("default_chat_id", chat_id)

        if ctx.cfg.voice_backend == "off":
            await message.reply_text(
                "🎙️ Voz desativada. Defina VOICE_BACKEND=local|openai no .env."
            )
            return

        voice = message.voice or message.audio
        tg_file = await ctx.bot.get_file(voice.file_id)
        fd, path = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)
        try:
            await tg_file.download_to_drive(path)
            text = (await transcribe.transcribe(path, ctx.cfg)).strip()
        except Exception as exc:  # falta de chave, lib ausente, erro de API…
            log.exception("falha transcrevendo áudio")
            await message.reply_text(f"❌ Não consegui transcrever: {exc}")
            return
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        if not text:
            await message.reply_text("🎙️ Não entendi o áudio.")
            return
        await message.reply_text(f"🎙️ _{text}_", parse_mode="Markdown")
        await _dispatch_text(text, update, ctx)

    return handler


def _make_callback(ctx):
    async def on_callback(update, _context):
        query = update.callback_query
        if query.from_user.id not in ctx.cfg.allowed_users:
            await query.answer("não autorizado")
            return
        await query.answer()
        data = query.data or ""
        # Roteia para a sessão que REALMENTE está parada no prompt (pode ser uma sessão
        # efêmera de cron, não a principal). Fallback: sessão principal.
        target = await tmux.find_awaiting_permission(prefer=ctx.cfg.tmux_session) \
            or ctx.cfg.tmux_session
        log.info("botão pressionado: %s -> sessão %s", data, target)
        if data == "perm:allow":
            # Enter confirma a opção destacada por padrão ("Sim, permitir uma vez").
            await tmux.send_keys(target, "Enter")
            suffix = f"\n\n✅ Permitido (sessão `{target}`)."
        elif data == "perm:deny":
            await tmux.send_keys(target, "Escape")
            suffix = f"\n\n❌ Negado (sessão `{target}`)."
        else:
            return
        try:
            await query.edit_message_text((query.message.text or "") + suffix)
        except Exception:
            pass

    return on_callback


async def _reserved(cmd: str, text: str, update, ctx) -> None:
    reply = update.effective_message.reply_text
    chat_id = update.effective_chat.id

    if cmd == "start":
        ctx.state.set_kv("default_chat_id", chat_id)
        await reply(
            f"👋 {ctx.cfg.agent_name} conectado.\n"
            f"Sessão tmux: {ctx.cfg.tmux_session} · provider: {ctx.cfg.default_provider}\n\n"
            f"Mande mensagens normais que viram prompts. /help para os comandos."
        )
    elif cmd == "help":
        await reply(_help_text(ctx.cfg.agent_name), parse_mode="Markdown")
    elif cmd == "status":
        pane = await tmux.capture(ctx.cfg.tmux_session, 25)
        await reply(f"📟 Sessão {ctx.cfg.tmux_session} — últimas linhas:\n\n{pane[-3500:]}")
    elif cmd == "screenshot":
        pane = await tmux.capture(ctx.cfg.tmux_session, 50)
        await reply(pane[-3900:] or "(pane vazio)")
    elif cmd == "stop":
        await tmux.interrupt(ctx.cfg.tmux_session)
        ctx.typing.stop(chat_id)
        await reply("🛑 Enviei Escape — interrompi o turno atual.")
    elif cmd == "schedule":
        await _do_schedule(text, update, ctx)
    elif cmd == "schedules":
        await _list_schedules(update, ctx)
    elif cmd == "unschedule":
        await _unschedule(text, update, ctx)


async def _do_schedule(text: str, update, ctx) -> None:
    reply = update.effective_message.reply_text
    body = text.split(None, 1)
    if len(body) < 2:
        await reply(
            "Uso:\n"
            "/schedule cron <expr 5 campos> | <sessão> | <prompt>\n"
            "/schedule at <ISO8601> | <sessão> | <prompt>"
        )
        return
    try:
        trigger, session, prompt, descr = sched_mod.parse_schedule(body[1], ctx.cfg.tz)
    except Exception as exc:
        await reply(f"❌ {exc}")
        return
    job = ctx.scheduler.add_job(
        sched_mod.run_scheduled_prompt,
        trigger,
        args=[session, prompt, update.effective_chat.id, ctx.cfg.workspace],
        name=descr,
        misfire_grace_time=7200,  # 120 min: tolera disparo atrasado (ex.: bridge fora do ar)
        replace_existing=False,
    )
    await reply(
        f"✅ Agendado (id `{job.id}`)\n{descr}\nsessão: {session}\nprompt: {prompt}",
        parse_mode="Markdown",
    )


async def _list_schedules(update, ctx) -> None:
    jobs = ctx.scheduler.get_jobs()
    if not jobs:
        await update.effective_message.reply_text("Nenhum agendamento.")
        return
    lines = []
    for j in jobs:
        nxt = j.next_run_time.strftime("%Y-%m-%d %H:%M %Z") if j.next_run_time else "—"
        prompt = j.args[1] if len(j.args) > 1 else ""
        lines.append(f"• {j.id} | {j.name} | próximo: {nxt}\n   → {prompt[:80]}")
    await update.effective_message.reply_text("📅 Agendamentos:\n" + "\n".join(lines))


async def _unschedule(text: str, update, ctx) -> None:
    parts = text.split()
    if len(parts) < 2:
        await update.effective_message.reply_text("Uso: /unschedule <id>")
        return
    try:
        ctx.scheduler.remove_job(parts[1])
        await update.effective_message.reply_text(f"🗑️ Removido: {parts[1]}")
    except Exception:
        await update.effective_message.reply_text(f"❌ Não encontrei o job {parts[1]}")

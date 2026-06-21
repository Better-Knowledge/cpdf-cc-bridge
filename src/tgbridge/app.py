"""Orquestrador: Telegram (polling) + receiver de hooks (uvicorn) + scheduler,
num único event loop asyncio."""
import asyncio
import logging

import uvicorn
from telegram.ext import ApplicationBuilder

from . import hooks_install, hooks_receiver, notifier, telegram_io
from .scheduler import build_scheduler
from .state import State

log = logging.getLogger("tgbridge")


class Typing:
    """Mantém o indicador 'digitando…' no Telegram enquanto o agente trabalha."""

    def __init__(self, bot):
        self._bot = bot
        self._tasks = {}

    def start(self, chat_id: int) -> None:
        task = self._tasks.get(chat_id)
        if task and not task.done():
            return
        self._tasks[chat_id] = asyncio.create_task(self._loop(chat_id))

    async def _loop(self, chat_id: int) -> None:
        try:
            while True:
                try:
                    await self._bot.send_chat_action(chat_id=chat_id, action="typing")
                except Exception:
                    pass
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    def stop(self, chat_id: int) -> None:
        task = self._tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()


class Ctx:
    def __init__(self, cfg, state, application, queue, scheduler):
        self.cfg = cfg
        self.state = state
        self.application = application
        self.queue = queue
        self.scheduler = scheduler
        self.typing = Typing(application.bot)

    @property
    def bot(self):
        return self.application.bot


async def _event_worker(ctx: Ctx) -> None:
    while True:
        payload = await ctx.queue.get()
        try:
            await notifier.handle_event(payload, ctx)
        except Exception:
            log.exception("erro processando evento de hook")
        finally:
            ctx.queue.task_done()


async def run(cfg) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Não vazar o bot token nos logs: httpx loga a URL `…/bot<TOKEN>/getMe` em INFO;
    # quem tiver `docker logs` veria o token. Sobe esses loggers para WARNING.
    for noisy in ("httpx", "httpcore", "telegram.request"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    hooks_install.ensure(cfg)

    if cfg.voice_backend == "openai" and not cfg.openai_api_key:
        log.warning("VOICE_BACKEND=openai mas OPENAI_API_KEY está vazio — voz vai falhar.")

    state = State(cfg.state_db)
    application = ApplicationBuilder().token(cfg.bot_token).build()
    queue: asyncio.Queue = asyncio.Queue()
    scheduler = build_scheduler(cfg)
    ctx = Ctx(cfg, state, application, queue, scheduler)

    # Watchdog das sessões de cron avisa timeouts no Telegram via notifier.
    from . import scheduler as sched_mod

    async def _notify_cron_timeout(chat_id, text):
        await notifier.send(ctx.bot, int(chat_id), text)

    sched_mod.set_notifier(_notify_cron_timeout)

    telegram_io.register(application, ctx)
    fastapi_app = hooks_receiver.make_app(ctx)
    server = uvicorn.Server(
        uvicorn.Config(fastapi_app, host="127.0.0.1", port=cfg.port, log_level="warning")
    )

    # A2A: servidor separado na rede compartilhada (não publicado no host).
    a2a_server = None
    if cfg.a2a_enabled:
        from . import a2a
        a2a_server = uvicorn.Server(
            uvicorn.Config(a2a.make_a2a_app(ctx), host="0.0.0.0", port=cfg.a2a_port,
                           log_level="warning")
        )

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    # Re-assume sessões de cron órfãs antes de o scheduler disparar jobs novos: o watchdog
    # vive em memória e se perde quando o processo da bridge reinicia (tmux sobrevive).
    try:
        await sched_mod.rearm_cron_watchdogs(cfg.default_chat_id, cfg.tmux_session)
    except Exception:
        log.exception("startup: falha na varredura de sessões de cron órfãs")
    scheduler.start()
    log.info(
        "tgbridge no ar — Telegram polling, receiver 127.0.0.1:%s, scheduler ativo (sessão=%s)",
        cfg.port, cfg.tmux_session,
    )

    tasks = [
        asyncio.create_task(_event_worker(ctx), name="event-worker"),
        asyncio.create_task(server.serve(), name="uvicorn"),
    ]
    if a2a_server is not None:
        log.info("A2A no ar — 0.0.0.0:%s (agente=%s)", cfg.a2a_port, cfg.agent_name)
        tasks.append(asyncio.create_task(a2a_server.serve(), name="uvicorn-a2a"))
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        try:
            await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
            await application.shutdown()
        except Exception:
            pass
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

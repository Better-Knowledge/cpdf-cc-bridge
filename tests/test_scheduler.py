import asyncio

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from tgbridge import scheduler as sched_mod
from tgbridge.scheduler import parse_schedule, parse_when, run_scheduled_prompt

TZ = "America/Sao_Paulo"


def test_parse_cron():
    trigger, session, prompt, descr = parse_schedule(
        "cron 0 9 * * 1-5 | alice | rode acoes_hoje", TZ)
    assert isinstance(trigger, CronTrigger)
    assert session == "alice"
    assert prompt == "rode acoes_hoje"
    assert descr == "cron 0 9 * * 1-5"


def test_parse_at():
    trigger, session, prompt, descr = parse_schedule(
        "at 2026-06-12T09:00 | alice | gere o relatório", TZ)
    assert isinstance(trigger, DateTrigger)
    assert session == "alice"
    assert prompt == "gere o relatório"


def test_prompt_with_pipe_is_preserved():
    _, _, prompt, _ = parse_schedule("cron 0 9 * * * | g | faça a|b|c", TZ)
    assert prompt == "faça a|b|c"


def test_missing_parts():
    with pytest.raises(ValueError):
        parse_schedule("cron 0 9 * * *", TZ)


def test_bad_mode():
    with pytest.raises(ValueError):
        parse_schedule("daily | g | p", TZ)


# --- parse_when (endpoint) ---

def test_parse_when_cron():
    trigger, descr = parse_when("cron 0 6-22/2 * * *", TZ)
    assert isinstance(trigger, CronTrigger)
    assert descr == "cron 0 6-22/2 * * *"


def test_parse_when_at():
    trigger, descr = parse_when("at 2026-06-16T14:00", TZ)
    assert isinstance(trigger, DateTrigger)


def test_parse_when_bad():
    with pytest.raises(ValueError):
        parse_when("daily", TZ)


# --- execução efêmera (mock tmux) ---

def test_run_scheduled_prompt_ephemeral(monkeypatch):
    calls = []
    sched_mod._watchdogs.clear()

    async def fake_kill(s): calls.append(("kill", s))
    async def fake_new(s, cwd, **kw): calls.append(("new", s, cwd, kw))
    async def fake_setopt(s, name, value): calls.append(("setopt", s, name, value))
    async def fake_ready(s, **kw): calls.append(("ready", s)); return True
    async def fake_send(s, text): calls.append(("send", s, text))
    async def fake_keys(s, *keys): calls.append(("keys", s, keys))
    async def fake_has(s): return False                # watchdog: sessão já terminou → no-op
    async def fake_sleep(_): pass  # sem esperar os delays de assentamento

    monkeypatch.setattr(sched_mod.tmux, "kill_session", fake_kill)
    monkeypatch.setattr(sched_mod.tmux, "new_session", fake_new)
    monkeypatch.setattr(sched_mod.tmux, "set_option", fake_setopt)
    monkeypatch.setattr(sched_mod.tmux, "wait_ready", fake_ready)
    monkeypatch.setattr(sched_mod.tmux, "send_text", fake_send)
    monkeypatch.setattr(sched_mod.tmux, "send_keys", fake_keys)
    monkeypatch.setattr(sched_mod.tmux, "has_session", fake_has)
    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)

    asyncio.run(run_scheduled_prompt("briefing", "monte o briefing", 42, "/home/bob"))

    kinds = [c[0] for c in calls]
    # mata, cria, marca @cron, espera, envia, reforça Enter
    assert kinds == ["kill", "new", "setopt", "ready", "send", "keys"]
    assert calls[0][1] == "cron-briefing"              # sessão efêmera por job
    assert calls[1][2] == "/home/bob"                # cwd = workspace
    assert calls[2][1:] == ("cron-briefing", "@cron", "briefing")  # marcador de cron
    # cron roda via argv com env-scrub: `env -u <segredos> … claude …`. Mantém
    # BRIDGE_HOOK_SECRET (Stop hook entrega a saída); remove A2A_SECRET + TELEGRAM_BOT_TOKEN.
    cmd = calls[1][3]["cmd"]
    assert cmd[0] == "env" and "claude" in cmd
    for sec in ("A2A_SECRET", "TELEGRAM_BOT_TOKEN"):
        assert sec in cmd
    assert "BRIDGE_HOOK_SECRET" not in cmd
    assert calls[4][2] == "monte o briefing"
    assert calls[5][2] == ("Enter",)                   # reforço de submit


def test_cron_cmd_bypass_mode(monkeypatch):
    monkeypatch.setattr(sched_mod, "CRON_PERMISSION_MODE", "bypassPermissions")
    cmd = sched_mod._cron_cmd()
    # cron scrub: A2A_SECRET + A2A_PEER_SECRETS + TELEGRAM_BOT_TOKEN + IS_SANDBOX=1 (mantém BRIDGE_HOOK_SECRET)
    assert cmd[:8] == ["env", "-u", "A2A_SECRET", "-u", "A2A_PEER_SECRETS",
                       "-u", "TELEGRAM_BOT_TOKEN", "IS_SANDBOX=1"]
    assert "BRIDGE_HOOK_SECRET" not in cmd        # Stop hook precisa dele no env
    i = cmd.index("claude")
    assert cmd[i + 1:i + 3] == ["--permission-mode", "bypassPermissions"]
    assert "--append-system-prompt" in cmd


def test_cron_cmd_default_mode(monkeypatch):
    monkeypatch.setattr(sched_mod, "CRON_PERMISSION_MODE", "default")
    cmd = sched_mod._cron_cmd()
    # default → claude puro (sem IS_SANDBOX / --permission-mode), MAS ainda com env-scrub
    assert "IS_SANDBOX=1" not in cmd and "--permission-mode" not in cmd
    assert cmd[:7] == ["env", "-u", "A2A_SECRET", "-u", "A2A_PEER_SECRETS", "-u", "TELEGRAM_BOT_TOKEN"]
    assert cmd[7] == "claude" and "--append-system-prompt" in cmd
    assert "BRIDGE_HOOK_SECRET" not in cmd


def test_cron_cmd_with_model(monkeypatch):
    monkeypatch.setattr(sched_mod, "CRON_PERMISSION_MODE", "bypassPermissions")
    cmd = sched_mod._cron_cmd("haiku")
    i = cmd.index("claude")
    assert cmd[i + 1:i + 3] == ["--model", "haiku"]                   # --model logo após claude
    assert cmd[i + 3:i + 5] == ["--permission-mode", "bypassPermissions"]
    assert "--model" not in sched_mod._cron_cmd("")                   # sem model → sem --model


def test_cron_model_resolution(monkeypatch):
    monkeypatch.delenv("CRON_MODEL", raising=False)
    monkeypatch.delenv("CRON_MODEL_HEARTBEAT", raising=False)
    assert sched_mod._cron_model("heartbeat") == ""                  # nada setado → vazio
    monkeypatch.setenv("CRON_MODEL", "sonnet")
    monkeypatch.setenv("CRON_MODEL_HEARTBEAT", "haiku")
    assert sched_mod._cron_model("heartbeat") == "haiku"             # override por label
    assert sched_mod._cron_model("checagem-agenda-bk") == "sonnet"  # cai no global


def test_cron_cmd_injects_label(monkeypatch):
    # O rótulo do job entra no env da sessão como K=V (depois dos -u do env-scrub e
    # antes do binário claude) → o hook Stop o reflete num header p/ colher a sessão.
    monkeypatch.setattr(sched_mod, "CRON_PERMISSION_MODE", "bypassPermissions")
    cmd = sched_mod._cron_cmd("sonnet", "briefing-matinal")
    assert "TGBRIDGE_CRON_LABEL=briefing-matinal" in cmd
    i_lbl = cmd.index("TGBRIDGE_CRON_LABEL=briefing-matinal")
    assert cmd.index("claude") > i_lbl                       # K=V antes do binário
    for sec in ("A2A_SECRET", "TELEGRAM_BOT_TOKEN"):         # todos os -u antes do K=V
        assert cmd.index(sec) < i_lbl
    # sem label (sessão principal / chamada legada) → sem a var
    assert not any(c.startswith("TGBRIDGE_CRON_LABEL=") for c in sched_mod._cron_cmd("sonnet"))


def test_reap_cron_session(monkeypatch):
    # Colhe a sessão efêmera assim que o cron entrega: mata a sessão tmux certa e
    # cancela o watchdog (senão o REPL interativo fica ocioso até o timeout → falso alarme).
    import asyncio as aio
    sched_mod._watchdogs.clear()
    killed = []

    async def fake_has(s): return True
    async def fake_kill(s): killed.append(s)
    monkeypatch.setattr(sched_mod.tmux, "has_session", fake_has)
    monkeypatch.setattr(sched_mod.tmux, "kill_session", fake_kill)

    async def scenario():
        wd = aio.create_task(aio.Event().wait())            # watchdog "vivo" do label
        sched_mod._watchdogs["briefing"] = wd
        assert await sched_mod.reap_cron_session("briefing") is True
        assert killed == ["cron-briefing"]                  # matou a sessão certa
        assert "briefing" not in sched_mod._watchdogs       # tirou do registro
        for _ in range(10):
            if wd.done():
                break
            await aio.sleep(0)
        assert wd.cancelled()                               # watchdog cancelado

    aio.run(scenario())
    sched_mod._watchdogs.clear()


def test_reap_cron_session_noops(monkeypatch):
    import asyncio as aio

    async def fake_has(s): return False
    async def fake_kill(s): raise AssertionError("não deve matar nada")
    monkeypatch.setattr(sched_mod.tmux, "has_session", fake_has)
    monkeypatch.setattr(sched_mod.tmux, "kill_session", fake_kill)

    async def scenario():
        assert await sched_mod.reap_cron_session("") is False           # rótulo vazio (sessão principal)
        assert await sched_mod.reap_cron_session("nao-existe") is False  # sessão inexistente

    aio.run(scenario())


def test_watchdog_cancelled_on_refire(monkeypatch):
    # Re-disparar o mesmo label cancela o watchdog anterior → ele NÃO dispara o falso
    # "excedeu N min" matando a sessão nova. (regressão do bug do heartbeat */30 vs timeout 120m)
    import asyncio as aio
    sched_mod._watchdogs.clear()
    real_sleep = aio.sleep
    interrupted = []

    async def noop(*a, **k):
        return True

    async def fake_interrupt(s):
        interrupted.append(s)        # só é chamado se o watchdog DISPARAR o timeout

    async def fast_sleep(d, *a, **k):
        if d and d >= 60:
            await aio.Event().wait()  # o sleep longo do watchdog: fica pendente até cancelar
        else:
            await real_sleep(0)       # sleeps curtos do run_scheduled_prompt: instantâneos

    for name in ("kill_session", "new_session", "set_option", "wait_ready",
                 "send_text", "send_keys", "has_session"):
        monkeypatch.setattr(sched_mod.tmux, name, noop)
    monkeypatch.setattr(sched_mod.tmux, "interrupt", fake_interrupt)
    monkeypatch.setattr(sched_mod.asyncio, "sleep", fast_sleep)

    async def scenario():
        await run_scheduled_prompt("x", "p", 1)
        w1 = sched_mod._watchdogs.get("x")
        assert w1 is not None
        await run_scheduled_prompt("x", "p", 1)            # re-disparo do MESMO label
        w2 = sched_mod._watchdogs.get("x")
        assert w2 is not None and w2 is not w1             # watchdog novo substituiu o antigo
        for _ in range(10):
            if w1.done():
                break
            await real_sleep(0)
        assert w1.done()                                   # o antigo encerrou…
        assert interrupted == []                           # …sem disparar o timeout (sem falso alarme)
        w2.cancel()

    aio.run(scenario())
    sched_mod._watchdogs.clear()


# --- re-arm de startup (resiliência a restart da bridge) ---

def test_rearm_cron_watchdogs(monkeypatch):
    # No startup: mata sessões de cron que JÁ estouraram o timeout, re-arma (tempo
    # restante) as jovens, e NUNCA toca a sessão principal nem sessões não-cron.
    import asyncio as aio
    sched_mod._watchdogs.clear()
    NOW, TIMEOUT = 1_000_000, 100
    monkeypatch.setattr(sched_mod, "CRON_SESSION_TIMEOUT_S", TIMEOUT)
    monkeypatch.setattr(sched_mod.time, "time", lambda: NOW)

    meta = [
        ("alice",        NOW - 5,   ""),           # sessão principal → intocável
        ("cron-old",     NOW - 500, ""),           # cron via prefixo, velha → reap
        ("cron-young",   NOW - 10,  ""),           # cron via prefixo, jovem → re-arm (90s)
        ("a2a-foo-bar",  NOW - 500, ""),           # não-cron (sem prefixo/@cron) → ignorada
        ("weird",        NOW - 500, "heartbeat"),   # @cron setado, nome qualquer, velha → reap
        ("cron-badts",   0,         ""),           # timestamp inválido → re-arm conservador (cheio)
    ]
    killed, interrupted, rearmed, notified = [], [], [], []

    async def fake_meta(): return meta
    async def fake_interrupt(s): interrupted.append(s)
    async def fake_kill(s): killed.append(s)
    async def fake_sleep(_): pass
    async def fake_watchdog(session, label, chat_id, timeout_s=None):
        rearmed.append((session, label, timeout_s))
    async def fake_notify(chat, text): notified.append((chat, text))

    monkeypatch.setattr(sched_mod.tmux, "list_cron_meta", fake_meta)
    monkeypatch.setattr(sched_mod.tmux, "interrupt", fake_interrupt)
    monkeypatch.setattr(sched_mod.tmux, "kill_session", fake_kill)
    monkeypatch.setattr(sched_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched_mod, "_session_watchdog", fake_watchdog)
    sched_mod.set_notifier(fake_notify)

    aio.run(sched_mod.rearm_cron_watchdogs(42, "alice"))

    # Reap só das velhas reconhecidas como cron (prefixo OU @cron); principal e a2a fora.
    assert set(killed) == {"cron-old", "weird"}
    assert set(interrupted) == {"cron-old", "weird"}
    assert "alice" not in killed and "a2a-foo-bar" not in killed
    # Re-arm das jovens + timestamp inválido (com tempo restante correto).
    by_label = {label: (session, timeout_s) for session, label, timeout_s in rearmed}
    assert by_label["young"] == ("cron-young", TIMEOUT - 10)      # restante = timeout - idade
    assert by_label["badts"] == ("cron-badts", TIMEOUT)           # inválido → timeout cheio
    assert "old" not in by_label and "heartbeat" not in by_label   # velhas não re-armam
    assert set(sched_mod._watchdogs) == {"young", "badts"}
    # Uma notificação-resumo, para o chat certo, mencionando as 2 reapadas.
    assert len(notified) == 1 and notified[0][0] == 42 and "2" in notified[0][1]

    sched_mod.set_notifier(None)
    sched_mod._watchdogs.clear()


def test_rearm_cron_watchdogs_empty(monkeypatch):
    # Sem sessões (container recém-criado) → no-op silencioso, sem notificação.
    import asyncio as aio
    sched_mod._watchdogs.clear()
    notified = []

    async def fake_meta(): return []
    async def fake_notify(chat, text): notified.append(text)
    monkeypatch.setattr(sched_mod.tmux, "list_cron_meta", fake_meta)
    sched_mod.set_notifier(fake_notify)

    aio.run(sched_mod.rearm_cron_watchdogs(42, "alice"))
    assert notified == [] and sched_mod._watchdogs == {}
    sched_mod.set_notifier(None)

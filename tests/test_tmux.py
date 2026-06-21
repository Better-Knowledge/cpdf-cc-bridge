import asyncio

from tgbridge import tmux


def _capture_run(monkeypatch):
    """Substitui tmux._run e devolve a lista de chamadas (cada uma = args do tmux)."""
    calls = []

    async def fake_run(*args):
        calls.append(list(args))
        return (0, "", "")

    monkeypatch.setattr(tmux, "_run", fake_run)
    return calls


def test_norm_sanitizes():
    assert tmux.norm("a2a/bob foo") == "a2a-bob-foo"


def test_new_session_plain(monkeypatch):
    calls = _capture_run(monkeypatch)
    asyncio.run(tmux.new_session("s", cwd="/w"))
    args = calls[0]
    assert args[0] == "new-session" and args[-1] == "claude"
    assert "env" not in args            # sem env-scrub → sem prefixo `env`


def test_new_session_env_scrub_prefix(monkeypatch):
    calls = _capture_run(monkeypatch)
    asyncio.run(tmux.new_session(
        "s", cwd="/w",
        env_unset=["A2A_SECRET", "BRIDGE_HOOK_SECRET", "TELEGRAM_BOT_TOKEN"],
        env_set={"A2A_INBOUND": "1"},
    ))
    args = calls[0]
    tail = args[args.index("env"):]
    assert tail == ["env", "-u", "A2A_SECRET", "-u", "BRIDGE_HOOK_SECRET",
                    "-u", "TELEGRAM_BOT_TOKEN", "A2A_INBOUND=1", "claude"]


def test_new_session_argv_cmd(monkeypatch):
    calls = _capture_run(monkeypatch)
    asyncio.run(tmux.new_session("s", cwd="/w",
                                 cmd=["claude", "--permission-mode", "bypassPermissions"]))
    assert calls[0][-3:] == ["claude", "--permission-mode", "bypassPermissions"]


def test_new_session_argv_with_env_scrub(monkeypatch):
    calls = _capture_run(monkeypatch)
    asyncio.run(tmux.new_session("s", cwd="/w",
                                 cmd=["claude", "--permission-mode", "bypassPermissions"],
                                 env_unset=["A2A_SECRET"]))
    args = calls[0]
    tail = args[args.index("env"):]
    assert tail == ["env", "-u", "A2A_SECRET", "claude", "--permission-mode", "bypassPermissions"]


def test_list_sessions(monkeypatch):
    async def fake_run(*args):
        return (0, "bob\ncron-x\n", "")
    monkeypatch.setattr(tmux, "_run", fake_run)
    assert asyncio.run(tmux.list_sessions()) == ["bob", "cron-x"]


def test_find_awaiting_permission_picks_stuck_session(monkeypatch):
    async def fake_list():
        return ["bob", "cron-x"]

    async def fake_capture(name, lines=40):
        return "Do you want to proceed?\n  Esc to cancel" if name == "cron-x" else "❯ pronto"

    monkeypatch.setattr(tmux, "list_sessions", fake_list)
    monkeypatch.setattr(tmux, "capture", fake_capture)
    assert asyncio.run(tmux.find_awaiting_permission(prefer="bob")) == "cron-x"


def test_find_awaiting_permission_none(monkeypatch):
    async def fake_list():
        return ["bob"]

    async def fake_capture(name, lines=40):
        return "❯ pronto"

    monkeypatch.setattr(tmux, "list_sessions", fake_list)
    monkeypatch.setattr(tmux, "capture", fake_capture)
    assert asyncio.run(tmux.find_awaiting_permission()) is None

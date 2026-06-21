import asyncio
import json
from types import SimpleNamespace

from tgbridge import notifier
from tgbridge.notifier import extract_last_assistant, split_message


def _write(tmp_path, records):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return str(p)


def test_extract_skips_trailing_metadata_and_tooluse(tmp_path):
    records = [
        {"type": "user", "message": {"content": [{"type": "text", "text": "oi"}]}},
        {"type": "assistant", "uuid": "a1",
         "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}},
        {"type": "assistant", "uuid": "a2",
         "message": {"content": [{"type": "text", "text": "Resposta final."}]}},
        {"type": "assistant", "uuid": "a3",
         "message": {"content": [{"type": "tool_use", "name": "X", "input": {}}]}},
        {"type": "file-history-snapshot", "snapshot": {}},
    ]
    uuid, text = extract_last_assistant(_write(tmp_path, records))
    assert uuid == "a2"
    assert text == "Resposta final."


def test_extract_joins_multiple_text_blocks(tmp_path):
    records = [
        {"type": "assistant", "uuid": "z",
         "message": {"content": [
             {"type": "text", "text": "linha 1"},
             {"type": "text", "text": "linha 2"},
         ]}},
    ]
    uuid, text = extract_last_assistant(_write(tmp_path, records))
    assert uuid == "z"
    assert text == "linha 1\nlinha 2"


def test_extract_missing_file():
    assert extract_last_assistant("/nao/existe.jsonl") == (None, None)


def test_split_respects_limit():
    text = "\n".join(f"linha {i}" for i in range(500))
    chunks = split_message(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "\n".join(chunks).count("linha 0") == 1


def test_split_hard_splits_long_line():
    chunks = split_message("x" * 5000, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == "x" * 5000


# --- Fase 2: monitoramento ---

class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def _mon_ctx(monitor_events=True):
    bot = _FakeBot()
    state = SimpleNamespace(
        chat_for_session=lambda s: None,
        get_kv=lambda k, d=None: 42,
    )
    cfg = SimpleNamespace(monitor_events=monitor_events, default_chat_id=42)
    return SimpleNamespace(bot=bot, state=state, cfg=cfg), bot


def test_monitor_sends_label_and_detail():
    ctx, bot = _mon_ctx()
    asyncio.run(notifier.handle_event(
        {"hook_event_name": "SubagentStop", "session_id": "s", "subagent_type": "Explore"}, ctx))
    assert bot.sent == [(42, "🤖 subagente concluiu: Explore")]


def test_monitor_task_completed_no_detail():
    ctx, bot = _mon_ctx()
    asyncio.run(notifier.handle_event(
        {"hook_event_name": "TaskCompleted", "session_id": "s"}, ctx))
    assert bot.sent == [(42, "✅ tarefa concluída")]


def test_monitor_disabled():
    ctx, bot = _mon_ctx(monitor_events=False)
    asyncio.run(notifier.handle_event(
        {"hook_event_name": "SubagentStart", "session_id": "s"}, ctx))
    assert bot.sent == []


# --- supressão de sentinela no Stop ---

class _Typing:
    def stop(self, chat_id): pass


class _State2:
    def __init__(self):
        self.saved = []
    def chat_for_session(self, s): return None
    def get_kv(self, k, d=None): return 42
    def last_uuid(self, s): return None
    def set_last_uuid(self, s, u): self.saved.append((s, u))


def _stop_ctx():
    bot = _FakeBot()
    cfg = SimpleNamespace(
        suppress_sentinels=["NO_NEWS", "HEARTBEAT_OK"], default_chat_id=42, monitor_events=True)
    return SimpleNamespace(bot=bot, state=_State2(), cfg=cfg, typing=_Typing()), bot


def test_stop_suppresses_sentinel(monkeypatch):
    async def fake_read_final(path, **kw): return ("u1", "NO_NEWS")
    monkeypatch.setattr(notifier, "read_final", fake_read_final)
    ctx, bot = _stop_ctx()
    asyncio.run(notifier.handle_event(
        {"hook_event_name": "Stop", "session_id": "s", "transcript_path": "/x"}, ctx))
    assert bot.sent == []                     # suprimido
    assert ctx.state.saved == [("s", "u1")]   # dedup gravado mesmo suprimindo


def test_stop_sends_normal(monkeypatch):
    async def fake_read_final(path, **kw): return ("u2", "olá mundo")
    monkeypatch.setattr(notifier, "read_final", fake_read_final)
    ctx, bot = _stop_ctx()
    asyncio.run(notifier.handle_event(
        {"hook_event_name": "Stop", "session_id": "s", "transcript_path": "/x"}, ctx))
    assert bot.sent and "mundo" in bot.sent[0][1]

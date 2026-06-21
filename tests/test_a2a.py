from types import SimpleNamespace

from fastapi.testclient import TestClient

from tgbridge import a2a

AUTH = {"Authorization": "Bearer a2asek"}


class _FakeBot:
    def __init__(self): self.sent = []
    async def send_message(self, chat_id, text, **kw): self.sent.append((chat_id, text))


def _client(monkeypatch, notify=True, allowed=None, rate_max=1000, rate_window=300):
    async def fake_capture(sender, message, ctx, timeout=120.0):
        return f"resposta-para-{sender}: {message[::-1]}"
    monkeypatch.setattr(a2a, "run_and_capture", fake_capture)
    bot = _FakeBot()
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(a2a_secret="a2asek", agent_name="alice",
                            a2a_notify=notify, default_chat_id=42,
                            a2a_allowed_senders=allowed or [],
                            a2a_rate_max=rate_max, a2a_rate_window=rate_window,
                            workspace="/nonexistent"),   # sem registry → allow-all por padrão
        state=SimpleNamespace(get_kv=lambda k, d=None: 42),
        bot=bot,
    )
    return TestClient(a2a.make_a2a_app(ctx)), bot


def test_health(monkeypatch):
    c, _ = _client(monkeypatch)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["agent"] == "alice"


def test_message_requires_auth(monkeypatch):
    c, _ = _client(monkeypatch)
    assert c.post("/message", json={"from": "bob", "message": "oi"}).status_code == 401


def test_message_rpc(monkeypatch):
    c, bot = _client(monkeypatch)
    r = c.post("/message", headers=AUTH, json={"from": "bob", "message": "ping"})
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == "alice"
    assert body["answer"] == "resposta-para-bob: gnip"
    assert bot.sent and "bob" in bot.sent[0][1]   # notify postado


def test_message_empty(monkeypatch):
    c, _ = _client(monkeypatch)
    assert c.post("/message", headers=AUTH, json={"from": "bob", "message": ""}).status_code == 400


def test_notify_off(monkeypatch):
    c, bot = _client(monkeypatch, notify=False)
    c.post("/message", headers=AUTH, json={"from": "bob", "message": "x"})
    assert bot.sent == []


def test_sender_allowlist_blocks_unknown(monkeypatch):
    c, _ = _client(monkeypatch, allowed=["bob"])
    # remetente fora da allowlist → 403
    assert c.post("/message", headers=AUTH,
                  json={"from": "mallory", "message": "oi"}).status_code == 403
    # remetente permitido → 200
    assert c.post("/message", headers=AUTH,
                  json={"from": "bob", "message": "oi"}).status_code == 200


def test_rate_limit(monkeypatch):
    c, _ = _client(monkeypatch, rate_max=2)
    assert c.post("/message", headers=AUTH, json={"from": "bob", "message": "1"}).status_code == 200
    assert c.post("/message", headers=AUTH, json={"from": "bob", "message": "2"}).status_code == 200
    assert c.post("/message", headers=AUTH, json={"from": "bob", "message": "3"}).status_code == 429


def test_notify_sender_sanitized(monkeypatch):
    c, bot = _client(monkeypatch)
    c.post("/message", headers=AUTH, json={"from": "bob\nINJETADO", "message": "x"})
    assert bot.sent
    text = bot.sent[0][1]
    assert "\n" not in text                 # newline do remetente não vaza pro Telegram
    assert "bob INJETADO" in text

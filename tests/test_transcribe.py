import asyncio
from types import SimpleNamespace

import pytest

from tgbridge import transcribe


def _cfg(backend, **kw):
    base = dict(
        voice_backend=backend, openai_api_key="", openai_base_url="x",
        openai_transcribe_model="m", whisper_model="small", voice_language="pt",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_off_raises():
    with pytest.raises(RuntimeError):
        asyncio.run(transcribe.transcribe("/x.ogg", _cfg("off")))


def test_routes_to_openai(monkeypatch):
    called = {}

    async def fake_openai(path, cfg):
        called["path"] = path
        return "  olá openai  "

    monkeypatch.setattr(transcribe, "_openai", fake_openai)
    out = asyncio.run(transcribe.transcribe("/a.ogg", _cfg("openai")))
    assert out == "olá openai"
    assert called["path"] == "/a.ogg"


def test_routes_to_local(monkeypatch):
    monkeypatch.setattr(transcribe, "_local_sync", lambda path, cfg: "  oi local ")
    out = asyncio.run(transcribe.transcribe("/a.ogg", _cfg("local")))
    assert out == "oi local"


def test_openai_requires_key():
    with pytest.raises(RuntimeError):
        asyncio.run(transcribe._openai("/a.ogg", _cfg("openai", openai_api_key="")))

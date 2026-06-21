"""Auth do microserviço whisper (template). Testa o gate `_check_auth` direto
para não depender de python-multipart (upload), e confirma que /health é aberto."""
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

WHISPER_APP = (
    Path(__file__).resolve().parents[1]
    / "src" / "tgbridge" / "templates" / "whisper" / "app.py"
)


def _load_app(monkeypatch, secret=None):
    # WHISPER_SECRET é lido no import → setar antes de carregar o módulo.
    if secret is None:
        monkeypatch.delenv("WHISPER_SECRET", raising=False)
    else:
        monkeypatch.setenv("WHISPER_SECRET", secret)
    spec = importlib.util.spec_from_file_location("whisperd_under_test", WHISPER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_auth_requires_bearer_when_secret_set(monkeypatch):
    mod = _load_app(monkeypatch, secret="sek")
    mod._check_auth("Bearer sek")                      # correto → não levanta
    with pytest.raises(HTTPException) as ei:
        mod._check_auth("")                            # sem header
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException):
        mod._check_auth("Bearer errado")               # token errado


def test_check_auth_open_when_no_secret(monkeypatch):
    mod = _load_app(monkeypatch, secret=None)
    mod._check_auth("")                                # compat: aberto, não levanta
    mod._check_auth("Bearer qualquer")


def test_health_is_open(monkeypatch):
    mod = _load_app(monkeypatch, secret="sek")
    assert TestClient(mod.app).get("/health").status_code == 200

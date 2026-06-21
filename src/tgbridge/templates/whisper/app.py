"""Microserviço Whisper compartilhado — endpoint compatível com a API da OpenAI.

Expõe POST /v1/audio/transcriptions (mesmo contrato do endpoint da OpenAI), de modo
que os agentes reusam o backend `openai` do tgbridge apenas trocando OPENAI_BASE_URL.
Um único processo/modelo serve N agentes (economia de disco e RAM).
"""
import asyncio
import logging
import os
import tempfile

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("whisperd")

MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
DEFAULT_LANG = os.environ.get("WHISPER_LANGUAGE", "pt")

# Auth opcional: se WHISPER_SECRET setado, exige `Authorization: Bearer <secret>`
# (o agente manda como OPENAI_API_KEY). Vazio = aberto (compat com deploys atuais).
WHISPER_SECRET = os.environ.get("WHISPER_SECRET", "").strip()


def _check_auth(authorization: str) -> None:
    if WHISPER_SECRET and authorization != f"Bearer {WHISPER_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")

app = FastAPI(title="tgbridge-whisper", version="1.0")
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("carregando faster-whisper '%s' (%s/%s)…", MODEL_NAME, DEVICE, COMPUTE_TYPE)
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def _transcribe_sync(path: str, language: str) -> str:
    segments, _info = _get_model().transcribe(path, language=language or None)
    return " ".join(seg.text.strip() for seg in segments).strip()


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default=MODEL_NAME),   # aceito e ignorado (modelo é do servidor)
    language: str = Form(default=DEFAULT_LANG),
    response_format: str = Form(default="json"),
    prompt: str = Form(default=""),
    temperature: str = Form(default=""),
    authorization: str = Header(default=""),
):
    _check_auth(authorization)
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or "")[1] or ".ogg")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(await file.read())
        text = await asyncio.to_thread(_transcribe_sync, path, language)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if response_format == "text":
        return text
    return {"text": text}

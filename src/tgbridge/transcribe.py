"""Transcrição de voz plugável: off | local (faster-whisper) | openai.

Interface única: `await transcribe(path, cfg) -> str`. Imports das libs de cada
backend são lazy (só pesam quando o backend é usado). O handler de voz no
telegram_io chama daqui; a saída segue o mesmo caminho de um prompt de texto.
"""
import asyncio
import logging

log = logging.getLogger("tgbridge.transcribe")

_whisper_model = None  # singleton: carregar o modelo por request é caro


async def transcribe(path: str, cfg) -> str:
    backend = (cfg.voice_backend or "off").lower()
    if backend == "openai":
        return (await _openai(path, cfg)).strip()
    if backend == "local":
        return (await asyncio.to_thread(_local_sync, path, cfg)).strip()
    raise RuntimeError("VOICE_BACKEND=off (transcrição de voz desativada)")


async def _openai(path: str, cfg) -> str:
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY ausente no .env (VOICE_BACKEND=openai).")
    from openai import AsyncOpenAI  # lazy

    client = AsyncOpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_base_url)
    with open(path, "rb") as f:
        resp = await client.audio.transcriptions.create(
            model=cfg.openai_transcribe_model,
            file=f,
            language=cfg.voice_language or None,
        )
    return getattr(resp, "text", "") or ""


def _get_local_model(cfg):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel  # lazy

        log.info("carregando faster-whisper (%s)…", cfg.whisper_model)
        _whisper_model = WhisperModel(cfg.whisper_model, device="cpu", compute_type="int8")
    return _whisper_model


def _local_sync(path: str, cfg) -> str:
    model = _get_local_model(cfg)
    segments, _info = model.transcribe(path, language=cfg.voice_language or None)
    return " ".join(seg.text.strip() for seg in segments)

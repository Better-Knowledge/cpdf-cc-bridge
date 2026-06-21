# Microserviço Whisper compartilhado (faster-whisper + endpoint OpenAI-compatível)
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# uv: gerencia o venv do serviço
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml /app/
COPY app.py /app/
RUN uv sync

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

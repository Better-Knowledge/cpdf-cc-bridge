# Agente {{NAME}} — Claude Code headless + bridge tgbridge
FROM debian:bookworm-slim

# Runtime: TLS, instaladores, ferramentas do Claude Code/sessão, runtime da bridge
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep tmux unzip python3 python3-venv{{FFMPEG_PKG}} \
    && rm -rf /var/lib/apt/lists/*

# Claude Code (instalador nativo, sem Node). WORKDIR /tmp evita escanear "/".
WORKDIR /tmp
RUN curl -fsSL https://claude.ai/install.sh | bash

# bun: runtime dos plugins de Channels
RUN curl -fsSL https://bun.sh/install | bash

# uv: gerenciador Python da bridge
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV BUN_INSTALL=/root/.bun \
    PATH="/root/.bun/bin:/root/.local/bin:${PATH}" \
    USE_BUILTIN_RIPGREP=0 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    CLAUDE_CONFIG_DIR=/config

WORKDIR /home/{{NAME}}

# O compose sobrescreve com entrypoint.sh. Fallback se rodado sem compose:
CMD ["sleep", "infinity"]

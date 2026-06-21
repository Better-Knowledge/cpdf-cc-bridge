#!/usr/bin/env bash
# Entrypoint do agente {{NAME}}: sobe o claude interativo em tmux (assinatura)
# e a bridge tgbridge num loop de restart. Docker enxerga a bridge (logs/restart).
set -uo pipefail

# PATH explícito: login shell rebuilda o PATH e perde ~/.local/bin (claude, uv).
export PATH="/root/.bun/bin:/root/.local/bin:$PATH"
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/config}"

# Segredos de infra num arquivo restrito (0600) que as skills leem nas sessões
# efêmeras (cron/A2A), onde o env é limpo (anti-exfil). Subshell isola o umask.
( umask 077; {
    printf 'BRIDGE_HOOK_SECRET=%s\n' "${BRIDGE_HOOK_SECRET:-}"
    printf 'A2A_SECRET=%s\n' "${A2A_SECRET:-}"
    printf 'A2A_PEER_SECRETS=%s\n' "${A2A_PEER_SECRETS:-}"
  } > "$CLAUDE_CONFIG_DIR/bridge.secret" ) && \
  chmod 600 "$CLAUDE_CONFIG_DIR/bridge.secret" 2>/dev/null || \
  echo "[entrypoint] aviso: não consegui gravar $CLAUDE_CONFIG_DIR/bridge.secret" >&2

SESSION="${TMUX_SESSION:-{{NAME}}}"
WORKSPACE=/home/{{NAME}}
BRIDGE_DIR=/home/{{NAME}}/tgbridge

cd "$BRIDGE_DIR"

# 1) venv da bridge (idempotente; diretório é bind-mount)
echo "[entrypoint] uv sync..."
uv sync{{UV_SYNC_EXTRA}} || { echo "[entrypoint] uv sync FALHOU" >&2; }

# 2) instala os hooks no settings.json (idempotente) ANTES do claude subir
uv run tgbridge hook-install || echo "[entrypoint] hook-install falhou (segue)" >&2

# 3) sobe o claude interativo em tmux, se ainda não existir
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[entrypoint] iniciando claude em tmux (sessão $SESSION, cwd $WORKSPACE)"
  tmux new-session -d -s "$SESSION" -c "$WORKSPACE" -x 200 -y 50 "claude"
fi

# 4) bridge em loop de restart (foreground → PID principal do container)
echo "[entrypoint] iniciando tgbridge"
while true; do
  uv run tgbridge run
  echo "[entrypoint] tgbridge saiu ($?); reiniciando em 3s" >&2
  sleep 3
done

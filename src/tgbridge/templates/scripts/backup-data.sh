#!/usr/bin/env bash
# backup-data.sh — backup local dos DADOS PESSOAIS do agente (NÃO versionados no git).
# Snapshot tar.gz datado, fora do repositório. Rode 1x/dia (cron/scheduler).
set -euo pipefail
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Destino: fora do workspace (../data-backups). Override por AGENT_BACKUP_DIR.
DEST="${AGENT_BACKUP_DIR:-$WS/../data-backups}"
mkdir -p "$DEST"

# Conjunto de dados pessoais (relativos ao workspace)
PATHS=( memory MEMORY.md projects DASHBOARD.md USER.md TOOLS.md HEARTBEAT.md )

STAMP="$(TZ="${TZ:-America/Sao_Paulo}" date '+%Y-%m-%d_%H%M%S-%Z')"
OUT="$DEST/agent-data_${STAMP}.tar.gz"

EXISTING=()
for p in "${PATHS[@]}"; do [ -e "$WS/$p" ] && EXISTING+=("$p"); done
[ ${#EXISTING[@]} -gt 0 ] || { echo "nada a salvar em $WS"; exit 0; }

tar -czf "$OUT" -C "$WS" "${EXISTING[@]}"
echo "Backup criado: $OUT ($(du -h "$OUT" | cut -f1))"

# Retenção: manter os 30 snapshots mais recentes
ls -1t "$DEST"/agent-data_*.tar.gz 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "Snapshots mantidos: $(ls -1 "$DEST"/agent-data_*.tar.gz 2>/dev/null | wc -l)"

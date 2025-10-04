#!/usr/bin/env bash
set -euo pipefail
[ -f .env ] && set -a && . .env && set +a

export PYTHONPATH=src:${PYTHONPATH:-}
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8084}"
LOG_LEVEL="${LOG_LEVEL:-debug}"

# fast shutdown so restarts don't hang
export UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN="${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-2}"

echo "→ (once) uvicorn on ${HOST}:${PORT}"
exec uvicorn tobyworld_v4.api.server:app \
  --host "$HOST" \
  --port "$PORT" \
  --log-level "$LOG_LEVEL"

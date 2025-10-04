#!/usr/bin/env bash
set -euo pipefail

# Go to repo root (parent of scripts/)
cd "$(dirname "$0")/.."

# venv
if [[ -d .venv ]]; then source .venv/bin/activate; fi

# ---- Load envs robustly ----
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

# only load .env.local if RUN_PROFILE=dev
if [[ "${RUN_PROFILE:-}" == "dev" ]] && [[ -f .env.local ]]; then
  set -a; source .env.local; set +a
fi

# ---- Prometheus multiprocess dir ----
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prom_multiproc}"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
rm -f "$PROMETHEUS_MULTIPROC_DIR"/* 2>/dev/null || true

# Defaults (can be overridden by .env/.env.local)
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
WORKERS="${WORKERS:-2}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Ensure src is on path
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1  # nicer logs

# Absolute paths for safety
export WEB_DIR="${WEB_DIR:-$(pwd)/web}"
export SCROLLS_DIR="${SCROLLS_DIR:-$(pwd)/lore-scrolls}"

# Port check (Linux/macOS)
port_in_use=false
if command -v ss >/dev/null 2>&1; then
  if ss -ltn | awk '{print $4}' | grep -q ":${PORT}$"; then port_in_use=true; fi
elif command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP -sTCP:LISTEN -n -P 2>/dev/null | grep -q ":${PORT} "; then port_in_use=true; fi
fi
if $port_in_use; then
  echo "⚠️  Port ${PORT} in use; assuming server already running."
  exit 0
fi

# Banner (include Memori hint)
echo "===================================="
echo " 🪞 Mirror V4 — ${RUN_PROFILE:-prod} MODE"
echo " → Host: ${HOST}:${PORT}"
echo " → Workers: ${WORKERS}"
echo " → Web dir: ${WEB_DIR}"
echo " → Scrolls dir: ${SCROLLS_DIR}"
echo " → PROMETHEUS_MULTIPROC_DIR: ${PROMETHEUS_MULTIPROC_DIR}"
echo " → MEMORI_URL: ${MEMORI_URL:-unset}"
echo " → MEMORI_PULL_ASK: ${MEMORI_PULL_ASK:-unset}  MEMORI_PULL_LIMIT: ${MEMORI_PULL_LIMIT:-unset}"
echo "===================================="

# Dev profile: reload + 1 worker, no multiproc metrics
if [[ "${RUN_PROFILE:-}" == "dev" ]]; then
  export WORKERS=1
  # In dev, Prometheus multiproc + reload can be messy; isolate metrics dir per PID
  export PROMETHEUS_MULTIPROC_DIR="/tmp/prom_multiproc_dev_$$"
  mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
  echo "🔁 Dev reload enabled; workers forced to 1. Metrics dir: $PROMETHEUS_MULTIPROC_DIR"
  exec uvicorn --app-dir src tobyworld_v4.api.server:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --log-level "${LOG_LEVEL}" \
    --reload
fi

# Prod/default
exec uvicorn --app-dir src tobyworld_v4.api.server:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --log-level "${LOG_LEVEL}" \
  --workers "${WORKERS}"

#!/usr/bin/env bash
set -euo pipefail

# Go to repo root (parent of scripts/)
cd "$(dirname "$0")/.."

# 1) venv
if [[ -d .venv ]]; then source .venv/bin/activate; fi

# 2) env (load .env; .env.local only when RUN_PROFILE=dev)
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi
if [[ "${RUN_PROFILE:-}" == "dev" ]] && [[ -f .env.local ]]; then
  set -a; source .env.local; set +a
fi

# 3) defaults (can override in .env / .env.local / inline)
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8095}"          # default for V5
WORKERS="${WORKERS:-1}"       # single worker is fine for now
LOG_LEVEL="${LOG_LEVEL:-info}"

# 4) ensure src on path
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"

# 5) absolute paths for assets
export WEB_DIR="${WEB_DIR:-$(pwd)/web}"
export SCROLLS_DIR="${SCROLLS_DIR:-$(pwd)/lore-scrolls}"

# 6) Prometheus multiprocess dir (safe even with 1 worker)
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prom_multiproc}"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
rm -f "$PROMETHEUS_MULTIPROC_DIR"/* 2>/dev/null || true

# 7) avoid port clash (auto-kill any old uvicorn on this port)
if command -v lsof >/dev/null 2>&1; then
  pid=$(lsof -ti :${PORT} || true)
  if [[ -n "$pid" ]]; then
    echo "⚠️  Port ${PORT} is in use by PID $pid, killing..."
    kill -9 $pid || true
  fi
fi

echo "===================================="
echo " 🪞 Mirror V5 — PROD MODE"
echo " → Host: ${HOST}:${PORT}"
echo " → Workers: ${WORKERS}"
echo " → Web dir: ${WEB_DIR}"
echo " → Scrolls dir: ${SCROLLS_DIR}"
echo " → PROMETHEUS_MULTIPROC_DIR: ${PROMETHEUS_MULTIPROC_DIR}"
echo " → RUN_PROFILE: ${RUN_PROFILE:-<unset>}"
echo " → App: tobyworld_v5.api.server:app"
echo "===================================="

exec uvicorn --app-dir src tobyworld_v5.api.server:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --log-level "${LOG_LEVEL}" \
  --workers "${WORKERS}"

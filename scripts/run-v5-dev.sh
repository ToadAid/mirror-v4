#!/usr/bin/env bash
set -euo pipefail

# Go to repo root (parent of scripts/)
cd "$(dirname "$0")/.."

# 1) venv
if [[ -d .venv ]]; then source .venv/bin/activate; fi

# 2) env (always load .env; also load .env.local for dev)
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi
if [[ -f .env.local ]]; then
  set -a; source .env.local; set +a
fi

# 3) defaults (overrideable in .env/.env.local)
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8095}"          # V5 dev default
WORKERS=1                     # force single worker for reload
LOG_LEVEL="${LOG_LEVEL:-debug}"

# 4) ensure src on path
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"

# 5) absolute paths for assets
export WEB_DIR="${WEB_DIR:-$(pwd)/web}"
export SCROLLS_DIR="${SCROLLS_DIR:-$(pwd)/lore-scrolls}"

# 6) Prometheus multiprocess dir (clean on start)
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prom_multiproc}"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
rm -f "$PROMETHEUS_MULTIPROC_DIR"/* 2>/dev/null || true

echo "===================================="
echo " 🪞 Mirror V5 — DEV MODE (hot reload)"
echo " → Host: ${HOST}:${PORT}"
echo " → Web dir: ${WEB_DIR}"
echo " → Scrolls dir: ${SCROLLS_DIR}"
echo " → PROMETHEUS_MULTIPROC_DIR: ${PROMETHEUS_MULTIPROC_DIR}"
echo " → App: tobyworld_v5.api.server:app"
echo "===================================="

exec uvicorn --app-dir src tobyworld_v5.api.server:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --log-level "${LOG_LEVEL}" \
  --reload \
  --reload-dir src \
  --reload-dir web

#!/usr/bin/env bash
set -euo pipefail

# go to repo root (parent of scripts/)
cd "$(dirname "$0")/.."

# Force dev profile for this script
export RUN_PROFILE="${RUN_PROFILE:-dev}"

# 1) venv
if [[ -d .venv ]]; then source .venv/bin/activate; fi

# 2) env (load .env; .env.local always in dev)
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi
if [[ -f .env.local ]]; then
  set -a; source .env.local; set +a
fi

# 3) defaults (can override in .env / .env.local)
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8090}"            # dev default
LOG_LEVEL="${LOG_LEVEL:-debug}"

# 4) ensure src on path + unbuffered logs
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1

# 5) absolute paths for assets
export WEB_DIR="${WEB_DIR:-$(pwd)/web}"
export SCROLLS_DIR="${SCROLLS_DIR:-$(pwd)/lore-scrolls}"

# 6) Prometheus multiprocess dir (per-run to avoid reload clashes)
export PROMETHEUS_MULTIPROC_DIR="/tmp/prom_multiproc_dev_$$"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
rm -f "$PROMETHEUS_MULTIPROC_DIR"/* 2>/dev/null || true

# 7) ensure watchfiles exists for reload
python - <<'PY'
import importlib, sys
try:
    importlib.import_module("watchfiles")
except Exception:
    sys.exit(1)
PY
if [[ $? -ne 0 ]]; then
  pip install --quiet watchfiles
fi

# 8) avoid port clash (Linux/macOS)
port_in_use=false
if command -v ss >/dev/null 2>&1; then
  if ss -ltn | awk '{print $4}' | grep -q ":${PORT}$"; then port_in_use=true; fi
elif command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP -sTCP:LISTEN -n -P 2>/dev/null | grep -q ":${PORT} "; then port_in_use=true; fi
fi
if $port_in_use; then
  echo "❌ Port ${PORT} appears in use. Set PORT or stop the other process."
  exit 1
fi

echo "===================================="
echo " 🪞 Mirror V4 — DEV MODE"
echo " → Host: ${HOST}:${PORT}"
echo " → Workers: 1 (single, hot reload)"
echo " → Web dir: ${WEB_DIR}"
echo " → Scrolls dir: ${SCROLLS_DIR}"
echo " → PROMETHEUS_MULTIPROC_DIR: ${PROMETHEUS_MULTIPROC_DIR}"
echo " → RUN_PROFILE: ${RUN_PROFILE}"
echo " → MEMORI_URL: ${MEMORI_URL:-unset}  MEMORI_PULL_ASK: ${MEMORI_PULL_ASK:-unset}  MEMORI_PULL_LIMIT: ${MEMORI_PULL_LIMIT:-unset}"
echo "===================================="

# single process in dev; hot reload on src/ and web/
exec uvicorn --app-dir src tobyworld_v4.api.server:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --log-level "${LOG_LEVEL}" \
  --reload \
  --reload-dir src \
  --reload-dir web

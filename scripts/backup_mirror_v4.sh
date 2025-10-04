#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-$HOME/mirror-v4}"
DEST="${2:-$HOME/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="mirror-v4_${STAMP}"
OUT="${DEST}/${NAME}.tar.zst"

mkdir -p "$DEST"

# Load .env if present (for LEDGER_DB)
ENVFILE="${REPO}/.env"
if [[ -f "$ENVFILE" ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^\s*#' "$ENVFILE" | xargs -d '\n') || true
fi
DB="${LEDGER_DB:-${REPO}/mirror-v4.db}"

# Stage extras (DB backup + systemd unit if present)
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
if [[ -f "$DB" ]]; then
  echo "[*] Backing up DB: $DB"
  sqlite3 "$DB" ".backup '${STAGE}/mirror-v4.db'"
  sqlite3 "$DB" ".dump" > "${STAGE}/mirror-v4.dump.sql" || true
fi
if [[ -r /etc/systemd/system/mirror-v4.service ]]; then
  sudo cp -a /etc/systemd/system/mirror-v4.service "${STAGE}/mirror-v4.service" || true
fi

# Create archive (include .git; skip caches/venv/node_modules)
echo "[*] Creating $OUT"
tar --use-compress-program zstd -cf "$OUT" \
  -C "$(dirname "$REPO")" "$(basename "$REPO")" \
  --exclude='**/__pycache__' \
  --exclude='**/*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.venv' \
  --exclude='web/node_modules' \
  --transform "s|^|${NAME}/|" \
  -C "$STAGE" .

sha256sum "$OUT" | tee "${OUT}.sha256"
du -h "$OUT"
echo "[✓] Backup written to $OUT"

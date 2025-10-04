#!/usr/bin/env bash
# Watches lore-scrolls for changes (except .snippets) and triggers snippet refresh.
# Uses debounce + flock to avoid stampedes.

set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/lore-scrolls"
LOCK="/tmp/mv4-snippets.lock"
DEBOUNCE_SEC="${DEBOUNCE_SEC:-5}"

echo "[watch] Watching $DIR for changes (debounce ${DEBOUNCE_SEC}s)..."

# function: refresh safely with a lock
do_refresh() {
  (
    flock -n 9 || { echo "[watch] another refresh in progress, skipping"; exit 0; }
    echo "[watch] 🔄 change detected → rebuilding snippets..."
    "$ROOT/scripts/refresh_snippets.sh" || echo "[watch] refresh_snippets.sh failed"
  ) 9>"$LOCK"
}

# Debounce loop
last=0
refresh_pending=0

# Start inotify
# -r recursive, ignore .snippets (we only care about source scrolls)
inotifywait -m -r -e close_write,create,move,delete --format '%w%f' \
  --exclude '/\.snippets(/|$)' "$DIR" | while read -r path; do
  now=$(date +%s)
  refresh_pending=1

  # If enough time passed since last event, run immediately
  if (( now - last >= DEBOUNCE_SEC )); then
    last=$now
    do_refresh
    refresh_pending=0
  else
    # Debounced tail: wait a bit to accumulate events
    (
      sleep "$DEBOUNCE_SEC"
      if (( refresh_pending == 1 )); then
        last=$(date +%s)
        do_refresh
        refresh_pending=0
      fi
    ) &
  fi
done

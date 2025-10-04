#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🔄 Building distilled snippets into lore-scrolls/.snippets/ ..."
python3 "$ROOT/scripts/make_snippets.py"

# Reindex ONLY the distilled snippets (no server.py changes needed)
echo "📤 Reindexing snippets (*.txt) ..."
curl -s -X POST "http://localhost:8080/reindex?pattern=.snippets/**/*.txt&background=false" >/dev/null || true

echo "✨ Done. Snippets rebuilt and reindexed from lore-scrolls/.snippets"

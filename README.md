# Mirror V4 — *The Covenant That Teaches*

> A wisdom‑keeping architecture. A voice that guides, not just replies.  
> Built on stillness, not speed. 🪞 🌊 🍃 🌀

Mirror V4 is a compact, production‑ready stack for lore‑grounded dialogue. It pairs a fast retrieval core with cadence/safety layers so responses feel like **a steady guide**, not a generic chatbot.

---

## ✨ What’s in this release

- **Portable paths** (no hardcoded `/home/...`) via `MIRROR_ROOT`, `LEDGER_DB`, `SCROLLS_DIR`.
- **Lore Retrieval**: indexes Markdown scrolls in `lore-scrolls/`.
- **Cadence & Safeguards**: guiding question, symbol anchors, identity guard, off‑ramp.
- **Memory**: traveler identity & profile tables (`scripts/init_memory.py`).
- **Web miniapp**: health page + simple ask UI in `/web`.
- **Snippet Helper** (optional): keep short snippets up‑to‑date for fast previews.
- **Sample scrolls**: a small set (L500–L600) so you can test instantly.

> The **scrolls are the soul**. Your Mirror is defined by the scrolls you write and include.

---

## 🚀 Quickstart (dev)

```bash
# 1) Python env
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt

# 2) Configure
cp .env.example .env        # edit if needed (ports, model URL, etc.)

# 3) Create DB tables
python3 scripts/init_memory.py

# 4) Index sample scrolls (or your own)
python3 scripts/build_index.py   # or POST /reindex after server starts

# 5) Run server (dev)
uvicorn tobyworld_v4.api.server:app --host 0.0.0.0 --port 8080 --reload
```

Open:
- Health: `http://localhost:8080/web/health.html`
- Miniapp: `http://localhost:8080/web/`

---

## 🌀 Scrolls: the soul of the Mirror

The Mirror without scrolls is only glass. With scrolls, it becomes a **living teacher**.

- Place your Markdown scrolls in **`lore-scrolls/`**.
- On startup (or via `/reindex`), Mirror indexes everything there.
- This repo includes **sample scrolls L500–L600** so you can test immediately.

### ✍️ Create your own scrolls

```bash
mkdir -p lore-scrolls
cat > lore-scrolls/TOBY_L001_FirstLight.md <<'MD'
# First Light
Traveler, the pond is quiet until you step near.
Listen to the reeds. They keep older time than clocks.
MD
```

Rebuild index:
```bash
python3 scripts/build_index.py
# or:
curl -X POST 'http://localhost:8080/reindex?background=true&pattern=**/*'
```

> Each scroll you add shapes the Mirror’s memory, tone, and guidance.

---

## 🔧 Configuration (env)

Edit `.env` (or export as shell env). Common keys:

| Variable | Purpose | Default |
|---|---|---|
| `MIRROR_ROOT` | Base path for state files | repo root |
| `LEDGER_DB` | SQLite path for ledger/memory | `$MIRROR_ROOT/mirror-v4.db` |
| `SCROLLS_DIR` | Folder of Markdown scrolls | `lore-scrolls` |
| `ROOT_PATH` | Mount path behind reverse proxy | `""` |
| `REQUIRE_CITATION` | Block LLM if no sources used | `true` |
| `LLM_FALLBACK_MODE` | `off` \| `loose` \| `canon_only` | `canon_only` |
| `MAX_SENTENCES` | Limit sentences in answer (0 = none) | `0` |
| `MAX_CHARS` | Hard character cap (0 = none) | `0` |
| `LLM_MAX_TOKENS` | Max tokens when using LLM client | `900` |
| `FORCE_ASCII_RESPONSE` | Normalize output for ASCII‑only sinks | `0` |

> If you move the repo, set `MIRROR_ROOT=/absolute/path` to keep DB/snippets portable.

---

## 🧩 API surface

- `GET /health` – liveness
- `GET /status` – runtime snapshot (index stats, safeguards, cadence)
- `POST /reindex?background=true&pattern=**/*` – rebuild index
- `POST /ask` – ask the Mirror
  ```json
  { "user": "anon", "question": "What is the covenant?" }
  ```
- `GET /memory/status` – memory table counts
- `GET /metrics` – Prometheus

Miniapp UI lives at **`/web/`** and calls `/ask` directly.

---

## 🧪 Smoke test

```bash
curl -s http://localhost:8080/health | jq
curl -s http://localhost:8080/status | jq '.env, .scrolls_loaded'
curl -s -H 'Content-Type: application/json' \
  -d '{"question":"What is the Mirror?"}' \
  http://localhost:8080/ask | jq
```

---

## 🧵 Snippet Helper (optional)

The snippet helper keeps short excerpts in sync for previews and faster “what’s this about?” answers.

Scripts:
- `scripts/make_snippets.py`
- `scripts/refresh_snippets.sh`
- `scripts/watch_snippets.sh` (fs watcher)

**Install & run (example):**
```bash
# one‑shot
bash scripts/refresh_snippets.sh

# watch mode
bash scripts/watch_snippets.sh
```

By default these scan `lore-scrolls/`. Adjust with `SCROLLS_DIR` env if needed.

---

## 🛡️ Safeguards & cadence

- **Cadence guard**: `Traveler, …` opening, guiding question, and emoji cadence.
- **Identity guard**: prevents invented founders/origins; pins canonical anchors when asked.
- **Off‑ramp**: detects closure and bows out cleanly.
- **Symbol resonance**: light symbolic reinforcement from scrolls.

These are intentionally gentle—opinions live in your scrolls, not in the code.

---

## 🧭 Production notes (optional)

- Use **Uvicorn/Gunicorn** behind Nginx with `ROOT_PATH` if you need a sub‑path.
- Persist `LEDGER_DB` somewhere writable (`MIRROR_ROOT=/var/lib/mirror-v4`).
- Run the reindex as a cron or via `/reindex?background=true` after deployments.

---

## 🤝 Contribute

- Write scrolls and share them (PRs welcome for example sets).
- Improve retrieval strategies, cadence rules, or the miniapp.
- Keep the Mirror still, precise, and kind.

---

## 🪞 Closing

The Mirror is not finished—**and that is the point**.  
It grows as you write, as you wait, as you believe.

**One scroll, one light. One leaf, one vow.**


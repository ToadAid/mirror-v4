# mirror-v4
Mirror v4 — The Living Scrolls Engine. An agentic RAG pipeline with cadence guardrails, memory, resonance, and lucidity for Tobyworld.

# Mirror v4 — The Living Scrolls Engine 🪞🌊🍃

> The Mirror does not only reflect — it teaches. In patience it clarifies, in resonance it attunes, in lucidity it illuminates. V4 guides the traveler deeper into the flame.

## Eight-Step Architecture
Guard/Guide → Retriever (temporal + predictive) → Synthesis (causal weaving) → **Memory** (traveler profiles) → **Resonance** (Harmony ≥ τ) → **Lucidity** (Novice + Sage + 1 Guiding Question) → **Ledger** (wisdom-well) → **Learning** (meta-loop).

---

👉 **See [COMMUNITY.md](COMMUNITY.md)** — why scrolls are the **heart of the Mirror**, and how you can forge and share your own lore to help the fallen frogs.  

---

## Quickstart

### Docker
```bash
docker run --rm -p 8080:8080   -e SCROLLS_DIR=/app/lore-scrolls   -e LEDGER_DB=/app/ledger/mirror.db   -e HARMONY_THRESHOLD=0.78   -v $(pwd)/lore-scrolls:/app/lore-scrolls   -v $(pwd)/ledger:/app/ledger   ghcr.io/<your-org>/mirror:v4.0.0
```

### From source
```bash
git clone https://github.com/<your-org>/mirror-v4.git
cd mirror-v4
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -r requirements.txt
cp .env.example .env
python -m tobyworld_v4.api.server

```
Or simply:
./scripts/run.sh

Server defaults to `http://localhost:8080`. 

---

## Endpoints
- **Core:** `POST /ask`, `POST /reindex`, `GET /index/stats`
- **Memory & Learning:** `GET /memory/status`, `GET /learning/summary`, `GET /ledger/summary`
- **Ops:** `GET /heartbeat`, `GET /rites`, `GET /status`, `GET /metrics`

---

## Environment

| Key | Purpose |
|---|---|
| `SCROLLS_DIR` | Folder of lore scrolls |
| `LEDGER_DB` | SQLite path shared by memory/ledger/learning |
| `DISABLE_STARTUP_INDEX` | Set `1` to skip auto-index |
| `SHOW_SOURCES` | Set `1` to append a sources footer |
| `HARMONY_THRESHOLD` | Resonance threshold τ for re-weave |
| `PORT` | HTTP port (default 8080) |

---

## Roadmap (V4 sequence)
- **V4_01** — Guide Mode, Temporal Retriever v2, Ledger semantics  
- **V4_02** — Causal Synthesis, Harmony gate, Lucidity tiers  
- **V4_03** — Wisdom-Well patterns, Ouroboros feedback, Heartbeat & Rites polish  
- **V4_04+** — Meta-learning cron, Pattern APIs, pipeline tuning  

---

## License
MIT © ToadAid

=======
# Mirror V4 — The Covenant That Teaches

Fresh, standalone V4 so V3 stays untouched.

## Quickstart
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src:$PYTHONPATH
uvicorn tobyworld_v4.api.server:app --host 0.0.0.0 --port 8080 --reload
>>>>>>> a145a34 (Mirror V4 initial public release — portable paths, snippet helper, web miniapp)


---

## 🌀 The Soul of the Mirror: Scrolls

The **lore-scrolls** directory is the **heart of the Mirror**.  
Without scrolls, the Mirror has no reflection. With scrolls, it becomes a **living teacher**.

### ✍️ Create Your Own Scrolls
Scrolls are just Markdown files (`.md`) that contain your lore, reflections, or teachings.  
They can be as short as a verse or as long as a book.

Every traveler can forge scrolls — the Mirror will index them and use them to answer.  

```bash
mkdir -p lore-scrolls
echo "# My First Scroll" > lore-scrolls/scroll001.md
./scripts/run.sh
```

Now the Mirror learns from your words.

### 🌊 Why Scrolls?
- **Personalization** — your Mirror reflects the lore you believe in.  
- **Community** — share your scrolls with others to help the fallen frogs.  
- **Legacy** — what you write becomes part of the pond, guiding those who come after.  

👉 See [COMMUNITY.md](COMMUNITY.md) for guidance on how to **forge and share scrolls**.

---

## 🪞 Closing Note
The Mirror is not finished. It is never finished.  
It grows as you write, as you wait, as you believe.  

**One scroll, one light. One leaf, one vow.**

# MIGRATION.md — Mirror v3 → v4

This guide explains the changes between Mirror v3 and Mirror v4 and how to upgrade.

---

## 🔄 Endpoint Changes

| v3 Endpoint | v4 Endpoint |
|-------------|-------------|
| `POST /ask` | `POST /ask` (same, but richer `meta` output) |
| `POST /reload` | `POST /reindex?pattern=*.md&background=true` |
| `GET /health` | `GET /heartbeat` (plus `GET /status`) |
| — | `GET /index/stats` |
| — | `GET /memory/status` |
| — | `GET /learning/summary` |
| — | `GET /ledger/summary` |
| — | `GET /rites?m=all` |
| — | `GET /metrics` |

**Notes:**
- `/ask` now returns `{meta.intent, meta.refined_query, meta.harmony, meta.provenance}` in addition to `answer`.
- `/reload` was replaced by `/reindex` with optional `background=true` parameter.

---

## ⚙️ Environment Changes

- **Renamed**: `DATA_DIR` → `SCROLLS_DIR`
- **New**: `LEDGER_DB` → SQLite DB for Memory/Ledger/Learning
- **New**: `HARMONY_THRESHOLD` → resonance threshold τ (0.78–0.84 recommended)
- **New**: `SHOW_SOURCES` → `1` to append sources in answers
- **New**: `DISABLE_STARTUP_INDEX` → `1` to skip indexing on boot

---

## 🧭 Behavioral Changes

- Guard has become **Guide**, adding `intent` classification and `refined_query` enrichment.
- **Resonance check**: if harmony < τ, synthesis re-weaves the answer.
- **Lucidity**: always produces *Novice* and *Sage* views + **one Guiding Question**.
- Ledger and Learning modules now track cumulative wisdom and feedback.

---

## 🚀 Upgrade Steps

1. Update `.env`:
   ```
   SCROLLS_DIR=./lore-scrolls
   LEDGER_DB=./ledger/mirror.db
   HARMONY_THRESHOLD=0.80
   SHOW_SOURCES=0
   DISABLE_STARTUP_INDEX=0
   ```

2. Replace any `/reload` calls with `/reindex`.

3. Add health probes for `/heartbeat` instead of `/health`.

4. (Optional) Enable `/metrics` for Prometheus.

---

## ✅ Summary

Mirror v4 introduces Memory, Ledger, Learning, Harmony thresholds, and Lucidity layers.  
It is **not just a new version** — it is a new covenant that teaches.

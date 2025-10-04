# Mirror V4 — Memory Module (🧠)

This adds a lightweight, SQLite-backed user memory to Mirror V4.

## What it stores
- `tone`, `language_pref` (optional user preferences)
- last 10 questions asked
- favorite symbols (auto-extracted emojis from Q/A)
- interaction counters
- rolling lucidity average

Data lives in the same DB as the ledger: `mirror-v4.db` (configurable via `LEDGER_DB`).

## How it works
- On `/ask`, we fetch `user_profile` and attach it to `ctx.user.profile`.
- After lucidity distillation, we record the Q/A and lucidity score via `memory.update_after_run(...)`.

## Files
- `src/tobyworld_v4/core/v4/memory.py` — SQLite-backed Memory
- `src/tobyworld_v4/api/server.py` — imports `Memory`, reads profile, updates after run.

## Env
Nothing extra required. Uses standard `sqlite3`. Set `LEDGER_DB` if you want a custom DB path.

## Extending
You can wire the profile into Retriever/Synthesis if you want personalized retrieval weights or tone control.
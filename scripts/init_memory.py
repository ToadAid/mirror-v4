#!/usr/bin/env python3
import os, sqlite3
from pathlib import Path

# Use env var if set, else default to project root
default_root = Path(os.getenv("MIRROR_ROOT", Path(__file__).resolve().parents[1]))
DB_PATH = os.getenv("LEDGER_DB", str(default_root / "mirror-v4.db"))

print(f"Using DB: {DB_PATH}")

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS travelers (
  id TEXT PRIMARY KEY,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS identities (
  id TEXT PRIMARY KEY,
  traveler_id TEXT NOT NULL REFERENCES travelers(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,         -- 'x' | 'telegram' | 'wallet'
  external_id TEXT NOT NULL,      -- stable id (numeric tg id, wallet addr, or handle)
  handle TEXT,
  verified INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, external_id)
);

CREATE TABLE IF NOT EXISTS profiles (
  traveler_id TEXT PRIMARY KEY REFERENCES travelers(id) ON DELETE CASCADE,
  tone TEXT DEFAULT '',
  language_pref TEXT DEFAULT '',
  interactions INTEGER DEFAULT 0,
  lucidity_avg REAL DEFAULT 0.0,
  last_q TEXT DEFAULT '',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

db.commit()
print("✅ Memory tables ready in", DB_PATH)

#!/usr/bin/env python3
import os, sqlite3

DB = os.getenv("LEDGER_DB", "mirror-v4.db")
print("Using DB:", DB)
db = sqlite3.connect(DB)
cur = db.cursor()

cur.executescript("""
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS travelers (
  id TEXT PRIMARY KEY,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS identities (
  id TEXT PRIMARY KEY,
  traveler_id TEXT NOT NULL REFERENCES travelers(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,         -- 'x' | 'telegram' | 'wallet'
  external_id TEXT NOT NULL,      -- tg user id, x handle, or wallet addr
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
db.close()
print("✅ identities/profiles/travelers ready.")

import os, sqlite3
from uuid import uuid4
from typing import Optional, Tuple, Dict

DB_PATH = os.getenv("LEDGER_DB", os.path.join(os.getenv("MIRROR_ROOT", "."), "mirror-v4.db"))

def _db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def parse_user_token(s: str) -> Dict[str, Optional[str]]:
    """
    Accepts:
      - "tg:id=123456" (preferred)
      - "tg:@username" or "tg:username"
      - "x:@handle" or "x:handle"
      - "w:0xabc.."
      - fallback: "anon:...", "anon"
    Returns dict with provider, external_id, handle?
    """
    s = (s or "").strip()
    if s.startswith("tg:id="):
        return {"provider": "telegram", "external_id": s.split("=",1)[1], "handle": None}
    if s.startswith("tg:@") or s.startswith("tg:"):
        handle = s.split(":",1)[1]
        if not handle.startswith("@"): handle = "@"+handle
        return {"provider": "telegram", "external_id": handle.lower(), "handle": handle}
    if s.startswith("x:@") or s.startswith("x:"):
        handle = s.split(":",1)[1]
        if not handle.startswith("@"): handle = "@"+handle
        return {"provider": "x", "external_id": handle.lower(), "handle": handle}
    if s.startswith("w:"):
        return {"provider": "wallet", "external_id": s[2:].lower(), "handle": None}
    # default anon
    ident = s or "anon"
    return {"provider": "anon", "external_id": ident, "handle": None}

def ensure_tables():
    db = _db(); cur = db.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS travelers (
      id TEXT PRIMARY KEY,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS identities (
      id TEXT PRIMARY KEY,
      traveler_id TEXT NOT NULL REFERENCES travelers(id) ON DELETE CASCADE,
      provider TEXT NOT NULL,
      external_id TEXT NOT NULL,
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
    db.commit(); db.close()

def resolve_traveler(token: Dict[str, Optional[str]]) -> Tuple[str, Dict]:
    """
    Find or create (traveler, identity). Returns (traveler_id, identity_row_dict).
    """
    db = _db(); cur = db.cursor()
    prov, ext = token["provider"], token["external_id"]
    row = cur.execute("SELECT * FROM identities WHERE provider=? AND external_id=?", (prov, ext)).fetchone()
    if row:
        db.close()
        return row["traveler_id"], dict(row)

    # create new traveler + identity + ensure profile
    tid = uuid4().hex
    cur.execute("INSERT INTO travelers(id) VALUES (?)", (tid,))
    cur.execute("INSERT INTO identities(id, traveler_id, provider, external_id, handle, verified) VALUES (?,?,?,?,?,0)",
                (uuid4().hex, tid, prov, ext, token.get("handle")))
    cur.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (tid,))
    db.commit(); db.close()
    return tid, {"traveler_id": tid, "provider": prov, "external_id": ext, "handle": token.get("handle"), "verified": 0}

def merge_travelers(dst_tid: str, src_tid: str) -> None:
    """
    Move all identities from src -> dst, combine profiles, remove src traveler.
    """
    if dst_tid == src_tid:  # nothing to do
        return
    db = _db(); cur = db.cursor()
    # move identities
    cur.execute("UPDATE identities SET traveler_id=? WHERE traveler_id=?", (dst_tid, src_tid))
    # ensure profiles exist
    cur.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (dst_tid,))
    cur.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (src_tid,))
    # fetch for merge
    p_dst = cur.execute("SELECT interactions, lucidity_avg, last_q FROM profiles WHERE traveler_id=?", (dst_tid,)).fetchone()
    p_src = cur.execute("SELECT interactions, lucidity_avg FROM profiles WHERE traveler_id=?", (src_tid,)).fetchone()
    n1, a1 = (p_dst["interactions"] or 0), (p_dst["lucidity_avg"] or 0.0)
    n2, a2 = (p_src["interactions"] or 0), (p_src["lucidity_avg"] or 0.0)
    n = n1 + n2
    new_avg = (a1 * n1 + a2 * n2) / n if n > 0 else 0.0
    new_last_q = p_dst["last_q"]  # keep dst's last_q
    cur.execute("UPDATE profiles SET interactions=?, lucidity_avg=?, last_q=?, updated_at=CURRENT_TIMESTAMP WHERE traveler_id=?",
                (n, new_avg, new_last_q, dst_tid))
    # remove src profile + traveler
    cur.execute("DELETE FROM profiles WHERE traveler_id=?", (src_tid,))
    cur.execute("DELETE FROM travelers WHERE id=?", (src_tid,))
    db.commit(); db.close()

def forget_traveler(traveler_id: str, hard: bool=False) -> None:
    db = _db(); cur = db.cursor()
    if hard:
        cur.execute("DELETE FROM travelers WHERE id=?", (traveler_id,))
        # ON DELETE CASCADE will remove identities + profile
    else:
        # soft reset: keep traveler + identities, zero profile stats
        cur.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (traveler_id,))
        cur.execute("""UPDATE profiles SET interactions=0, lucidity_avg=0.0, last_q='',
                       updated_at=CURRENT_TIMESTAMP WHERE traveler_id=?""", (traveler_id,))
    db.commit(); db.close()

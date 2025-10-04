from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import os, time, json, sqlite3, threading, re, uuid
import unicodedata  # NEW: for ASCII-safe normalization

# Reuse the same DB as ledger/learning
_DB_PATH = os.getenv("LEDGER_DB", "mirror-v4.db")

# Basic emoji / symbol capture (lightweight)
_EMOJI = re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]')

# ASCII-safe punctuation map (match server.py)
_PUNCT_MAP = {
    0x2013: '-',  # – en dash
    0x2014: '-',  # — em dash
    0x2018: "'",  # ‘
    0x2019: "'",  # ’
    0x201C: '"',  # “
    0x201D: '"',  # ”
    0x00A0: ' ',  # nbsp
}

def _ascii_clean(s: str) -> str:
    """
    Normalize to NFKC, replace smart punctuation, then drop anything non-ASCII.
    Keeps downstream ASCII-only consumers happy without touching emoji storage elsewhere.
    """
    try:
        s = unicodedata.normalize("NFKC", s or "")
        s = s.translate(_PUNCT_MAP)
        return s.encode("ascii", "ignore").decode("ascii")
    except Exception:
        return (s or "").encode("ascii", "ignore").decode("ascii")

# --- Legacy lightweight table (kept for UX niceties like last_questions/emojis) ---
_USER_MEMORY_SQL = """
CREATE TABLE IF NOT EXISTS user_memory (
    user_id          TEXT PRIMARY KEY,
    tone             TEXT,
    language_pref    TEXT,
    last_questions   TEXT,
    favorite_symbols TEXT,
    last_seen        REAL,
    interactions     INTEGER DEFAULT 0,
    lucidity_sum     REAL DEFAULT 0.0,
    lucidity_avg     REAL DEFAULT 0.0
);
"""

# --- Identity/Profile tables (new canonical memory) ---
_TRAVELERS_SQL = """
CREATE TABLE IF NOT EXISTS travelers (
  id TEXT PRIMARY KEY,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_IDENTITIES_SQL = """
CREATE TABLE IF NOT EXISTS identities (
  id TEXT PRIMARY KEY,
  traveler_id TEXT NOT NULL REFERENCES travelers(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,         -- 'x' | 'telegram' | 'wallet'
  external_id TEXT NOT NULL,      -- handle, numeric tg id, or wallet addr
  handle TEXT,
  verified INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, external_id)
);
"""

_PROFILES_SQL = """
CREATE TABLE IF NOT EXISTS profiles (
  traveler_id TEXT PRIMARY KEY REFERENCES travelers(id) ON DELETE CASCADE,
  tone TEXT DEFAULT '',
  language_pref TEXT DEFAULT '',
  interactions INTEGER DEFAULT 0,
  lucidity_avg REAL DEFAULT 0.0,
  last_q TEXT DEFAULT '',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

class _SQLiteMemory:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._ensure()

    # ----------- low-level helpers -----------
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path)
        con.row_factory = sqlite3.Row
        return con

    def _ensure(self):
        with self._connect() as conn:
            conn.execute(_USER_MEMORY_SQL)
            conn.execute(_TRAVELERS_SQL)
            conn.execute(_IDENTITIES_SQL)
            conn.execute(_PROFILES_SQL)
            conn.commit()

    # ----------- identity resolution -----------
    def resolve_user(self, raw: str) -> Tuple[str, dict]:
        """
        Accepts:
          - UUID traveler_id
          - 'x:handle'   (X/Twitter)
          - 'tg:123456'  (Telegram numeric id)
          - anything else: treated as a direct traveler id (created if missing)

        Returns (traveler_id, profile_dict)
        Creates traveler/identity/profile rows if missing.
        """
        raw = (raw or "").strip()
        # UUID short-circuit
        try:
            _ = uuid.UUID(raw)
            prof = self._get_profile(raw) or {}
            if not prof:
                # ensure skeleton profile exists
                with self._connect() as con:
                    con.execute("INSERT OR IGNORE INTO travelers(id) VALUES (?)", (raw,))
                    con.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (raw,))
                    con.commit()
                prof = self._get_profile(raw) or {}
            return raw, prof
        except Exception:
            pass

        m = re.match(r"^(x|tg):\s*(.+)$", raw, flags=re.I)
        if not m:
            # treat as traveler id literal; ensure rows exist
            tid = raw if raw else str(uuid.uuid4())
            with self._connect() as con:
                con.execute("INSERT OR IGNORE INTO travelers(id) VALUES (?)", (tid,))
                con.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (tid,))
                con.commit()
            return tid, (self._get_profile(tid) or {})

        provider, ext = m.group(1).lower(), m.group(2).strip()
        provider = "x" if provider == "x" else "telegram"
        external_id = ext.lstrip("@")

        with self._connect() as con:
            cur = con.execute(
                "SELECT traveler_id FROM identities WHERE provider=? AND external_id=?",
                (provider, external_id),
            )
            row = cur.fetchone()
            if row:
                tid = row["traveler_id"]
                return tid, (self._get_profile(tid) or {})

            # create traveler + identity + profile
            tid = str(uuid.uuid4())
            con.execute("INSERT OR IGNORE INTO travelers(id) VALUES (?)", (tid,))
            con.execute(
                "INSERT OR IGNORE INTO identities(id, traveler_id, provider, external_id, handle, verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (str(uuid.uuid4()), tid, provider, external_id, external_id),
            )
            con.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (tid,))
            con.commit()
            return tid, (self._get_profile(tid) or {})

    # ----------- profiles (canonical) -----------
    def _get_profile(self, traveler_id: str) -> dict:
        if not traveler_id:
            return {}
        with self._connect() as con:
            cur = con.execute(
                "SELECT tone, language_pref, interactions, lucidity_avg, last_q, updated_at "
                "FROM profiles WHERE traveler_id=?",
                (traveler_id,),
            )
            r = cur.fetchone()
            if not r:
                return {}
            return {
                "tone": r["tone"] or "",
                "language_pref": r["language_pref"] or "",
                "interactions": int(r["interactions"] or 0),
                "lucidity_avg": float(r["lucidity_avg"] or 0.0),
                "last_q": r["last_q"] or "",
                "updated_at": r["updated_at"],
            }

    def _set_profile_prefs(self, traveler_id: str, tone: Optional[str], language_pref: Optional[str]) -> None:
        if not traveler_id:
            return
        with self._connect() as con:
            # ensure rows
            con.execute("INSERT OR IGNORE INTO travelers(id) VALUES (?)", (traveler_id,))
            con.execute("INSERT OR IGNORE INTO profiles(traveler_id) VALUES (?)", (traveler_id,))
            # update prefs
            if tone is not None and language_pref is not None:
                con.execute(
                    "UPDATE profiles SET tone=?, language_pref=?, updated_at=CURRENT_TIMESTAMP WHERE traveler_id=?",
                    (tone, language_pref, traveler_id),
                )
            elif tone is not None:
                con.execute(
                    "UPDATE profiles SET tone=?, updated_at=CURRENT_TIMESTAMP WHERE traveler_id=?",
                    (tone, traveler_id),
                )
            elif language_pref is not None:
                con.execute(
                    "UPDATE profiles SET language_pref=?, updated_at=CURRENT_TIMESTAMP WHERE traveler_id=?",
                    (language_pref, traveler_id),
                )
            con.commit()

    def _bump_learning(self, traveler_id: str, last_q: str, lucidity: float) -> None:
        """Update interactions, lucidity_avg, last_q on profiles."""
        with self._connect() as con:
            # fetch existing for rolling average
            cur = con.execute(
                "SELECT interactions, lucidity_avg FROM profiles WHERE traveler_id=?",
                (traveler_id,),
            )
            r = cur.fetchone()
            interactions = int(r["interactions"] or 0) + 1 if r else 1
            prev_avg = float(r["lucidity_avg"] or 0.0) if r else 0.0
            # simple incremental average
            new_avg = ((prev_avg * (interactions - 1)) + float(lucidity)) / max(interactions, 1)
            con.execute(
                "UPDATE profiles SET interactions=?, lucidity_avg=?, last_q=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE traveler_id=?",
                (interactions, new_avg, _ascii_clean(last_q)[:500], traveler_id),  # ASCII-safe last_q
            )
            con.commit()

    # ----------- legacy user_memory niceties -----------
    def _get_user_mem_row(self, user_id: str) -> Optional[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT user_id,tone,language_pref,last_questions,favorite_symbols,last_seen,interactions,lucidity_sum,lucidity_avg "
                "FROM user_memory WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "user_id": row["user_id"],
                "tone": row["tone"] or "",
                "language_pref": row["language_pref"] or "",
                "last_questions": json.loads(row["last_questions"] or "[]"),
                "favorite_symbols": json.loads(row["favorite_symbols"] or "[]"),
                "last_seen": float(row["last_seen"] or 0.0),
                "interactions": int(row["interactions"] or 0),
                "lucidity_sum": float(row["lucidity_sum"] or 0.0),
                "lucidity_avg": float(row["lucidity_avg"] or 0.0),
            }

    def _user_mem_get_or_fresh(self, user_id: str) -> dict:
        return self._get_user_mem_row(user_id) or {
            "user_id": user_id, "tone":"", "language_pref":"", "last_questions":[],
            "favorite_symbols":[], "last_seen":0.0, "interactions":0,
            "lucidity_sum":0.0, "lucidity_avg":0.0
        }

    def _user_mem_set_prefs(self, user_id: str, tone: Optional[str], language_pref: Optional[str]) -> None:
        with self._connect() as conn:
            row = self._get_user_mem_row(user_id)
            if not row:
                conn.execute(
                    "INSERT INTO user_memory (user_id,tone,language_pref,last_questions,favorite_symbols,last_seen,interactions,lucidity_sum,lucidity_avg) "
                    "VALUES (?,?,?,?,?,?,0,0.0,0.0)",
                    (user_id, tone or "", language_pref or "", "[]", "[]", time.time()),
                )
            else:
                tone_v = tone if tone is not None else row["tone"]
                lang_v = language_pref if language_pref is not None else row["language_pref"]
                conn.execute(
                    "UPDATE user_memory SET tone=?, language_pref=?, last_seen=? WHERE user_id=?",
                    (tone_v, lang_v, time.time(), user_id),
                )
            conn.commit()

    def _user_mem_update_after_run(self, user_id: str, question: str, answer: str, lucidity: float) -> None:
        question = (question or "").strip()
        answer = (answer or "").strip()
        syms = list(set(_EMOJI.findall(question + " " + answer)))[:16]

        with self._connect() as conn:
            row = self._get_user_mem_row(user_id)
            if not row:
                last_qs = [question] if question else []
                fav = syms
                interactions = 1
                luc_sum = float(lucidity)
                luc_avg = luc_sum / interactions
                conn.execute(
                    "INSERT INTO user_memory (user_id,tone,language_pref,last_questions,favorite_symbols,last_seen,interactions,lucidity_sum,lucidity_avg) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (user_id, "", "", json.dumps(last_qs), json.dumps(fav), time.time(), interactions, luc_sum, luc_avg)
                )
            else:
                last_qs = (row["last_questions"] + ([question] if question else []))[-10:]
                fav = list({*row["favorite_symbols"], *syms})[:24]
                interactions = row["interactions"] + 1
                luc_sum = row["lucidity_sum"] + float(lucidity)
                luc_avg = (luc_sum / interactions) if interactions > 0 else 0.0
                conn.execute(
                    "UPDATE user_memory SET last_questions=?, favorite_symbols=?, last_seen=?, interactions=?, lucidity_sum=?, lucidity_avg=? "
                    "WHERE user_id=?",
                    (json.dumps(last_qs), json.dumps(fav), time.time(), interactions, luc_sum, luc_avg, user_id)
                )
            conn.commit()

class Memory:
    """
    Public wrapper used by the server.

    - resolve_user(raw_id) → (traveler_id, profile_dict)
    - get_profile(traveler_id) → dict
    - set_preferences(traveler_id, tone=..., language_pref=...)
    - update_after_run(traveler_id, question, answer, lucidity)
        * updates both canonical profiles and legacy user_memory niceties
    """
    def __init__(self, config=None):
        self.backend = _SQLiteMemory(_DB_PATH)

    # --- identity / profile ---
    def resolve_user(self, raw: str) -> Tuple[str, dict]:
        return self.backend.resolve_user(raw)

    def get_profile(self, traveler_id: str) -> dict:
        return self.backend._get_profile(traveler_id)

    def set_preferences(self, traveler_id: str, tone: Optional[str]=None, language_pref: Optional[str]=None) -> None:
        # update both canonical profile and legacy user_memory (same id key)
        self.backend._set_profile_prefs(traveler_id, tone, language_pref)
        self.backend._user_mem_set_prefs(traveler_id, tone, language_pref)

    def update_after_run(self, traveler_id: str, question: str, answer: str, lucidity: float=0.0) -> None:
        # canonical rolling stats
        self.backend._bump_learning(traveler_id, last_q=question, lucidity=lucidity)
        # keep legacy convenience store in sync
        self.backend._user_mem_update_after_run(traveler_id, question, answer, lucidity)

    # Back-compat: old callsites may still use this name
    def get(self, traveler_id: str) -> dict:
        return self.get_profile(traveler_id)

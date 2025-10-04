from __future__ import annotations
from typing import Dict, Any, List, Optional
import os, time, json, sqlite3, threading, re
from .config import config

_DB_PATH = os.getenv("LEDGER_DB", "mirror-v4.db")  # reuse ledger DB

_WORD = re.compile(r"[a-z0-9][a-z0-9\-']*", re.I)
STOP = set("""
a an the and or but if then else of for to in on at with by from about into over
after before between within is are was were be being been do does did doing why how
what when where who whom which that this these those often ever never always it its
their his her your my our as i you we they them me us
""".split())

def _tokens(s: str) -> List[str]:
    return [t.lower() for t in _WORD.findall(s or "") if t.lower() not in STOP]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS learnings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    run_id          INTEGER,
    user_id         TEXT,
    intent          TEXT,
    harmony         REAL,
    answer_len      INTEGER,
    retrieval_count INTEGER,
    tags_json       TEXT,
    memo_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_learnings_ts ON learnings(ts DESC);
CREATE INDEX IF NOT EXISTS idx_learnings_user ON learnings(user_id);
"""

class _SQLiteLearning:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def commit(self, run_ctx: Dict[str, Any], run_id: Optional[int] = None) -> int:
        ts = float(time.time())
        user_id = str(((run_ctx.get("user") or {}).get("id", "")))[:200]
        intent = str(run_ctx.get("intent") or "")[:100]
        harmony = float(run_ctx.get("harmony") or 0.0)

        final = run_ctx.get("final") or {}
        answer = str(final.get("sage") or final.get("novice") or "")
        answer_len = len(answer)

        retrieval = run_ctx.get("retrieval") or []
        retrieval_count = int(len(retrieval))

        refined = run_ctx.get("refined_query") or ""
        q_tokens = _tokens(refined)[:12]

        # light heuristics → tags
        tags: List[str] = []
        if harmony < 0.6: tags.append("low_harmony")
        if answer_len < 160: tags.append("short_answer")
        if retrieval_count == 0: tags.append("no_retrieval")
        if any(k in refined.lower() for k in ("compare", " vs ")): tags.append("compare")
        if intent in ("guide", "troubleshoot"): tags.append(intent)

        memo = {
            "q_tokens": q_tokens,
            "guiding_question": (final.get("guiding_question") or ""),
            "sources": (final.get("sources") or []),
        }

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO learnings (ts, run_id, user_id, intent, harmony, answer_len,
                                       retrieval_count, tags_json, memo_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, run_id, user_id, intent, harmony, answer_len,
                 retrieval_count, json.dumps(tags, ensure_ascii=False), json.dumps(memo, ensure_ascii=False)),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def self_refine(self, limit: int = 50) -> Dict[str, Any]:
        """
        Quick snapshot: counts by tag and recent harmony/answer stats.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT tags_json, harmony, answer_len FROM learnings ORDER BY ts DESC LIMIT ?",
                (limit,)
            )
            rows = cur.fetchall()
        tag_counts: Dict[str,int] = {}
        harmonies: List[float] = []
        lengths: List[int] = []
        for tj, h, L in rows:
            try:
                for t in json.loads(tj or "[]"):
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            except Exception:
                pass
            try:
                harmonies.append(float(h or 0.0))
            except Exception:
                pass
            try:
                lengths.append(int(L or 0))
            except Exception:
                pass

        def _avg(xs): return (sum(xs) / len(xs)) if xs else 0.0
        return {
            "recent": len(rows),
            "avg_harmony": round(_avg(harmonies), 3),
            "avg_answer_len": int(_avg(lengths)) if lengths else 0,
            "top_tags": sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:8],
            "note": "Use tags to inform retrieval depth/series or synthesis cadence.",
        }

class _MemoryLearning:
    def __init__(self):
        self._rows: List[Dict[str, Any]] = []
        self._id = 0
        self._lock = threading.Lock()

    def close(self): pass

    def commit(self, run_ctx: Dict[str, Any], run_id: Optional[int] = None) -> int:
        with self._lock:
            self._id += 1
            # compute same signals as sqlite path (minimal)
            final = run_ctx.get("final") or {}
            answer = str(final.get("sage") or final.get("novice") or "")
            record = {
                "id": self._id,
                "ts": time.time(),
                "run_id": run_id,
                "user_id": (run_ctx.get("user") or {}).get("id"),
                "intent": run_ctx.get("intent"),
                "harmony": run_ctx.get("harmony"),
                "answer_len": len(answer),
                "retrieval_count": len(run_ctx.get("retrieval") or []),
            }
            self._rows.append(record)
            return self._id

    def self_refine(self, limit: int = 50) -> Dict[str, Any]:
        with self._lock:
            rows = list(reversed(self._rows[-limit:]))
        if not rows:
            return {"recent": 0, "avg_harmony": 0.0, "avg_answer_len": 0, "top_tags": []}
        avg_h = sum((r.get("harmony") or 0.0) for r in rows) / len(rows)
        avg_L = sum((r.get("answer_len") or 0) for r in rows) / len(rows)
        return {
            "recent": len(rows),
            "avg_harmony": round(avg_h, 3),
            "avg_answer_len": int(avg_L),
            "top_tags": [],
        }

class Learning:
    """
    Learning wrapper: uses SQLite if available, else in-memory.
    """
    def __init__(self, cfg=config):
        self.cfg = cfg
        try:
            self._impl = _SQLiteLearning(_DB_PATH)
            self.backend = "sqlite"
        except Exception:
            self._impl = _MemoryLearning()
            self.backend = "memory"

    def commit(self, run_ctx: Dict[str, Any], run_id: Optional[int] = None) -> int:
        return self._impl.commit(run_ctx, run_id)

    def self_refine(self, limit: int = 50) -> Dict[str, Any]:
        return self._impl.self_refine(limit=limit)

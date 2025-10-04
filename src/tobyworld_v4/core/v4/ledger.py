from __future__ import annotations
from typing import Dict, Any, List, Optional
import os, time, json, sqlite3, threading
from .config import config

# LEDGER_DB can be set to an absolute path or a filename under the CWD.
# Default: mirror-v4.db in the project root.
_DB_PATH = os.getenv("LEDGER_DB", "mirror-v4.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    user_id         TEXT,
    intent          TEXT,
    refined_query   TEXT,
    harmony         REAL,
    answer          TEXT,
    retrieval_count INTEGER,
    final_json      TEXT,
    ctx_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_text ON runs(answer);
"""

class _SQLiteLedger:
    def __init__(self, db_path: str):
        # check_same_thread=False so FastAPI workers can share; guard with a lock.
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

    def log(self, run_ctx: Dict[str, Any]) -> int:
        """
        Store a single run. Returns row id.
        """
        ts = float(time.time())
        user_id = ""
        try:
            u = run_ctx.get("user") or {}
            if isinstance(u, dict):
                user_id = str(u.get("id", ""))[:200]
            else:
                user_id = str(u)[:200]
        except Exception:
            user_id = ""

        intent = str(run_ctx.get("intent") or "")[:100]
        refined_query = str(run_ctx.get("refined_query") or "")[:2000]
        harmony = float(run_ctx.get("harmony") or 0.0)

        final = run_ctx.get("final") or {}
        # keep answer reasonably bounded to avoid bloating the DB
        answer = str(final.get("sage") or final.get("novice") or "")[:4000]

        retrieval = run_ctx.get("retrieval") or []
        retrieval_count = int(len(retrieval))

        final_json = json.dumps(final, ensure_ascii=False)
        ctx_json = json.dumps(run_ctx, ensure_ascii=False)

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO runs (ts, user_id, intent, refined_query, harmony, answer,
                                  retrieval_count, final_json, ctx_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, user_id, intent, refined_query, harmony, answer,
                 retrieval_count, final_json, ctx_json),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def query_semantic(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Very light LIKE-based search over answer/refined_query.
        """
        q = (q or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, ts, user_id, intent, harmony,
                       substr(answer, 1, 240) AS snippet
                FROM runs
                WHERE answer LIKE ? OR refined_query LIKE ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (like, like, limit),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0],
                "ts": r[1],
                "user_id": r[2],
                "intent": r[3],
                "harmony": r[4],
                "snippet": r[5],
            })
        return out

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(*), AVG(harmony), MAX(ts) FROM runs")
            cnt, avg_h, max_ts = cur.fetchone()
        return {
            "count": int(cnt or 0),
            "harmony_avg": float(avg_h or 0.0),
            "last_ts": float(max_ts or 0.0),
            "db_path": self.db_path,
        }

class _MemoryLedger:
    """
    Fallback ledger if sqlite is unavailable (keeps data in RAM).
    """
    def __init__(self):
        self._rows: List[Dict[str, Any]] = []
        self._id = 0
        self._lock = threading.Lock()

    def close(self):
        pass

    def log(self, run_ctx: Dict[str, Any]) -> int:
        with self._lock:
            self._id += 1
            self._rows.append({"id": self._id, "ctx": run_ctx, "ts": time.time()})
            return self._id

    def query_semantic(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        q = (q or "").lower()
        if not q:
            return []
        out = []
        with self._lock:
            for r in reversed(self._rows):
                ctx = r.get("ctx") or {}
                text = json.dumps(ctx, ensure_ascii=False).lower()
                if q in text:
                    out.append({
                        "id": r["id"],
                        "ts": r["ts"],
                        "user_id": (ctx.get("user") or {}).get("id"),
                        "intent": ctx.get("intent"),
                        "harmony": ctx.get("harmony"),
                        "snippet": (ctx.get("final") or {}).get("sage","")[:240],
                    })
                    if len(out) >= limit:
                        break
        return out

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            cnt = len(self._rows)
            if cnt == 0:
                return {"count": 0, "harmony_avg": 0.0, "last_ts": 0.0, "db_path": ":memory:"}
            avg = sum((r.get("ctx") or {}).get("harmony") or 0.0 for r in self._rows) / max(cnt, 1)
            last_ts = max(r["ts"] for r in self._rows)
            return {"count": cnt, "harmony_avg": float(avg), "last_ts": float(last_ts), "db_path": ":memory:"}

class Ledger:
    """
    Public wrapper. Uses SQLite if possible; otherwise falls back to in-memory.
    """
    def __init__(self, cfg=config):
        self.cfg = cfg
        try:
            self._impl = _SQLiteLedger(_DB_PATH)
            self.backend = "sqlite"
        except Exception as e:
            # Fallback
            self._impl = _MemoryLedger()
            self.backend = "memory"

    def log(self, run_ctx: Dict[str, Any]) -> int:
        return self._impl.log(run_ctx)

    def query_semantic(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self._impl.query_semantic(q, limit=limit)

    def summary(self) -> Dict[str, Any]:
        base = self._impl.summary()
        base["backend"] = self.backend
        return base

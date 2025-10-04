# src/tobyworld_v4/core/v4/retriever.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Iterable, Optional, Tuple
from pathlib import Path
import os, math, re, time, sqlite3, threading, json
import logging

from .config import config

# ──────────────────────────────────────────────────────────────────────────────
# SQLite FTS5 retriever with hint-aware scoring.
# - Uses on-disk DB so index persists across restarts.
# - If FTS5 is unavailable, falls back to in-memory lexical retrieval.
# - Public API (exported at bottom):
#     indexing(), index_stats(), set_index(), load_index_from_folder(), close_db(), class Retriever
# ──────────────────────────────────────────────────────────────────────────────

log = logging.getLogger("retriever")

_FTS_DB_PATH = os.getenv("RETRIEVER_DB", "mirror-v4-fts.db")
_LOCK = threading.RLock()

# indexer busy flag (for /reindex status & overlap prevention)
_INDEXING = False
def indexing() -> bool:
    return _INDEXING

# last index stats (exposed via index_stats())
_LAST_INDEX_STATS: Dict[str, Any] = {
    "added": 0, "skipped": 0, "failed": 0, "considered": 0, "duration_sec": 0.0,
    "root": None, "pattern": None, "fts": None,
}

# --- Env-controlled knobs (NEW) ---
TOPK_RAW      = int(os.getenv("RETRIEVER_TOPK_RAW", "120"))      # wide gather before filtering
TOPK_FINAL    = int(os.getenv("RETRIEVER_TOPK_FINAL", "48"))      # pass to synthesis
TOPK_PER_ARC  = int(os.getenv("RETRIEVER_TOPK_PER_ARC", "0"))     # 0 = off (unused here, for future)
MIN_SCORE     = float(os.getenv("RETRIEVER_MIN_SCORE", "0.20"))   # permissive gate (on our normalized score)
BM25_W        = float(os.getenv("RETRIEVER_BM25_WEIGHT", "0.55")) # reserved for hybrid
EMB_W         = float(os.getenv("RETRIEVER_EMB_WEIGHT", "0.45"))  # reserved for hybrid

_WORD_RX = re.compile(r"[a-z0-9][a-z0-9\-']*", re.I)
_STOP = set("""
a an the and or but if then else of for to in on at with by from about into over
after before between within is are was were be being been do does did doing why how
what when where who whom which that this these those often ever never always it its
their his her your my our as i you we they them me us
""".split())

def _tokens(s: str) -> List[str]:
    return [t.lower() for t in _WORD_RX.findall(s or "") if t.lower() not in _STOP]

def _uniq(seq: Iterable[str]) -> List[str]:
    out, seen = [], set()
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _now_ts() -> float:
    try: return time.time()
    except Exception: return 0.0

def _series_from_filename(name: str) -> str:
    # infer series from prefix like TOBY_L001.md -> "TOBY_L"
    m = re.match(r"^(TOBY_[A-Z]+)", name)
    return m.group(1).upper() if m else ""

def _first_heading(text: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if not s: continue
        if s.startswith("#"):
            return re.sub(r"^#+\s*", "", s)
        return s
    return ""

def _chunk_text(text: str, max_chars: int = 800) -> Tuple[str, Tuple[int,int]]:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text, (0, len(text))
    return text[:max_chars], (0, max_chars)

# ── FTS layer ─────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY,
  title TEXT,
  series TEXT,
  ts REAL,
  epoch TEXT,
  symbols TEXT,   -- JSON array
  text TEXT
);

-- contentless FTS so we can recompute text as needed
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
  id, title, series, text,
  tokenize = 'porter'
);

-- small helper to speed up common filters
CREATE INDEX IF NOT EXISTS idx_docs_series ON docs(series);
CREATE INDEX IF NOT EXISTS idx_docs_ts ON docs(ts);
"""

def _fts_supported() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(a);")
        con.close()
        return True
    except Exception:
        return False

_SUPPORTS_FTS = _fts_supported()
_DB: Optional[sqlite3.Connection] = None

def _db() -> Optional[sqlite3.Connection]:
    global _DB
    if not _SUPPORTS_FTS:
        return None
    if _DB is None:
        _DB = sqlite3.connect(_FTS_DB_PATH, check_same_thread=False)
        _DB.executescript(_SCHEMA)
        _DB.commit()
    return _DB

def _fts_insert_or_replace(row: Dict[str, Any]) -> None:
    con = _db()
    if con is None:
        return
    with _LOCK:
        cur = con.cursor()
        symbols = json.dumps(row.get("symbols") or [], ensure_ascii=False)
        cur.execute(
            "INSERT OR REPLACE INTO docs (id,title,series,ts,epoch,symbols,text) VALUES (?,?,?,?,?,?,?)",
            (row["id"], row.get("title",""), row.get("series",""), float(row.get("ts") or 0.0),
             row.get("epoch"), symbols, row.get("text",""))
        )
        # keep FTS contentless table in sync
        cur.execute(
            "INSERT OR REPLACE INTO docs_fts (rowid,id,title,series,text) "
            "VALUES ((SELECT rowid FROM docs WHERE id=?),?,?,?,?)",
            (row["id"], row["id"], row.get("title",""), row.get("series",""), row.get("text",""))
        )
        con.commit()

def _fts_load_folder(root: str, pattern: str = "*.md") -> int:
    """
    Incremental loader:
      - inserts/updates records whose mtime changed
      - skips unchanged files (fast subsequent reindex)
    Stores stats in _LAST_INDEX_STATS and returns the number of UPDATED/INSERTED docs.
    """
    global _LAST_INDEX_STATS
    con = _db()
    if con is None:
        _LAST_INDEX_STATS = {
            "added": 0, "skipped": 0, "failed": 0, "considered": 0,
            "duration_sec": 0.0, "root": root, "pattern": pattern, "fts": False,
        }
        return 0

    base = Path(root)
    added = skipped = failed = considered = 0
    t0 = time.perf_counter()
    log.info("[INDEX][START] base=%s pattern=%s", base, pattern)

    with _LOCK:
        cur = con.cursor()
        for p in base.rglob(pattern):
            if not p.is_file():
                continue
            considered += 1
            try:
                if p.suffix.lower() not in {".md", ".markdown", ".txt"}:
                    skipped += 1
                    continue

                mtime = p.stat().st_mtime
                rid = str(p.resolve())
                # squash accidental duplicate segment we saw in logs
                rid = rid.replace("/lore-scrolls/lore-scrolls/", "/lore-scrolls/")

                # skip if unchanged
                cur.execute("SELECT ts FROM docs WHERE id=?", (rid,))
                row = cur.fetchone()
                if row and abs(float(row[0]) - float(mtime)) < 1e-6:
                    skipped += 1
                    continue

                text = p.read_text(encoding="utf-8", errors="ignore")
                row = {
                    "id": rid,
                    "title": _first_heading(text),
                    "series": _series_from_filename(p.name),
                    "ts": mtime,
                    "epoch": None,
                    "symbols": [],
                    "text": text,
                }
                _fts_insert_or_replace(row)
                added += 1
                if added <= 10:
                    log.info("[INDEX][ADD] %s", p)
            except Exception as e:
                failed += 1
                log.exception("[INDEX][FAIL] %s -> %s", p, e)
                continue

    duration = round(time.perf_counter() - t0, 2)
    _LAST_INDEX_STATS = {
        "added": added, "skipped": skipped, "failed": failed, "considered": considered,
        "duration_sec": duration, "root": root, "pattern": pattern, "fts": True,
    }

    print(
        f"[INDEX][SUMMARY] base={root} pattern={pattern} "
        f"added={added} skipped={skipped} failed={failed} considered={considered} "
        f"duration={duration}s"
    )
    try:
        with sqlite3.connect(_FTS_DB_PATH) as con2:
            docs_total = con2.execute("select count(*) from docs").fetchone()[0]
        print(f"📚 Current index docs_total={docs_total}")
    except Exception as e:
        print("⚠️ could not count docs:", e)

    return added

def _fts_search(terms: List[str], k: int) -> List[Dict[str, Any]]:
    con = _db()
    if con is None or not terms:
        return []
    # Build MATCH query like: "toby OR proof OR time"
    q = " OR ".join([f'"{t}"' for t in terms])
    sql = """
    SELECT d.id, d.title, d.series, d.ts, d.epoch, d.symbols, d.text,
           bm25(docs_fts) AS bm25_score
    FROM docs_fts
    JOIN docs d ON d.rowid = docs_fts.rowid
    WHERE docs_fts MATCH ?
    ORDER BY bm25_score ASC
    LIMIT ?
    """
    with _LOCK:
        cur = con.cursor()
        cur.execute(sql, (q, k * 4))  # fetch a bit extra before re-ranking
        rows = cur.fetchall()
    out = []
    for rid, title, series, ts, epoch, symbols, text, bm25_score in rows:
        try:
            syms = json.loads(symbols or "[]")
        except Exception:
            syms = []
        out.append({
            "id": rid, "title": title, "series": (series or "").upper(),
            "ts": float(ts or 0.0), "epoch": epoch, "symbols": syms,
            "text": text, "bm25": float(bm25_score or 0.0),
        })
    return out

def _fts_get_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    con = _db()
    if con is None or not doc_id:
        return None
    with _LOCK:
        cur = con.cursor()
        row = cur.execute(
            "SELECT id,title,series,ts,epoch,symbols,text FROM docs WHERE id=?", (doc_id,)
        ).fetchone()
    if not row:
        return None
    rid, title, series, ts, epoch, symbols, text = row
    try:
        syms = json.loads(symbols or "[]")
    except Exception:
        syms = []
    return {
        "id": rid, "title": title, "series": (series or "").upper(),
        "ts": float(ts or 0.0), "epoch": epoch, "symbols": syms,
        "text": text,
    }

# ── In-memory lexical fallback (if FTS5 unavailable) ──────────────────────────

_FALLBACK_INDEX: List[Dict[str, Any]] = []

def _fallback_set_index(rows: List[Dict[str, Any]]) -> int:
    global _FALLBACK_INDEX, _LAST_INDEX_STATS
    safe = []
    for r in rows:
        text = str(r.get("text",""))
        if not text.strip():
            continue
        rid = str(r.get("id","")).strip() or f"doc-{len(safe)+1}"
        safe.append({
            "id": rid,
            "title": r.get("title") or _first_heading(text),
            "series": (r.get("series") or _series_from_filename(Path(rid).name)).upper(),
            "ts": float(r.get("ts") or 0.0),
            "epoch": r.get("epoch"),
            "symbols": r.get("symbols") or [],
            "text": text,
        })
    _FALLBACK_INDEX = safe
    _LAST_INDEX_STATS = {
        "added": len(safe), "skipped": 0, "failed": 0, "considered": len(safe),
        "duration_sec": 0.0, "root": None, "pattern": None, "fts": False,
    }
    print(f"[INDEX][SUMMARY][FALLBACK] added={len(safe)}")
    return len(_FALLBACK_INDEX)

def _fallback_search(terms: List[str], k: int) -> List[Dict[str, Any]]:
    if not terms:
        return _FALLBACK_INDEX[:k]
    scored = []
    for r in _FALLBACK_INDEX:
        toks = _tokens(r.get("text",""))
        score = sum(toks.count(t) for t in terms)
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k*4]]

# ── Public helpers ────────────────────────────────────────────────────────────

def close_db() -> None:
    """Close the FTS SQLite connection so reload/shutdown is clean."""
    global _DB
    try:
        if _DB is not None:
            with _LOCK:
                _DB.close()
    except Exception:
        pass
    finally:
        _DB = None

def index_stats() -> Dict[str, Any]:
    """Return stats about the index (works for FTS and fallback)."""
    stats = {
        "fts": _SUPPORTS_FTS,
        "db": _FTS_DB_PATH,
        "docs": 0,
        "indexing": indexing(),
        "last": dict(_LAST_INDEX_STATS) if _LAST_INDEX_STATS else None,
    }
    if _SUPPORTS_FTS:
        con = _db()
        if con is not None:
            try:
                with _LOCK:
                    row = con.execute("SELECT COUNT(*) FROM docs").fetchone()
                    stats["docs"] = int(row[0]) if row else 0
            except Exception:
                pass
    else:
        stats["docs"] = len(_FALLBACK_INDEX)
    return stats

def set_index(rows: List[Dict[str, Any]]) -> int:
    """
    Replace index with provided rows (id, text, optional title/series/ts/epoch/symbols).
    Uses FTS if supported; otherwise falls back to memory.
    """
    if _SUPPORTS_FTS:
        count = 0
        for r in rows:
            t = str(r.get("text",""))
            if not t.strip():
                continue
            rid = str(r.get("id","")).strip() or f"doc-{count+1}"
            row = {
                "id": rid,
                "title": r.get("title") or _first_heading(t),
                "series": (r.get("series") or _series_from_filename(Path(rid).name)).upper(),
                "ts": float(r.get("ts") or 0.0),
                "epoch": r.get("epoch"),
                "symbols": r.get("symbols") or [],
                "text": t,
            }
            _fts_insert_or_replace(row)
            count += 1
        global _LAST_INDEX_STATS
        _LAST_INDEX_STATS = {
            "added": count, "skipped": 0, "failed": 0, "considered": count,
            "duration_sec": 0.0, "root": None, "pattern": None, "fts": True,
        }
        return count
    else:
        return _fallback_set_index(rows)

def load_index_from_folder(root: str, pattern: str = "*.md") -> int:
    """
    (Re)load files from folder into the index.
    - If another indexing job is running, return 0 immediately (busy).
    - FTS path is incremental (skips unchanged by mtime).
    Returns the number of UPDATED/INSERTED docs (int) for backward-compat.
    Full stats are available via index_stats()['last'].
    """
    global _INDEXING
    if _INDEXING:
        log.warning("[INDEX] already running; skip")
        return 0
    _INDEXING = True
    try:
        if _SUPPORTS_FTS:
            return _fts_load_folder(root, pattern)
        else:
            rows = []
            base = Path(root)
            log.info("[INDEX][START][FALLBACK] base=%s pattern=%s", base, pattern)
            considered = 0
            for p in base.rglob(pattern):
                if not p.is_file():
                    continue
                considered += 1
                try:
                    if p.suffix.lower() not in {".md", ".markdown", ".txt"}:
                        continue
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except Exception as e:
                    log.exception("[INDEX][FAIL][FALLBACK] %s -> %s", p, e)
                    continue
                rows.append({
                    "id": str(p.resolve()),
                    "title": _first_heading(text),
                    "series": _series_from_filename(p.name),
                    "ts": p.stat().st_mtime,
                    "epoch": None,
                    "symbols": [],
                    "text": text,
                })
            count = _fallback_set_index(rows)
            print(f"[INDEX][SUMMARY][FALLBACK] base={root} pattern={pattern} added={count} considered={considered}")
            return count
    finally:
        _INDEXING = False

# ── Retriever ─────────────────────────────────────────────────────────────────

@dataclass
class _Knobs:
    k_normal: int = config.RETRIEVER.K_NORMAL
    k_deep: int = config.RETRIEVER.K_DEEP
    series_boost: float = config.RETRIEVER.SERIES_BOOST
    recency_half_life_days: float = config.RETRIEVER.RECENCY_HALF_LIFE_DAYS

class Retriever:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self.k = _Knobs()

    def multi_arc(self, query: str, hint: dict | None = None) -> List[Dict[str, Any]]:
        """
        Returns ranked chunks:
        [{doc_id, span, ts, epoch, score, symbols, text}]
        """
        q = (query or "").strip()
        hint = hint or {}
        q_terms = _tokens(q)
        kw = [k.lower() for k in hint.get("keywords", [])]
        terms = _uniq(q_terms + kw)
        depth = hint.get("depth") or "normal"
        prefer_series = [s.upper() for s in hint.get("prefer_series", [])]
        pins = hint.get("pins", [])

        # Wider gather pool, then trim
        if depth == "deep":
            k_fetch = TOPK_RAW
        else:
            k_fetch = max(24, TOPK_RAW // 2)

        # Search (FTS or fallback)
        cand = _fts_search(terms, k_fetch) if _SUPPORTS_FTS else _fallback_search(terms, k_fetch)

        # Inject canon pins (guaranteed top presence if found)
        for pid in pins:
            got = _fts_get_by_id(pid) if _SUPPORTS_FTS else None
            if got:
                cand.insert(0, got)

        now = _now_ts()
        half = self.k.recency_half_life_days * 86400.0

        # Score blend (bm25 → 1/(1+bm25)), series boost, recency bonus
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for r in cand:
            # base from bm25 (lower better) → convert to 0..1
            if "bm25" in r:
                base = 1.0 / (1.0 + max(0.0, r.get("bm25") or 0.0))
            else:
                toks = _tokens(r.get("text",""))
                overlap = sum(toks.count(t) for t in terms)
                base = min(1.0, 0.1 * overlap) if overlap > 0 else 0.0
            if base <= 0.0:
                continue

            # series boost
            sboost = 0.0
            sname = (r.get("series") or "").upper()
            for rank, wanted in enumerate(prefer_series, start=1):
                if sname == wanted:
                    sboost = self.k.series_boost / rank
                    break
            base *= (1.0 + sboost)

            # recency
            ts = float(r.get("ts") or 0.0)
            if ts > 0.0 and now > ts and half > 0:
                age = now - ts
                rec = 0.15 * math.exp(-age / half)  # up to +15%
                base *= (1.0 + rec)

            scored.append((base, r))

        # Sort by score desc
        scored.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate by doc id (preserve order)
        seen, deduped = set(), []
        for s, r in scored:
            did = r.get("id")
            if not did or did in seen:
                continue
            seen.add(did)
            r = dict(r)
            r["_norm_score"] = float(s)  # attach per-doc score for logging/output
            deduped.append(r)

        # Filter by MIN_SCORE (on normalized score)
        filtered = [r for r in deduped if r.get("_norm_score", 0.0) >= MIN_SCORE]

        # Final cap
        final_docs = filtered[:TOPK_FINAL]

        # Build output chunks
        out: List[Dict[str, Any]] = []
        for r in final_docs:
            snippet, span = _chunk_text(r.get("text",""))
            out.append({
                "doc_id": r.get("id"),
                "span": list(span),
                "ts": r.get("ts"),
                "epoch": r.get("epoch"),
                "score": round(float(r.get("_norm_score", 0.0)), 3),
                "symbols": r.get("symbols") or [],
                "text": snippet,
            })

        # Console debug
        try:
            print(json.dumps({
                "evt": "retriever.debug",
                "q": q[:120],
                "pins": pins,
                "raw": len(cand),
                "deduped": len(deduped),
                "filtered": len(filtered),
                "final": len(out),
                "top_preview": [{
                    "id": (r.get("id") or "")[:72],
                    "title": (r.get("title") or "")[:60],
                    "score": round(float(r.get("_norm_score", 0.0)), 3)
                } for r in final_docs[:10]],
            }, ensure_ascii=False))
        except Exception:
            pass

        # graceful fallback: if nothing found and we have a query, echo it
        if not out and q:
            snippet, span = _chunk_text(q)
            out = [{
                "doc_id": "SYNTH://echo",
                "span": list(span),
                "ts": 0.0,
                "epoch": "E?",
                "score": 0.5,
                "symbols": ["🪞"],
                "text": snippet,
            }]
        return out

# explicit exports so reloaders / hasattr see them
__all__ = [
    "indexing", "index_stats", "set_index", "load_index_from_folder", "close_db",
    "Retriever"
]

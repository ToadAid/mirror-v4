# src/tobyworld_v4/core/v4/memori_status.py
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import os, time, sqlite3, pathlib, json, datetime as dt, io, csv

router = APIRouter()
API_TOKEN = os.getenv("MEMORI_TOKEN")  # set to require 'x-token' on writes/deletes/purge

# ---------------- Helpers ----------------
def _db():
    path = os.getenv("MEMORI_DB") or os.path.join(os.getenv("MIRROR_ROOT", "."), "memori.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def _ts():
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _ensure_tables(conn):
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS memori_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      kind TEXT NOT NULL,
      payload TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS memori_notes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      user_id TEXT NOT NULL,
      note TEXT NOT NULL
    )""")
    conn.commit()

def _tune_sqlite(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memori_events_kind ON memori_events(kind);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memori_notes_user ON memori_notes(user_id);")
    conn.commit()

def _require_token(token: str | None):
    if not API_TOKEN:  # auth disabled
        return
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")

# best-effort one-time init/tune at import
try:
    __conn = _db()
    _ensure_tables(__conn)
    _tune_sqlite(__conn)
    __conn.close()
except Exception:
    pass

# ---------------- Models ----------------
class NoteIn(BaseModel):
    user_id: str
    note: str

class EventIn(BaseModel):
    kind: str
    payload: dict | list | str

# ---------------- Routes ----------------
@router.get("/v5/memori/ping")
def memori_ping():
    return {"ok": True, "service": "memori"}

@router.get("/v5/memori/status")
def memori_status():
    """Hardened status endpoint for Memori — always JSON output."""
    t0 = time.perf_counter()
    info = {
        "ok": True,
        "service": "memori",
        "db_path": os.getenv("MEMORI_DB") or os.path.join(os.getenv("MIRROR_ROOT", "."), "memori.db"),
        "db_exists": None,
        "db_dir_writable": None,
        "notes_count": None,
        "events_count": None,
    }
    try:
        p = pathlib.Path(info["db_path"])
        info["db_exists"] = p.exists()
        info["db_dir_writable"] = os.access(p.parent, os.W_OK)
        conn = _db()
        cur = conn.cursor()
        def count_safe(table):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                return cur.fetchone()[0]
            except Exception as e:
                return f"err: {type(e).__name__}: {e}"
        info["notes_count"] = count_safe("memori_notes")
        info["events_count"] = count_safe("memori_events")
        conn.close()
    except Exception as e:
        info["ok"] = False
        info["error"] = f"{type(e).__name__}: {e}"
    finally:
        info["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return JSONResponse(info)

@router.get("/v5/memori/summary")
def memori_summary(limit: int = 20):
    """Lightweight summary of recent memori notes/events."""
    db_path = os.getenv("MEMORI_DB") or os.path.join(os.getenv("MIRROR_ROOT", "."), "memori.db")
    try:
        conn = _db()
        cur = conn.cursor()
        def rows(sql, *args):
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]
        notes = rows(
            "SELECT id, created_at, user_id, note FROM memori_notes ORDER BY id DESC LIMIT ?",
            limit,
        )
        events = rows(
            "SELECT id, created_at, kind, payload FROM memori_events ORDER BY id DESC LIMIT ?",
            limit,
        )
        for e in events:
            try:
                e["payload"] = json.loads(e.get("payload") or "{}")
            except Exception:
                pass
        total_notes = cur.execute("SELECT COUNT(*) FROM memori_notes").fetchone()[0]
        total_events = cur.execute("SELECT COUNT(*) FROM memori_events").fetchone()[0]
        conn.close()
        return {
            "ok": True,
            "db_path": db_path,
            "total_notes": total_notes,
            "total_events": total_events,
            "recent": {"notes": notes, "events": events},
        }
    except Exception as e:
        return {"ok": False, "db_path": db_path, "error": f"{type(e).__name__}: {e}"}

# --- Writers (token-gated if MEMORI_TOKEN set) ---
@router.post("/v5/memori/note")
def memori_note(body: NoteIn, x_token: str | None = Header(None)):
    _require_token(x_token)
    conn = _db()
    try:
        _ensure_tables(conn); _tune_sqlite(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO memori_notes(created_at,user_id,note) VALUES(?,?,?)",
            (_ts(), body.user_id.strip(), body.note.strip()),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

@router.post("/v5/memori/event")
def memori_event(body: EventIn, x_token: str | None = Header(None)):
    _require_token(x_token)
    conn = _db()
    try:
        _ensure_tables(conn); _tune_sqlite(conn)
        cur = conn.cursor()
        payload_str = body.payload if isinstance(body.payload, str) else json.dumps(body.payload, ensure_ascii=False)
        cur.execute(
            "INSERT INTO memori_events(created_at,kind,payload) VALUES(?,?,?)",
            (_ts(), body.kind.strip(), payload_str),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

# --- Readers ---
@router.get("/v5/memori/events")
def memori_events(kind: str | None = None, limit: int = 50):
    conn = _db()
    try:
        cur = conn.cursor()
        if kind:
            cur.execute(
                "SELECT id, created_at, kind, payload FROM memori_events WHERE kind=? ORDER BY id DESC LIMIT ?",
                (kind, limit),
            )
        else:
            cur.execute(
                "SELECT id, created_at, kind, payload FROM memori_events ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try: r["payload"] = json.loads(r["payload"] or "{}")
            except Exception: pass
        return {"ok": True, "events": rows}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

@router.get("/v5/memori/notes")
def memori_notes(user_id: str | None = None, limit: int = 50):
    conn = _db()
    try:
        cur = conn.cursor()
        if user_id:
            cur.execute(
                "SELECT id, created_at, user_id, note FROM memori_notes WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            cur.execute(
                "SELECT id, created_at, user_id, note FROM memori_notes ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return {"ok": True, "notes": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

# --- Deletes (token-gated if MEMORI_TOKEN set) ---
@router.delete("/v5/memori/note/{note_id}")
def memori_note_delete(note_id: int, x_token: str | None = Header(None)):
    _require_token(x_token)
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM memori_notes WHERE id=?", (note_id,))
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

@router.delete("/v5/memori/event/{event_id}")
def memori_event_delete(event_id: int, x_token: str | None = Header(None)):
    _require_token(x_token)
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM memori_events WHERE id=?", (event_id,))
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

# --- Purge & Export (admin) ---
@router.delete("/v5/memori/purge")
def memori_purge(x_token: str | None = Header(None)):
    _require_token(x_token)
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM memori_events;")
        cur.execute("DELETE FROM memori_notes;")
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()

@router.get("/v5/memori/export")
def memori_export(which: str = "all", fmt: str = "json", limit: int = 1000):
    """
    Export notes/events. For fmt=csv, set which=notes or which=events (not 'all').
    """
    which = which.lower()
    fmt = fmt.lower()
    conn = _db()
    try:
        cur = conn.cursor()

        def q(sql, *args):
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]

        notes = events = None
        if which in ("all", "notes"):
            notes = q("SELECT id, created_at, user_id, note FROM memori_notes ORDER BY id DESC LIMIT ?", limit)
        if which in ("all", "events"):
            rows = q("SELECT id, created_at, kind, payload FROM memori_events ORDER BY id DESC LIMIT ?", limit)
            # parse payloads
            for r in rows:
                try: r["payload"] = json.loads(r["payload"] or "{}")
                except Exception: pass
            events = rows

        if fmt == "json":
            payload = {"ok": True, "which": which, "notes": notes, "events": events}
            return JSONResponse(payload)

        if fmt == "csv":
            if which == "notes":
                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=["id", "created_at", "user_id", "note"])
                w.writeheader()
                for r in notes or []: w.writerow(r)
                return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                         headers={"Content-Disposition": 'attachment; filename="memori_notes.csv"'})
            if which == "events":
                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=["id", "created_at", "kind", "payload"])
                w.writeheader()
                for r in events or []:
                    row = dict(r); 
                    if isinstance(row.get("payload"), (dict, list)):
                        row["payload"] = json.dumps(row["payload"], ensure_ascii=False)
                    w.writerow(row)
                return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                         headers={"Content-Disposition": 'attachment; filename="memori_events.csv"'})
            raise HTTPException(400, "csv export supports which=notes or which=events (not 'all')")
        raise HTTPException(400, "fmt must be json or csv")
    finally:
        conn.close()

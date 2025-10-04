# memori_status.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import os, time, sqlite3, pathlib

router = APIRouter()

def _db_path():
    p = os.getenv("MEMORI_DB") or "/home/tommy/mirror-v4/memori.db"
    return p

@router.get("/v5/memori/status")
def memori_status():
    t0 = time.perf_counter()
    info = {
        "ok": True,
        "service": "memori",
        "db_path": _db_path(),
        "db_exists": None,
        "db_dir_writable": None,
        "notes_count": None,
        "events_count": None,
    }
    try:
        db = info["db_path"]
        dbp = pathlib.Path(db)
        info["db_exists"] = dbp.exists()
        info["db_dir_writable"] = os.access(dbp.parent, os.W_OK)

        conn = sqlite3.connect(db)
        cur  = conn.cursor()
        # notes_count (report errors instead of throwing)
        try:
            cur.execute("SELECT COUNT(*) FROM memori_notes")
            info["notes_count"] = cur.fetchone()[0]
        except Exception as e:
            info["notes_count"] = f"err: {type(e).__name__}: {e}"
        # events_count
        try:
            cur.execute("SELECT COUNT(*) FROM memori_events")
            info["events_count"] = cur.fetchone()[0]
        except Exception as e:
            info["events_count"] = f"err: {type(e).__name__}: {e}"
        conn.close()
    except Exception as e:
        info["ok"] = False
        info["error"] = f"{type(e).__name__}: {e}"
    finally:
        info["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return JSONResponse(info)

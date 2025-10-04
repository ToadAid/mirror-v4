# Telegram webhook → forwards to Mirror V4 /ask (and nicer /reload UX)

import os, re, time, json, logging, asyncio
from typing import Any, Dict, Optional, List, Set, Tuple
from fastapi import APIRouter, Request, HTTPException
import httpx

log = logging.getLogger("telegram")
router = APIRouter()

# ---------- Env ----------
TELEGRAM_BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")  # legacy
    or os.getenv("TOKEN")
    or ""
).strip()

TELEGRAM_API = (
    os.getenv("TELEGRAM_API").strip()
    if os.getenv("TELEGRAM_API")
    else (f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else "")
)

TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "").strip()
TELEGRAM_WEBHOOK_URL = (os.getenv("TELEGRAM_WEBHOOK_URL") or "").strip()
TELEGRAM_MODE = (os.getenv("TELEGRAM_MODE") or "webhook").strip().lower()  # webhook | poll

# Where Mirror V4 lives (its /ask, /reindex, /status endpoints)
MIRROR_BASE_URL = (os.getenv("MIRROR_BASE_URL") or "http://127.0.0.1:8080").rstrip("/")

# Optional allowlist: "12345,@tommyng"
_ALLOWED = os.getenv("TELEGRAM_ALLOWLIST", "").strip()
ALLOWLIST_IDS: Set[str] = set()
ALLOWLIST_USERS: Set[str] = set()
if _ALLOWED:
    for tok in _ALLOWED.split(","):
        t = tok.strip()
        if not t:
            continue
        if re.fullmatch(r"-?\d+", t):
            ALLOWLIST_IDS.add(t)
        else:
            ALLOWLIST_USERS.add(t.lstrip("@").lower())

# Basic rate-limit per chat
RL_N = int(os.getenv("TELEGRAM_RATE_N", "12"))
RL_WIN = int(os.getenv("TELEGRAM_RATE_WINDOW_S", "60"))
_rate: Dict[str, List[float]] = {}

CMD_ASK    = os.getenv("TELEGRAM_CMD_ASK", "/ask").strip() or "/ask"
CMD_START  = os.getenv("TELEGRAM_CMD_START", "/start").strip() or "/start"
CMD_PING   = os.getenv("TELEGRAM_CMD_PING", "/ping").strip() or "/ping"
CMD_RELOAD = os.getenv("TELEGRAM_CMD_RELOAD", "/reload").strip() or "/reload"

# ---------- Helpers ----------
def _allowed(chat_id: Optional[int], username: Optional[str]) -> bool:
    if not ALLOWLIST_IDS and not ALLOWLIST_USERS:
        return True
    if chat_id is not None and str(chat_id) in ALLOWLIST_IDS:
        return True
    if username and username.lstrip("@").lower() in ALLOWLIST_USERS:
        return True
    return False

def _rate_ok(key: str) -> bool:
    now = time.time()
    arr = _rate.setdefault(key, [])
    while arr and (now - arr[0]) > RL_WIN:
        arr.pop(0)
    if len(arr) >= RL_N:
        return False
    arr.append(now)
    return True

def _first_text(msg: Dict[str, Any]) -> str:
    return (msg.get("text") or msg.get("caption") or "").strip()

def _chunk(s: str, n: int = 3900) -> List[str]:
    out, cur = [], []
    cur_len = 0
    for part in s.splitlines(keepends=True):
        if cur_len + len(part) > n and cur:
            out.append("".join(cur))
            cur, cur_len = [], 0
        if len(part) > n:
            for i in range(0, len(part), n):
                if cur:
                    out.append("".join(cur))
                    cur, cur_len = [], 0
                out.append(part[i:i+n])
            continue
        cur.append(part)
        cur_len += len(part)
    if cur:
        out.append("".join(cur))
    return out or [s]

async def _tg(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not TELEGRAM_API:
        return {"ok": False, "error": "No TELEGRAM_API configured"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{TELEGRAM_API}/{method}", json=payload)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "text": r.text}

async def _tg_send(chat_id: int | str, text: str) -> None:
    try:
        await _tg("sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as e:
        log.warning("tg send failed: %s", e)

async def _mirror_ask(user: str, question: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{MIRROR_BASE_URL}/ask", json={"user": user, "question": question})
        return r.json()

def _format_arcs(index_stats: Dict[str, Any] | None) -> str:
    """
    Render an 'Arcs: {...}' breakdown if present in index_stats.
    Looks for common keys: 'arcs', 'arc_counts', 'by_arc', 'tags'.
    """
    if not isinstance(index_stats, dict):
        return ""
    arcs = None
    for key in ("arcs", "arc_counts", "by_arc", "tags", "arc_breakdown"):
        val = index_stats.get(key)
        if isinstance(val, dict) and val:
            arcs = val
            break
    if not arcs:
        return ""
    items = ", ".join(f"'{k}': {v}" for k, v in sorted(arcs.items(), key=lambda kv: (-int(kv[1]), kv[0])))
    return f" | Arcs: {{{items}}}"

async def _do_reload_and_report(chat_id: int | str) -> None:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, read=600, write=600, pool=600)
        ) as client:
            r = await client.post(f"{MIRROR_BASE_URL}/reindex", params={"pattern": "**/*", "background": "false"})
            r.raise_for_status()
            s = await client.get(f"{MIRROR_BASE_URL}/status")
            s.raise_for_status()
            st = s.json()
    except Exception as e:
        await _tg_send(chat_id, f"❌ Reload failed: {e}")
        return
    scrolls = st.get("scrolls_loaded")
    arcs_tail = _format_arcs(st.get("index_stats"))
    msg = f"✅ Reloaded. Scrolls: {scrolls}{arcs_tail}"
    await _tg_send(chat_id, msg)

def _extract(text: str) -> Tuple[str, str]:
    t = (text or "").strip()
    if t.startswith(CMD_ASK + " "): return (CMD_ASK, t[len(CMD_ASK):].strip())
    if t == CMD_ASK:                 return (CMD_ASK, "")
    if t.startswith(CMD_START):      return (CMD_START, t[len(CMD_START):].strip())
    if t.startswith(CMD_PING):       return (CMD_PING, t[len(CMD_PING):].strip())
    if t.startswith(CMD_RELOAD):     return (CMD_RELOAD, t[len(CMD_RELOAD):].strip())
    return ("", t)

# ---------- Routes ----------
@router.post("/tg/webhook")
async def tg_webhook(request: Request):
    if TELEGRAM_SECRET_TOKEN:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != TELEGRAM_SECRET_TOKEN:
            raise HTTPException(401, "Invalid telegram secret")
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(401, "No TELEGRAM_BOT_TOKEN configured")

    body = await request.json()
    msg = body.get("message") or body.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = _first_text(msg)
    username = (msg.get("from") or {}).get("username")

    if not chat_id or not text:
        return {"ok": True}
    if not _allowed(chat_id, username):
        return {"ok": True}
    if not _rate_ok(str(chat_id)):
        await _tg_send(chat_id, "⏳ please slow down; try again shortly.")
        return {"ok": True}

    cmd, rest = _extract(text)

    if cmd == CMD_START:
        await _tg_send(chat_id, "🪞 Mirror V4 ready.\nUse /ask <question> or just send a message.")
        return {"ok": True}
    if cmd == CMD_PING:
        await _tg_send(chat_id, "pong")
        return {"ok": True}
    if cmd == CMD_RELOAD:
        await _tg_send(chat_id, "♻️ Reloading scroll index...")
        await _tg_send(chat_id, "🔄 Rebuilding RAG index...")
        asyncio.create_task(_do_reload_and_report(chat_id))
        return {"ok": True}

    question = rest if cmd == CMD_ASK else text
    try:
        ans = await _mirror_ask(f"tg:{username or chat_id}", question)
        out = ans.get("answer") or json.dumps(ans, ensure_ascii=False, indent=2)
        for chunk in _chunk(out, 3900):
            await _tg_send(chat_id, chunk)
    except Exception as e:
        await _tg_send(chat_id, f"⚠️ Mirror error: {e}")
    return {"ok": True}

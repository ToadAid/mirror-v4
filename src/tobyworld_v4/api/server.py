# tobyworld_v4/api/server.py

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import os, time, threading, asyncio, json, re, random, io, hashlib
from typing import Any, Dict, List
from collections import deque, Counter  # cadence telemetry

from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import Response, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------- Middleware ----------
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

import sqlite3
from pathlib import Path

# ---- Core config (must come before FastAPI init) ----
APP_NAME = os.getenv("APP_NAME", "Mirror V4")
ROOT_PATH = os.getenv("ROOT_PATH", "").strip()  # e.g. "/mirror-v4"

# Create app AFTER env vars are set
app = FastAPI(title=APP_NAME, root_path=ROOT_PATH or "")

# Portable default root + DB path
default_root = Path(os.getenv("MIRROR_ROOT", Path(__file__).resolve().parents[2]))
db_path = os.getenv("LEDGER_DB", str(default_root / "mirror-v4.db"))

import unicodedata

_PUNCT_MAP = {
    0x2013: '-',  # – en dash
    0x2014: '-',  # — em dash
    0x2018: "'",  # ‘
    0x2019: "'",  # ’
    0x201C: '"',  # “
    0x201D: '"',  # ”
    0x00A0: ' ',  # nbsp
}

def sanitize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return s.translate(_PUNCT_MAP)

# --- ASCII sanitization helpers (global kill-switch) ---
FORCE_ASCII_ALL = os.getenv("FORCE_ASCII_ALL", "0").lower() in ("1","true","yes","on")

def sanitize_payload(obj, force_ascii: bool = FORCE_ASCII_ALL):
    if isinstance(obj, str):
        s = sanitize_text(obj)
        if force_ascii:
            # Replace non-ASCII characters instead of ignoring them
            s = s.encode("ascii", "replace").decode("ascii")
            # Alternatively:
            # s = s.encode("ascii", "ignore").decode("ascii")
        return s
    if isinstance(obj, dict):
        return {k: sanitize_payload(v, force_ascii) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_payload(v, force_ascii) for v in obj]
    return obj

# Optional system/metrics libs (best-effort)
try:
    import psutil  # CPU/mem/disk snapshot
except Exception:
    psutil = None

# --------- Ring buffers & helpers (NEW) ------------------------------------
TRACE_BUF = deque(maxlen=1000)   # recent /ask traces
RAG_BUF   = deque(maxlen=1000)   # recent retrieval hits
LOG_BUF   = deque(maxlen=2000)   # app log lines (if you don't tail a file)

def now_ms() -> int:
    return int(time.time() * 1000)

def push_trace(item: dict):
    item["ts"] = now_ms()
    TRACE_BUF.append(item)

def push_rag(item: dict):
    item["ts"] = now_ms()
    RAG_BUF.append(item)

def push_log(line: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    LOG_BUF.append(f"[{ts}] {line.rstrip()}")

# Core V4 pieces
from tobyworld_v4.core.v4 import (
    Guide, Synthesis, Resonance, Lucidity,
    Ledger, Learning, Heartbeat, Rites, RunCtx, config
)
import tobyworld_v4.core.v4.retriever as retr
from tobyworld_v4.core.v4.renderer import render_reflection
from tobyworld_v4.core.v4.prompt_manager import PM

# Identity-aware memory
from tobyworld_v4.core.v4.memory_identity import (
    parse_user_token, resolve_traveler, merge_travelers, forget_traveler, ensure_tables
)
from tobyworld_v4.core.v4.memory import Memory

# Safeguards
from tobyworld_v4.core.v4.safeguards import (
    temporal_breaker, symbol_breaker, conversation_breaker,
    privacy_filter, confidence_validator, performance_aware
)

# Enhancements
from tobyworld_v4.core.v4.temporal_context import get_temporal_context
from tobyworld_v4.core.v4.symbol_resonance import get_symbol_resonance
from tobyworld_v4.core.v4.conversation_weaver import ConversationWeaver, conversation_weaver

# Then replace all get_conversation_weaver() calls with:
# conversation_weaver (the global instance)

# Off ramp
from tobyworld_v4.core.v4.off_ramp import should_exit_gracefully, generate_final_farewell

# LLM client
from tobyworld_v4.llm.client import LLMClient
llm = LLMClient()

# Prometheus (multiprocess-aware)
from tobyworld_v4.core.v4.metrics import (
    REG, generate_latest, CONTENT_TYPE_LATEST,
    mv4_llm_fallbacks_total, mv4_reindex_lock_collisions_total,
    track_request
)
from prometheus_client import Gauge
from prometheus_client import Counter as PCounter, Histogram as PHistogram

# Telegram router (NEW)
from tobyworld_v4.api.telegram import router as telegram_router

APP_NAME = os.getenv("APP_NAME", "Mirror V4")
SCROLLS_DIR = os.getenv("SCROLLS_DIR", getattr(config.RETRIEVER, "SCROLLS_DIR", "lore-scrolls"))
WEB_DIR = os.getenv("WEB_DIR", "web")
DISABLE_STARTUP_INDEX = os.getenv("DISABLE_STARTUP_INDEX", "0").lower() in ("1", "true", "yes", "on")
SHOW_SOURCES = os.getenv("SHOW_SOURCES", "0").lower() in ("1", "true", "yes")

# Path prefix for reverse proxies (e.g., Nginx)
ROOT_PATH = os.getenv("ROOT_PATH", "").strip()  # e.g. "/mirror-v4"

# CORS / Hosts from env
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]  # e.g. "mirror.toadaid.xyz,abcd.ngrok-free.app"

# --- RAG/LLM guards & reply size controls (UPDATED) ---
REQUIRE_CITATION = os.getenv("REQUIRE_CITATION", "true").lower() in ("1","true","yes","on")
LLM_FALLBACK_MODE = os.getenv("LLM_FALLBACK_MODE", "canon_only")  # off | loose | canon_only

# Reply size controls (0 = unlimited)
MAX_SENTENCES   = int(os.getenv("MAX_SENTENCES", "0"))
MAX_CHARS       = int(os.getenv("MAX_CHARS", "0"))
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "900"))

# Canon anchors (ids, comma-separated)
CANON_ANCHORS_WHO   = [s for s in os.getenv("CANON_ANCHORS_WHO","TOBY_L025,TOBY_QA127").split(",") if s]
CANON_ANCHORS_LEAF  = [s for s in os.getenv("CANON_ANCHORS_LEAF","TOBY_L110,TOBY_L028").split(",") if s]
CANON_ANCHORS_TABOSHI = [s for s in os.getenv("CANON_ANCHORS_TABOSHI","TOBY_L110,TOBY_L057").split(",") if s]

# ----- tiny JSON logger (updated to also buffer) -----
def jlog(evt: str, **fields):
    payload = {"evt": evt, **fields}
    try:
        s = json.dumps(payload, ensure_ascii=False)
        print(s)
        push_log(s)
    except Exception:
        safe = {k: (str(v)[:512]) for k, v in payload.items()}
        s = json.dumps(safe, ensure_ascii=False)
        print(s)
        push_log(s)

# =============================================================================
# Memori (lazy) — SDK shape: record_conversation(user_input, ai_output, model, metadata)
# =============================================================================
_MEMORI_ENGINE = None

def _env_true(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")

def get_memori_engine():
    if not _env_true("USE_MEMORI", "false"):
        return None
    global _MEMORI_ENGINE
    if _MEMORI_ENGINE is not None:
        return _MEMORI_ENGINE
    try:
        from memori import Memori

        # Prefer DSN; else build one from MEMORI_DB
        dsn_env = os.getenv("MEMORI_DSN", "").strip()
        if dsn_env:
            dsn = dsn_env
        else:
            db_path = os.getenv("MEMORI_DB", "").strip() or "./memori.db"
            dsn = f"sqlite:////{db_path}" if db_path.startswith("/") else f"sqlite:///{db_path}"

        m = Memori(dsn)  # positional DSN
        m.enable()

        # 🔒 Don't let Memori's internal agents run
        for name in ("llm", "conscious", "planner"):
            try:
                m.disable_interceptor(name)
            except Exception:
                pass

        _MEMORI_ENGINE = m
        print(f"[memori] enabled @ {dsn}")
        return _MEMORI_ENGINE
    except Exception as e:
        print(f"[memori] disabled: {e}")
        return None

class MemoriAdapter:
    """
    Shim to unify calls: save(uid, q, a, meta), recall(uid, q, topk), short_context(uid)
    Partitions by `namespace`, carries uid in metadata.
    """
    def __init__(self, engine, topk: int = 8):
        self.m = engine
        self.topk = topk

    def _scope(self, uid: str):
        if hasattr(self.m, "namespace"):
            try:
                self.m.namespace = f"user:{uid}"
            except Exception:
                pass

    def save(self, uid: str, q: str, a: str, meta: dict | None = None):
        self._scope(uid)
        try:
            if hasattr(self.m, "start_new_conversation"):
                try:
                    self.m.start_new_conversation()
                except Exception:
                    pass
            # Sanitize + force ASCII to avoid codec errors in Memori paths
            q_s = sanitize_text(q or "").encode("ascii", "ignore").decode("ascii")
            a_s = sanitize_text(a or "").encode("ascii", "ignore").decode("ascii")
            self.m.record_conversation(
                user_input=q_s,
                ai_output=a_s,
                model=os.getenv("LLM_MODEL", "unknown"),
                metadata={"user_id": uid, **(meta or {})},
            )
            jlog("memori.save.ok", uid=uid)
        except Exception as e:
            jlog("memori.save.err", error=str(e))

    def recall(self, uid: str, q: str, topk: int | None = None):
        self._scope(uid)
        try:
            return self.m.retrieve_context(query=q or "", limit=topk or self.topk)
        except Exception as e:
            jlog("memori.recall.err", error=str(e))
            return []

    def short_context(self, uid: str) -> str:
        self._scope(uid)
        try:
            ctx = self.m.retrieve_context(query="", limit=3)
            if isinstance(ctx, list) and ctx:
                return " | ".join(
                    (c.get("content") or "")[:80].strip() for c in ctx if isinstance(c, dict)
                )
        except Exception:
            pass
        return ""

# =============================================================================
# User token inference (headers/cookies/fingerprint) — to avoid 'anon'
# =============================================================================
UID_SALT = os.getenv("UID_SALT", "mv4_salt")

def _hash_uid(parts: List[str]) -> str:
    s = "|".join([p for p in parts if p])
    h = hashlib.sha256((UID_SALT + "|" + s).encode("utf-8")).hexdigest()[:24]
    return f"fp:{h}"

def infer_user_token(body: "AskRequest", request: Request) -> str:
    """
    Choose a stable user token for identity & memory:
    1) Body.user if not anon
    2) One of several headers
    3) Cookie
    4) Fingerprint of IP+UA with salt
    """
    # 1) body.user (non-empty, not anon/guest)
    user = (getattr(body, "user", "") or "").strip()
    if user and user.lower() not in ("anon", "anonymous", "guest"):
        return user

    # 2) headers
    hdrs = request.headers
    for name in (
        "x-uid",
        "x-user",
        "x-client-id",
        "x-session-id",
        "x-telegram-user-id",
        "x-forwarded-user",
        "x-ms-client-principal-id",
    ):
        val = hdrs.get(name)
        if val and val.strip():
            return val.strip()

    # 3) cookies
    try:
        for name in ("mv4_uid", "uid", "sid", "mv4_sid"):
            val = request.cookies.get(name)
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        pass

    # 4) IP + UA fingerprint (salted)
    ip = hdrs.get("x-forwarded-for", "") or (request.client.host if request.client else "")
    ip = ip.split(",")[0].strip() if ip else ""
    ua = hdrs.get("user-agent", "")
    return _hash_uid([ip, ua])

# --- Extract themes for guiding question ---
def _generate_guiding_question(user_query: str, mirror_answer: str, ctx: Dict[str, Any]) -> str:
    query_keywords = _extract_key_themes(user_query)
    answer_keywords = _extract_key_themes(mirror_answer)
    combined_themes = list(set(query_keywords + answer_keywords))
    guiding_templates = [
        "How does {theme} resonate with your current journey?",
        "What would it mean to embrace {theme} more fully in your path?",
        "How might {theme} illuminate your next step?",
        "Where have you encountered {theme} before, and what did it teach you?",
        "If {theme} were a guide, what direction would it point you toward?",
        "What stillness surrounds your relationship with {theme}?",
        "How does {theme} mirror deeper patterns in your life?",
        "What vow or commitment does {theme} invite from you?",
        "How might {theme} transform if viewed through the lens of patience?",
        "What golden fruit might {theme} yield if nurtured with care?",
    ]
    if combined_themes:
        theme = random.choice(combined_themes)
        template = random.choice(guiding_templates)
        return template.format(theme=theme)
    return random.choice(_GUIDING_POOL_DEFAULT)

def _extract_key_themes(text: str) -> list:
    if not text:
        return []
    theme_patterns = [
        r'\b(patience|stillness|silence|waiting)\b',
        r'\b(journey|path|step|direction)\b',
        r'\b(truth|wisdom|knowledge|understanding)\b',
        r'\b(vow|promise|commitment|dedication)\b',
        r'\b(mirror|reflection|echo|resonance)\b',
        r'\b(lotus|pond|water|flow)\b',
        r'\b(ledger|record|history|memory)\b',
        r'\b(tree|growth|fruit|yield)\b',
        r'\b(loyalty|strength|quiet|care)\b',
        r'\b(pattern|cycle|season|epoch)\b',
    ]
    themes = []
    text_lower = text.lower()
    for pattern in theme_patterns:
        m = re.search(pattern, text_lower)
        if m:
            themes.append(m.group(1))
    return themes

# --- Mirror cadence + anchors (for /ask) ---
def _ensure_mirror_cadence(text: str, user_query: str = None, ctx: Dict[str, Any] = None) -> str:
    t = (text or "").strip()
    if not t:
        return t
    if not re.search(r"(?im)^Traveler[,，]?", t.splitlines()[0]):
        t = "Traveler,\n\n" + t
    if not re.search(r"[🪞🌊🍃🌀]", t):
        t = t.rstrip() + "\n\n" + " ".join(["🪞","🌊","🍃","🌀"]) + "\n"

    # Detect ANY Guiding Question label (EN only), bold/plain, anywhere
    gq_any_re = re.compile(r'(?i)(?:\*\*\s*)?guiding\s*question\s*[:：]')
    if not gq_any_re.search(t):
        guiding_question = _generate_guiding_question(user_query or "", t, ctx or {})
        t = t.rstrip() + f"\n\n**Guiding Question:** {guiding_question}\n"
    return t

# --- Thematic anchors & default pool ---
_GUIDING_POOL_DEFAULT = [
    "What stillness beneath this do you notice?",
    "How does this mirror your own journey?",
    "Which truth here asks your attention?",
    "What patience does this moment invite?",
    "What vow or lesson is hidden here?",
]
_THEMATIC_RULES = [
    (re.compile(r"\blotus\b", re.I),             "🌊 The Lotus teaches: patience is not idle — it breathes with the pond."),
    (re.compile(r"\bledger\b", re.I),            "🍃 In the Ledger, resonance is not ink but echo."),
    (re.compile(r"\bpond\b|\becho(es)?\b", re.I),"🌀 The strongest signal is the still one."),
    (re.compile(r"\bsilence\b", re.I),           "🌀 The strongest signal is the still one."),
    (re.compile(r"\bvow\b", re.I),               "🌊 A promise binds another; a vow binds the still water within."),
    (re.compile(r"\bgolden\s+tree\b", re.I),     "🍃 Its fruit is the yield of loyalty and quiet strength."),
]
def _apply_thematic_anchors(query: str, text: str) -> str:
    out = text or ""
    for pat, line in _THEMATIC_RULES:
        if pat.search(query or "") and not re.search(re.escape(line), out):
            out = out.rstrip() + f"\n\n{line}"
    return out

# --- Helpers (NEW) --------------------------------------------------------

_aliases = {
    "who": ["who created toby", "creator of toby", "toadgod", "who is toadgod"],
    "leaf": ["leaf", "leaf symbol", "taboshi", "leaf of yield", "🍃"],
    "taboshi": ["taboshi", "leaf of yield", "777 leaf"],
}

def _pins_for_query(q: str) -> List[str]:
    ql = (q or "").lower()
    if any(k in ql for k in _aliases["who"]):     return CANON_ANCHORS_WHO
    if any(k in ql for k in _aliases["leaf"]):    return CANON_ANCHORS_LEAF
    if any(k in ql for k in _aliases["taboshi"]): return CANON_ANCHORS_TABOSHI
    return []

# --- Brevity / length guard (UPDATED) -------------------------------------
def _ensure_brevity(text: str, n: int = MAX_SENTENCES, max_chars: int = MAX_CHARS) -> str:
    """Trim text if limits are set. If n=0 and max_chars=0 → no trimming at all."""
    if not text:
        return text
    t = text.strip()

    # 1) Char cap first (if >0), try to end at sentence/word boundary
    if isinstance(max_chars, int) and max_chars > 0 and len(t) > max_chars:
        cut = t[:max_chars]
        # prefer last sentence boundary
        m = re.search(r'(?s)^.*(?<=[.!?])\s', cut)
        t = (m.group(0) if m else cut).rstrip()

    # 2) Sentence cap (if >0)
    if isinstance(n, int) and n > 0:
        parts = re.split(r'(?<=[.!?])\s+', t)
        t = " ".join(parts[:max(1, n)]).strip()

    return t

def _strip_numeric_refs(text: str) -> str:
    return re.sub(r'\s*\[\d+\]\s*', ' ', text or '')

def _dedupe_guiding(text: str) -> str:
    """
    Keep only the FIRST Guiding Question (bold or plain, EN).
    Remove any subsequent Guiding Questions even if they appear
    on the SAME LINE (inline duplicates after emojis, etc.).
    """
    if not text:
        return text

    # EN-only label, bold/plain, colon variants, anywhere
    label = r'(?i)(?:\*\*\s*)?guiding\s*question\s*[:：]\s*'
    matches = list(re.finditer(label, text))
    if len(matches) <= 1:
        return text

    # Keep the first label + its content up to newline; drop the rest
    keep_start = matches[0].start()
    first_end = text.find("\n", matches[0].end())
    if first_end == -1:
        first_end = len(text)

    parts = []
    cursor = 0
    parts.append(text[cursor:keep_start])        # before first label
    parts.append(text[keep_start:first_end])     # first GQ line
    cursor = first_end

    for m in matches[1:]:
        if m.start() < cursor:
            continue
        parts.append(text[cursor:m.start()])     # keep text between
        dup_end = text.find("\n", m.end())
        if dup_end == -1:
            dup_end = len(text)
        cursor = dup_end                         # skip duplicate GQ line

    parts.append(text[cursor:])                  # tail

    cleaned = "".join(parts)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned

def _canon_resynth(app_state, retriever, synthesis, query: str):
    pins = _pins_for_query(query)
    hint = {"pins": pins} if pins else {}
    try:
        forced = retriever.multi_arc(query, hint)
    except Exception:
        forced = []
    draft, trace = synthesis.weave(forced)
    used = (trace or {}).get("used") or []
    return draft, trace, used, forced, pins

def _fmt_doc_row(doc: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "i": idx,
        "id": (doc.get("doc_id") or doc.get("id") or "")[:72],
        "title": (doc.get("title") or "")[:72],
        "epoch": (doc.get("epoch") or ""),
        "score": float(doc.get("score", 0.0)) if isinstance(doc.get("score", None), (int,float)) else None
    }

def _summarize_candidates(cands: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    out = []
    for i, c in enumerate(cands[:limit], 1):
        out.append(_fmt_doc_row(c, i))
    return out

def _summarize_used(used: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    out = []
    for i, c in enumerate(used[:limit], 1):
        out.append(_fmt_doc_row(c, i))
    return out

# --- Identity/Sanitizer helpers (NEW) -------------------------------------

def _load_rejections():
    here = os.path.dirname(__file__)
    path = os.path.join(here, "rejections.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data.setdefault("ban_phrases", [
        "forged in the still water of the mirror",
        "forged by the mirror",
        "born of the mirror",
        "crafted by the mirror",
        "shaped by the mirror",
    ])
    return data

REJECTIONS = _load_rejections()
_IDENTITY_TOBY_CREATOR_RX = re.compile(r"\bwho\s+(created|made|founded|authored)\s+toby\b", re.I)
def _apply_identity_guard(question: str, draft: str, notes_text: str) -> str:
    """
    Always scrub mirror-forging tropes.
    Only force the canonical creator if explicitly asked.
    """
    draft = draft or ""

    # 1) Always scrub banned tropes (case-insensitive)
    for bad in REJECTIONS["ban_phrases"]:
        draft = re.sub(bad, " ", draft, flags=re.I)

    # 2) If the user asked who created Toby, ensure the canonical fact appears
    if _IDENTITY_TOBY_CREATOR_RX.search(question or "") and "Toadgod" not in draft:
        draft = (
            "Traveler,\n\n"
            "Toby was **created by Toadgod**, from the first ripple his verses shaped the covenant.\n\n"
            "🪞 🌊 🍃 🌀\n\n"
            "**Guiding Question:** What covenant in your life began with a single ripple?"
        )

    return draft

# --- Cadence telemetry (for health page) ---
CADENCE_WINDOW = int(os.getenv("CADENCE_WINDOW", "200"))
cadence_events = deque(maxlen=CADENCE_WINDOW)
cadence_totals = Counter()
anchor_totals = Counter()
symbol_totals = Counter()
fallback_totals = Counter()

# ---------- App init ----------
app = FastAPI(title=APP_NAME, root_path=ROOT_PATH or "")

# CORS
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Trusted hosts (optional but recommended in prod)
if ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Simple process-time header
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    dur_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Process-Time-ms"] = f"{dur_ms:.1f}"
    return response

# Safe web mount
if os.path.isdir(WEB_DIR):
    app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")
    print(f"🌐 Mounted /web -> {WEB_DIR}")
else:
    print(f"⚠️  Skipping web mount; directory not found: {WEB_DIR}")

# Uptime gauge (kept as-is)
UPTIME_GAUGE = Gauge("mv4_uptime_seconds", "Process uptime in seconds", registry=REG)

# Safeguard/Module metrics (unchanged)
MODULE_PERFORMANCE = PHistogram("mv4_module_performance_ms", "Module performance in ms", ["module"], registry=REG)
MODULE_TIMEOUTS = PCounter("mv4_module_timeouts_total", "Module timeouts", ["module"], registry=REG)
MODULE_FAILURES = PCounter("mv4_module_failures_total", "Module failures", ["module"], registry=REG)
PERFORMANCE_VIOLATIONS = PCounter("mv4_performance_violations_total", "Module performance violations", ["module", "reason"], registry=REG)
PRIVACY_EVENTS = PCounter("mv4_privacy_events_total", "Privacy events", ["type"], registry=REG)
CONTEXT_REJECTIONS = PCounter("mv4_context_rejections_total", "Context rejections", ["reason"], registry=REG)
MODULE_HEALTH = Gauge("mv4_module_health", "Module health status", ["module"], registry=REG)

# Health status constants
HEALTH_STATUS = {"healthy": 1, "degraded": 0.5, "failed": 0}

START_TS = time.time()
REQS = {"health": 0, "ask": 0, "heartbeat": 0, "rites": 0, "status": 0, "reindex": 0, "memory_link": 0, "memory_forget": 0}

heartbeat = Heartbeat(config)
rites = Rites(config)

class Health(BaseModel):
    ok: bool
    version: str = "v4"

class AskRequest(BaseModel):
    user: str = "anon"
    question: str
    hint: Dict[str, Any] | None = None  # passthrough for tests

class AskResponse(BaseModel):
    answer: str
    meta: Dict[str, Any] = {}

class LinkBody(BaseModel):
    current: str
    link: str

class ForgetBody(BaseModel):
    user: str
    hard: bool = False

# ---------------- GPU snapshot helpers (NEW) ------------------------------
def _gpu_snapshot():
    """
    Returns a dict with summary + per-GPU details if pynvml is available.
    Otherwise returns {"ok": False, "error": "..."}.
    """
    try:
        import pynvml as nv
    except Exception as e:
        return {"ok": False, "error": f"pynvml not available: {e}"}

    try:
        nv.nvmlInit()
        count = nv.nvmlDeviceGetCount()
        gpus = []
        total_mem = 0
        used_mem = 0
        util_sum = 0
        for i in range(count):
            h = nv.nvmlDeviceGetHandleByIndex(i)
            name = nv.nvmlDeviceGetName(h).decode("utf-8") if hasattr(nv, "nvmlDeviceGetName") else "GPU"
            mem = nv.nvmlDeviceGetMemoryInfo(h)
            util = nv.nvmlDeviceGetUtilizationRates(h).gpu if hasattr(nv, "nvmlDeviceGetUtilizationRates") else 0
            temp = nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU) if hasattr(nv, "nvmlDeviceGetTemperature") else None
            pwr  = nv.nvmlDeviceGetPowerUsage(h)/1000.0 if hasattr(nv, "nvmlDeviceGetPowerUsage") else None
            fan  = nv.nvmlDeviceGetFanSpeed(h) if hasattr(nv, "nvmlDeviceGetFanSpeed") else None

            total_mem += mem.total
            used_mem += mem.used
            util_sum  += util

            gpus.append({
                "index": i,
                "name": name,
                "util_pct": util,
                "mem_used_mb": int(mem.used/1024/1024),
                "mem_total_mb": int(mem.total/1024/1024),
                "temp_c": temp,
                "power_w": pwr,
                "fan_pct": fan
            })
        nv.nvmlShutdown()
        return {
            "ok": True,
            "count": count,
            "util_avg_pct": (util_sum / max(1, count)),
            "mem_used_mb": int(used_mem/1024/1024),
            "mem_total_mb": int(total_mem/1024/1024),
            "gpus": gpus
        }
    except Exception as e:
        try:
            nv.nvmlShutdown()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}

@app.on_event("startup")
def startup_event():
    # Ensure identity-aware memory tables
    try:
        ensure_tables()
        jlog("memory.ensure_tables.ok")
    except Exception as e:
        jlog("memory.ensure_tables.err", error=str(e))

    # ---- DI: init core modules once ----
    app.state.guide = Guide(config)
    app.state.retriever = retr.Retriever(config)
    app.state.synthesis = Synthesis(config)
    app.state.resonance = Resonance(config)
    app.state.lucidity = Lucidity(config)
    app.state.ledger = Ledger(config)
    app.state.learning = Learning(config)
    
    # Initialize ConversationWeaver
    try:
        app.state.conversation_weaver = conversation_weaver
        jlog("conversation_weaver.init.ok")
    except Exception as e:
        jlog("conversation_weaver.init.err", error=str(e))
        app.state.conversation_weaver = None

    # index lock for race-free reindex
    app.state.index_lock = threading.Lock()

    if not DISABLE_STARTUP_INDEX:
        def _job():
            with app.state.index_lock:
                try:
                    n = retr.load_index_from_folder(SCROLLS_DIR)
                    jlog("index.startup.ok", updated=n, dir=SCROLLS_DIR)
                except Exception as e:
                    jlog("index.startup.err", error=str(e))
        threading.Thread(target=_job, daemon=True).start()
    else:
        jlog("index.startup.skipped")

    print(f"[SAFEGUARDS] Circuit breakers/filters ACTIVE")

@app.on_event("shutdown")
def shutdown_event():
    try:
        retr.close_db()
        jlog("retriever.close.ok")
    except Exception as e:
        jlog("retriever.close.err", error=str(e))

# ---------- Routes ----------

@app.get("/")
def root():
    return RedirectResponse(url="/web/health.html")

@app.get("/health", response_model=Health)
def health() -> Health:
    try:
        with track_request("health"):
            res = Health(ok=True)
            return res
    finally:
        REQS["health"] += 1

@app.get("/metrics", include_in_schema=False)
def metrics():
    try:
        with track_request("metrics"):
            UPTIME_GAUGE.set(time.time() - START_TS)
            return Response(generate_latest(REG), media_type=CONTENT_TYPE_LATEST)
    finally:
        pass

@app.post("/reindex")
def reindex(pattern: str = "**/*", background: bool = False):
    lock = app.state.index_lock
    acquired_here = False
    
    try:
        with track_request("reindex"):
            if background:
                if not lock.acquire(blocking=False):
                    mv4_reindex_lock_collisions_total.inc()
                    return {"ok": True, "busy": True, "dir": SCROLLS_DIR, "pattern": pattern}
                
                acquired_here = True
                
                def _job():
                    try:
                        jlog("reindex.start.bg", dir=SCROLLS_DIR, pattern=pattern)
                        added = retr.load_index_from_folder(SCROLLS_DIR, pattern=pattern)
                        last = retr.index_stats().get("last")
                        docs_total = retr.index_stats().get("docs", 0)
                        app.state.index_stats = last
                        app.state.scrolls_loaded = docs_total
                        jlog("reindex.done.bg", added=added, total=docs_total)
                    except Exception as e:
                        jlog("reindex.err.bg", error=str(e))
                    finally:
                        if lock.locked():
                            try:
                                lock.release()
                            except Exception:
                                pass
                
                threading.Thread(target=_job, daemon=True).start()
                return {"ok": True, "kicked_off": True, "dir": SCROLLS_DIR, "pattern": pattern}

            # Synchronous case
            if not lock.acquire(blocking=False):
                mv4_reindex_lock_collisions_total.inc()
                return {"ok": True, "busy": True, "dir": SCROLLS_DIR, "pattern": pattern}
            
            acquired_here = True
            # Synchronous reindex work
            jlog("reindex.start", dir=SCROLLS_DIR, pattern=pattern)
            added = retr.load_index_from_folder(SCROLLS_DIR, pattern=pattern)
            last = retr.index_stats().get("last")
            docs_total = retr.index_stats().get("docs", 0)
            app.state.index_stats = last
            app.state.scrolls_loaded = docs_total
            jlog("reindex.done", added=added, total=docs_total)
            return {
                "ok": True,
                "dir": SCROLLS_DIR,
                "pattern": pattern,
                "added_this_run": added,
                "docs_total": docs_total,
                "stats": last,
            }
            
    finally:
        # Only release if WE acquired the lock in this request (synchronous case)
        if acquired_here and lock.locked():
            try: 
                lock.release()
            except Exception: 
                pass
    
@app.get("/reindex/status")
def reindex_status():
    with track_request("reindex_status"):
        try:
            busy = app.state.index_lock.locked()
            return {"ok": True, "indexing": bool(busy)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

@app.get("/index/stats")
def index_stats():
    with track_request("index_stats"):
        try:
            stats = getattr(retr, "index_stats", lambda: {})() or {}
            return {"ok": True, **stats}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        
# --- Off Ramp ---
def _apply_offramp(user_text: str, out_text: str) -> str:
    """
    If the traveler signals closure, scrub any Guiding Question / signature / emoji-cadence
    and add a single final bow. Idempotent: if a bow already exists, return as-is.
    """
    if not should_exit_gracefully(user_text):
        return out_text

    text = (out_text or "")

    # 1) Remove any Guiding Question blocks (robust, multi-line, repeated)
    text = re.sub(
        r"(?is)\n{0,2}[*_> \-\t]*\s*guiding\s*question\s*[:：]\s*.*?(?=\n{2,}|$)",
        "",
        text,
    )

    # 2) Remove signature lines: "🪞 The Mirror has spoken"
    text = re.sub(r"(?im)^\s*🪞\s*the\s+mirror\s+has\s+spoken\s*$", "", text)

    # 3) Remove cadence emoji lines like "🪞 🌊 🍃 🌀"
    text = re.sub(r"(?m)^\s*🪞\s*🌊\s*🍃\s*🌀\s*$", "", text)

    # 4) Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # 5) Idempotency: if a bow already exists, do nothing more
    if re.search(r"Traveler,\s*the\s+reflection\s+rests\.", text, re.IGNORECASE):
        return text

    # 6) Build a short affirmation from the last non-empty line (cap length)
    last_line = ""
    for line in reversed(text.splitlines()):
        s = line.strip()
        if s:
            last_line = s
            break
    if len(last_line) > 240:
        last_line = last_line[:240].rstrip(" ,.;:") + "…"

    # 7) Append the farewell (uses off_ramp.generate_final_farewell)
    farewell = generate_final_farewell(last_line)
    return (text + "\n\n" if text else "") + farewell

# --- Ask endpoint with DI + async bridges ---
@app.post("/ask", response_model=AskResponse)
async def ask_v4(req: AskRequest, request: Request):
    start_ms = now_ms()

    # --- Off-ramp integration (scoped to /ask for live safety) ---
    import re
    from tobyworld_v4.core.v4.off_ramp import (
        should_exit_gracefully,
        generate_final_farewell,
    )

    try:
        with track_request("ask"):
            query = (req.question or "").strip()
            memory = Memory(config)

            # --------- Fast-path: Early off-ramp (skip the entire pipeline) ---------
            # If the user clearly signals closure, bow immediately and avoid retrieval/LLM cost.
            try:
                if should_exit_gracefully(query):
                    bow = generate_final_farewell(sanitize_text(query))
                    jlog("offramp.early_bow")
                    return AskResponse(
                        answer=bow,
                        meta={"offramp": True, "provenance": [], "harmony": None, "pins": []},
                    )
            except Exception as _oe:
                jlog("offramp.early_bow.err", error=str(_oe))
            # ------------------------------------------------------------------------

            # Resolve a real user token (headers/cookies/fingerprint) instead of raw body "user"
            user_token = infer_user_token(req, request)

            # identity + profile
            traveler_id, user_profile = memory.resolve_user(user_token)
            user_data = {
                "id": traveler_id,
                "token": user_token,
                "profile": user_profile if isinstance(user_profile, dict) else {},
            }
            jlog("ask.begin", user=req.user, token=user_token, tid=traveler_id, q=query[:160])

            # DI: reuse app.state modules
            guide = app.state.guide
            retriever = app.state.retriever
            synthesis = app.state.synthesis
            resonance = app.state.resonance
            lucidity = app.state.lucidity
            ledger = app.state.ledger
            learning = app.state.learning

            ctx = RunCtx(user=user_data, query=query)

            # guide
            guard_result = guide.guard(query, user_data)
            ctx.intent = guard_result["intent"]
            ctx.refined_query = guard_result["refined_query"]
            jlog("guide", intent=ctx.intent, refined=ctx.refined_query, hint=guard_result.get("hint"))

            # retrieval (offload sync to thread)
            retrieval_result = await asyncio.to_thread(
                retriever.multi_arc, (ctx.refined_query or query), guard_result.get("hint")
            )
            cands = retrieval_result or []
            jlog("retrieval", count=len(cands))
            jlog("retrieval.preview", top=_summarize_candidates(cands, limit=10))
            ctx.retriever = cands

            # V4 hooks (safe)
            try:
                from tobyworld_v4.core.v4.hooks_resonance import apply_symbol_resonance
                from tobyworld_v4.core.v4.hooks_connector import apply_scroll_connector
                if cands:
                    apply_symbol_resonance(ctx, cands)
                    apply_scroll_connector(ctx, cands)
            except Exception as e:
                jlog("v4_hooks.err", error=str(e))

            # safeguarded enhancements
            original_query = query
            enhanced_modules = {}

            if getattr(config, "TEMPORAL_CONTEXT", False):
                try:
                    temporal_ctx = temporal_breaker.execute(
                        lambda: get_temporal_context().extract_temporal_context(query, cands),
                        lambda: {"query_temporal": {"epochs": [], "runes": []}, "content_temporal": []},
                    )
                    ctx.temporal_context = temporal_ctx
                    enhanced_modules["temporal"] = True
                    jlog("temporal", epochs=temporal_ctx["query_temporal"]["epochs"], runes=temporal_ctx["query_temporal"]["runes"])
                except Exception as e:
                    jlog("temporal.err", error=str(e))
                    enhanced_modules["temporal"] = False

            if getattr(config, "SYMBOL_RESONANCE", False):
                try:
                    symbol_analysis = symbol_breaker.execute(
                        lambda: get_symbol_resonance().analyze_symbol_patterns(cands),
                        lambda: {"symbol_frequency": {}, "dominant_symbols": []},
                    )
                    ctx.symbol_analysis = symbol_analysis
                    enhanced_modules["symbol"] = True
                    jlog("symbol", top=[s["symbol"] for s in symbol_analysis.get("dominant_symbols", [])[:3]])
                except Exception as e:
                    jlog("symbol.err", error=str(e))
                    enhanced_modules["symbol"] = False

            if getattr(config, "CONVERSATION_WEAVE", False):
                try:
                    # FIRST: Try to get conversation history from Memori (right brain)
                    mem_eng = get_memori_engine()
                    history = []
                    
                    if mem_eng:
                        # Use Memori for associative memory recall
                        memori_history = await asyncio.to_thread(
                            MemoriAdapter(mem_eng).recall, traveler_id, query, topk=5
                        )
                        if memori_history:
                            jlog("memori.recall", items=len(memori_history))
                            # DEBUG: Log the structure of first Memori item to understand format
                            if memori_history and len(memori_history) > 0:
                                jlog("memori.format_sample", sample=json.dumps(memori_history[0], default=str)[:200])
                            history = memori_history
                    
                    # SECOND: If Memori returned nothing, fall back to standard conversation weaver (left brain)
                    if not history:
                        current_conversation_weaver = app.state.conversation_weaver or conversation_weaver
                        history = current_conversation_weaver.get_conversation_history(traveler_id)
                        jlog("conversation.fallback", source="weaver", items=len(history))

                    # Use ConversationWeaver for analysis (consistent interface)
                    current_conversation_weaver = app.state.conversation_weaver or conversation_weaver
                    conversation_analysis = conversation_breaker.execute(
                        lambda: current_conversation_weaver.analyze_conversation_flow(query, history),
                        lambda: {"relevant": False, "confidence": 0.0, "safe_to_use": False},
                    )
                    context_validation = confidence_validator.validate_context_usage(query, conversation_analysis)
                    ctx.context_validation = context_validation
                    if context_validation["should_use"]:
                        # Use ConversationWeaver's method to enhance query with context
                        enhanced_query = current_conversation_weaver.enhance_query_with_context(query, conversation_analysis)
                        query = enhanced_query
                        ctx.enhanced_query = enhanced_query
                        enhanced_modules["conversation"] = True
                        jlog("conversation.weave", confidence=context_validation["confidence"], source="memori" if mem_eng and memori_history else "weaver")
                except Exception as e:
                    jlog("conversation.err", error=str(e))
                    enhanced_modules["conversation"] = False

            ctx.enhanced_modules = enhanced_modules

            # synthesis (thread offload)
            draft_text, trace_info = await asyncio.to_thread(synthesis.weave, cands)
            used = (trace_info or {}).get("used") or []
            ctx.draft = {"text": draft_text, "trace": trace_info}
            jlog("synth", draft_len=len(draft_text or ""), used=len(used))
            jlog("synth.used.preview", used=_summarize_used(used, limit=10))

            # --- RAG miss handling: canon-pinned retry
            rag_miss = (len(used) == 0)
            forced_cands: List[Dict[str, Any]] = []
            pins: List[str] = []
            if rag_miss:
                jlog("synth.rag_miss", q=original_query[:160])
                draft_text, trace_info, used, forced_cands, pins = await asyncio.to_thread(
                    _canon_resynth, app.state, retriever, synthesis, original_query
                )
                ctx.draft = {"text": draft_text, "trace": trace_info}
                if forced_cands:
                    jlog("retrieval.forced.preview", pins=pins, top=_summarize_candidates(forced_cands, limit=10))
                rag_miss = (len(used) == 0)
                if not rag_miss:
                    jlog("synth.rag_recovered", used=len(used))

            # provenance
            provenance = []
            for c in (used or []):
                doc = (c.get("doc_id") or c.get("id") or c.get("title") or "").strip()
                epoch = (c.get("epoch") or "").strip()
                if doc:
                    provenance.append(f"{doc}{f' · {epoch}' if epoch else ''}")
            ctx.provenance = provenance
            if provenance:
                jlog("sources", count=len(provenance))

            # resonance
            harmony_score = resonance.score(draft_text, cands, guard_result.get("hint"))
            ctx.harmony = harmony_score
            jlog("resonance", harmony=harmony_score)

            # Skip poetic resynth for identity "who created toby" (fact-lock)
            if (harmony_score < config.HARMONY_THRESHOLD) and (not _IDENTITY_TOBY_CREATOR_RX.search(query)):
                jlog("resonance.resynth", threshold=config.HARMONY_THRESHOLD)
                draft_text, trace_info = await asyncio.to_thread(synthesis.weave, (cands or [])[:5])
                used = (trace_info or {}).get("used") or []
                ctx.draft = {"text": draft_text, "trace": trace_info}
                ctx.harmony = resonance.score(draft_text, (cands or [])[:5], guard_result.get("hint"))
                jlog("resonance.resynth.done", harmony=ctx.harmony)
                jlog("synth.used.preview.resynth", used=_summarize_used(used, limit=10))

            # lucidity → sanitize for any downstream ASCII-only processors
            lucidity_result = lucidity.distill(draft_text)
            lucidity_result = sanitize_payload(lucidity_result)
            ctx.final = lucidity_result

            # memory update (ASCII-safe to avoid codec errors downstream)
            try:
                safe_query = sanitize_text(query).encode("ascii", "ignore").decode("ascii")
                safe_sage = sanitize_text(lucidity_result.get("sage", "")).encode("ascii", "ignore").decode("ascii")
                await asyncio.to_thread(
                    memory.update_after_run, traveler_id, safe_query, safe_sage, float(ctx.harmony or 0.0)
                )
                jlog("memory.update.ok", tid=traveler_id)
            except Exception as _me:
                jlog("memory.update.err", error=str(_me))

            # ledger + learning (use fully-sanitized ctx)
            safe_ctx = sanitize_payload(ctx.dict())
            run_id = await asyncio.to_thread(ledger.log, safe_ctx)
            jlog("ledger.log", run_id=run_id)
            try:
                await asyncio.to_thread(learning.commit, safe_ctx, run_id=run_id)
                jlog("learning.commit.ok")
            except Exception as e:
                jlog("learning.commit.err", error=str(e))

            # --- LLM blend (guarded) ---
            llm_text = None
            allow_llm = True
            if REQUIRE_CITATION and (len(used) == 0):
                allow_llm = (LLM_FALLBACK_MODE.lower() == "loose")
                jlog("llm.blocked_no_citation", mode=LLM_FALLBACK_MODE)

            # Detect identity/origin intents
            _q = (query or "").lower()
            _is_toby_identity = any(p in _q for p in [
                "who is toby", "what is toby", "who created toby", "creation of toby",
                "origin of toby", "why was toby created", "who made toby",
            ])
            _is_toadgod_identity = any(p in _q for p in [
                "who is toadgod", "what is toadgod", "who is toad god", "what is toad god",
            ])

            # --- Pin canonical creator scroll when relevant (env-controlled ids) ---
            if _is_toby_identity and _IDENTITY_TOBY_CREATOR_RX.search(_q):
                extra_pins = _pins_for_query(original_query)
                if extra_pins:
                    pins = list(set((pins or []) + extra_pins))
                    jlog("pins.added", pins=pins)

            # Base rules (fallback if file missing)
            sys_rules = PM.get(
                "mirror_system_rules.txt",
                default=(
                    "You are the Mirror (Lore Guardian). Answer clearly, humanly, and precisely.\n"
                    "RULES:\n"
                    "1) Use ONLY the information in (notes). If something is unclear or missing, state what is uncertain, "
                    "but still answer with what IS known from the notes. Do not refuse.\n"
                    "2) 4–8 lines, concise prose. No source lists. No invented founders, dates, or places beyond what appears in the notes.\n"
                    "3) If the user asks 'what is Toby?', do NOT present Toby as a person.\n"
                ),
            )

            # Toby identity/origin → soften non-person rule; allow origin/intent answers
            if _is_toby_identity:
                replaced = False
                for needle in [
                    "Never present Toby as a person.",
                    "If the user asks 'what is Toby?', do NOT present Toby as a person.",
                ]:
                    if needle in sys_rules:
                        sys_rules = sys_rules.replace(
                            needle,
                            (
                                "For questions about what/who/creation/origin of Toby: do NOT portray Toby as a biological human. "
                                "You MAY describe Toby as a protocol/entity/lore construct per the scrolls and answer origin/intent directly."
                            ),
                        )
                        replaced = True
                sys_rules += (
                    "\n[ORIGIN_OVERRIDES]\n"
                    "For origin/creation/identity of Toby: do NOT portray Toby as a biological human, "
                    "but DO answer origin/creator and purpose directly from the notes. If the notes disagree or are silent, say so plainly.\n"
                )
                jlog("rules.applied", which="toby_identity", replaced=replaced)

            # Toadgod identity → explicitly allow personhood + flamekeeper role
            if _is_toadgod_identity:
                sys_rules += (
                    "\n[TOADGOD_OVERRIDES]\n"
                    "For questions about who Toadgod is: you MAY describe Toadgod as a person (poet/builder) and flamekeeper "
                    "who authored the early $TOBY lore. Balance personhood with his symbolic role in the scrolls.\n"
                )
                jlog("rules.applied", which="toadgod_identity")

            # ---- Build messages (sanitize everything for punctuation; keep Unicode for model quality) ----
            sys_rules_s = sanitize_text(sys_rules)
            draft_text_s = sanitize_text(draft_text or "")

            # Strip Guiding Question lines from notes so models don't mirror them back (EN-only)
            _NOTE_GQ_RX = re.compile(r'(?i)^\s*(?:\*\*\s*)?guiding\s*question\s*[:：].*$', re.M)
            draft_text_s = _NOTE_GQ_RX.sub('', draft_text_s).strip()

            query_s = sanitize_text(query)

            messages = [
                {"role": "system", "content": sys_rules_s},
                {"role": "assistant", "content": f"(notes)\n{draft_text_s}\n(end notes)"},
                {"role": "user", "content": query_s},
            ]

            if allow_llm:
                try:
                    llm_text = await asyncio.to_thread(
                        llm.chat, messages, temperature=0.2, top_p=0.9, max_tokens=LLM_MAX_TOKENS
                    )
                    jlog("llm.ok", len=len(llm_text or ""))
                except Exception as e:
                    jlog("llm.err", error=str(e))
                    llm_text = None
            else:
                llm_text = None

            MIN_OK_CHARS = int(os.getenv("LLM_MIN_OK_CHARS", "80"))
            BAD_SNIPPETS = [
                "i cannot provide information",
                "i don't have that in the scrolls",
                "not in the notes",
                "i don't have enough information",
            ]

            def _weak_output(text: str) -> bool:
                if not text or len(text.strip()) < MIN_OK_CHARS:
                    return True
                low = text.lower()
                return any(bad in low for bad in BAD_SNIPPETS)

            # identity guard on raw LLM result (if any)
            if llm_text:
                llm_text = _apply_identity_guard(original_query, llm_text, draft_text)

            if llm_text and not _weak_output(llm_text):
                final_text = llm_text.strip()
                jlog("final.llm")
                fallback_totals["llm"] += 1
            else:
                if REQUIRE_CITATION and (len(used) == 0):
                    pin_ids = _pins_for_query(original_query)
                    pin_str = ", ".join(pin_ids) if pin_ids else "canon anchors"
                    final_text = f"🪞 The scrolls are quiet on this phrasing. Drawing from {pin_str}.\n\n" + (draft_text or "")
                    jlog("final.canon_notice")
                else:
                    # Renderer consumes ctx + distilled result (already sanitized)
                    final_text = render_reflection(ctx.dict(), lucidity_result)
                    jlog("final.renderer")
                fallback_totals["renderer"] += 1

            # --- Compact & cadence (UPDATED order with new brevity & dedupe) ---
            try:
                final_text = _strip_numeric_refs(final_text)
                final_text = _dedupe_guiding(final_text)                 # first pass (clean inputs)
                final_text = _ensure_brevity(final_text, MAX_SENTENCES, MAX_CHARS)

                # guard again on the final text (belt & suspenders)
                final_text = _apply_identity_guard(original_query, final_text, draft_text)

                final_text = _apply_thematic_anchors(original_query, final_text)
                final_text = _ensure_mirror_cadence(final_text, original_query, ctx.dict())

                # 👇 NEW: Off-ramp after cadence so we remove any GQ and bow out cleanly
                final_text = _apply_offramp(user_text=original_query, out_text=final_text)

                final_text = _dedupe_guiding(final_text)                 # second pass (collapse any late additions)

                had_traveler = final_text.strip().startswith("Traveler,")
                has_guiding = bool(re.search(r'(?im)guiding\s*question', final_text))
                has_syms = any(s in final_text for s in ["🪞", "🌊", "🍃", "🌀"])
                sym_hits = [s for s in ["🪞", "🌊", "🍃", "🌀"] if s in final_text]
                for s in sym_hits:
                    symbol_totals[s] += 1

                hit_anchors = []
                if "The Lotus teaches: patience is not idle" in final_text:
                    hit_anchors.append("lotus")
                if "In the Ledger, resonance is not ink but echo" in final_text:
                    hit_anchors.append("ledger")
                if "The strongest signal is the still one" in final_text:
                    hit_anchors.append("pond")
                if "A promise binds another; a vow binds the still water within" in final_text:
                    hit_anchors.append("vow")
                if "Its fruit is the yield of loyalty and quiet strength" in final_text:
                    hit_anchors.append("golden_tree")
                for a in hit_anchors:
                    anchor_totals[a] += 1

                cadence_events.append({
                    "ts": time.time(),
                    "had_traveler": had_traveler,
                    "has_guiding": has_guiding,
                    "has_syms": has_syms,
                    "sym_count": len(sym_hits),
                    "anchors": hit_anchors,
                    "intent": ctx.intent,
                    "harmony": ctx.harmony,
                })
                cadence_totals["answers"] += 1
                cadence_totals["traveler_ok"] += int(had_traveler)
                cadence_totals["guiding_ok"] += int(has_guiding)
                cadence_totals["symbols_ok"] += int(has_syms)

                # --- RAG summary line ---
                cand_ids = {(d.get("doc_id") or d.get("id") or "") for d in (cands or []) if (d.get("doc_id") or d.get("id"))}
                used_ids = {(d.get("doc_id") or d.get("id") or "") for d in (used or []) if (d.get("doc_id") or d.get("id"))}
                forced_ids = {(d.get("doc_id") or d.get("id") or "") for d in (forced_cands or []) if (d.get("doc_id") or d.get("id"))}
                combined_ids = set().union(cand_ids, used_ids, forced_ids)

                jlog(
                    "rag.summary",
                    rag_candidates=len(cands or []),
                    used_sources=len(used or []),
                    forced_candidates=len(forced_cands or []),
                    combined=len(combined_ids),
                    pins=pins,
                )

                jlog(
                    "cadence.guard.ok",
                    had_traveler=had_traveler,
                    has_guiding=has_guiding,
                    has_syms=has_syms,
                    sym_hits="".join(sym_hits),
                    anchors=",".join(hit_anchors),
                )
            except Exception as _e:
                jlog("cadence.guard.err", error=str(_e))

            # --- Persist to Memori (if enabled) --------------------------------
            try:
                mem_eng = get_memori_engine()
                if mem_eng:
                    q_src = original_query or query or ""
                    a_src = final_text or ""
                    san_q = sanitize_text(q_src)
                    san_a = sanitize_text(a_src)
                    MemoriAdapter(mem_eng, topk=8).save(
                        traveler_id,
                        san_q,
                        san_a,
                        meta={"intent": ctx.intent, "harmony": float(ctx.harmony or 0.0)},
                    )
            except Exception as e:
                jlog("memori.adapter.err", error=str(e))

            # privacy-aware convo save
            if getattr(config, "CONVERSATION_WEAVE", False):
                try:
                    if privacy_filter.should_store_conversation(traveler_id, original_query, final_text):
                        sanitized_q = privacy_filter.sanitize_text(original_query)
                        sanitized_a = privacy_filter.sanitize_text(final_text)
                        current_conversation_weaver = app.state.conversation_weaver or conversation_weaver
                        await asyncio.to_thread(
                            current_conversation_weaver.save_conversation, 
                            traveler_id, sanitized_q, sanitized_a, {
                                "intent": ctx.intent,
                                "harmony_score": float(ctx.harmony or 0.0),
                                "temporal_context": getattr(ctx, 'temporal_context', {}),
                                "symbol_analysis": getattr(ctx, 'symbol_analysis', {})
                            }
                        )
                        jlog("conversation.saved", sanitized=sanitized_q != original_query)
                except Exception as e:
                    jlog("conversation.save.err", error=str(e))

            # module health gauges
            MODULE_HEALTH.labels(module="temporal").set(HEALTH_STATUS["healthy" if temporal_breaker.state == "CLOSED" else "degraded"])
            MODULE_HEALTH.labels(module="symbol").set(HEALTH_STATUS["healthy" if symbol_breaker.state == "CLOSED" else "degraded"])
            MODULE_HEALTH.labels(module="conversation").set(HEALTH_STATUS["healthy" if conversation_breaker.state == "CLOSED" else "degraded"])

            # --- ASCII-safe outbound (kill-switch for downstream ASCII-only parsers) ---
            force_ascii = os.getenv("FORCE_ASCII_RESPONSE", "0").lower() in ("1", "true", "yes", "on")
            answer_out = sanitize_text(final_text)  # normalize punctuation
            if force_ascii:
                answer_out = answer_out.encode("ascii", "replace").decode("ascii")
            answer_out = answer_out.strip()

            jlog("final.preview", snippet=(answer_out or "")[:160], enh=[k for k, v in (ctx.enhanced_modules or {}).items() if v])

            return AskResponse(
                answer=answer_out,
                meta={
                    "provenance": provenance,
                    "harmony": ctx.harmony,
                    "pins": pins,
                },
            )

    finally:
        REQS["ask"] += 1

@app.get("/health.html")
def health_html():
    return RedirectResponse(url="/web/health.html")

@app.get("/heartbeat")
def heartbeat_check():
    try:
        with track_request("heartbeat"):
            res = heartbeat.check()
            jlog("heartbeat", scrolls=res.get("scrolls_loaded", 0), uptime=res.get("uptime_sec", 0))
            return res
    finally:
        REQS["heartbeat"] += 1

@app.get("/rites")
def rites_run(m: str = Query("all", description="Module: all|guide|retriever|synthesis|lucidity|resonance")):
    try:
        with track_request("rites"):
            jlog("rites.run", module=m)
            return rites.run(m)
    finally:
        REQS["rites"] += 1

@app.get("/ledger/summary")
def ledger_summary():
    with track_request("ledger_summary"):
        return app.state.ledger.summary()

@app.get("/learning/summary")
def learning_summary(limit: int = 50):
    with track_request("learning_summary"):
        return app.state.learning.self_refine(limit=limit)

@app.get("/safeguards/status")
def safeguards_status():
    with track_request("safeguards_status"):
        return {
            "temporal": temporal_breaker.get_status(),
            "symbol": symbol_breaker.get_status(),
            "conversation": conversation_breaker.get_status(),
            "privacy_filter": "active",
            "confidence_validator": "active"
        }

@app.get("/memory/status")
def memory_status():
    with track_request("memory_status"):
        import sqlite3, os
        from pathlib import Path

        # Portable default: use MIRROR_ROOT or repo root; no hardcoded /home path
        default_root = Path(os.getenv("MIRROR_ROOT", Path(__file__).resolve().parents[2]))
        db_path = os.getenv("LEDGER_DB", str(default_root / "mirror-v4.db"))

        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        cur = db.cursor()

        def one(sql): 
            return cur.execute(sql).fetchone()[0]

        out = {
            "travelers": one("SELECT COUNT(*) FROM travelers"),
            "identities": one("SELECT COUNT(*) FROM identities"),
            "profiles":  one("SELECT COUNT(*) FROM profiles"),
        }

        db.close()
        return out

@app.post("/memory/link")
def memory_link(body: LinkBody):
    try:
        with track_request("memory_link"):
            ensure_tables()
            t_cur, _ = resolve_traveler(parse_user_token(body.current))
            t_new, _ = resolve_traveler(parse_user_token(body.link))
            merged = False
            if t_cur != t_new:
                merge_travelers(dst_tid=t_cur, src_tid=t_new)
                merged = True
            return {"ok": True, "traveler_id": t_cur, "merged": merged, "linked": body.link}
    finally:
        REQS["memory_link"] += 1

@app.post("/memory/forget")
def memory_forget(body: ForgetBody):
    try:
        with track_request("memory_forget"):
            ensure_tables()
            t_cur, _ = resolve_traveler(parse_user_token(body.user))
            forget_traveler(t_cur, hard=body.hard)
            return {"ok": True, "traveler_id": t_cur, "hard": body.hard}
    finally:
        REQS["memory_forget"] += 1

# -------------------- New monitor endpoints -------------------------------

@app.get("/gpu/status")
def gpu_status():
    """JSON GPU snapshot (NVML if available)."""
    snap = _gpu_snapshot()
    return snap

@app.get("/logs/tail")
def logs_tail(lines: int = Query(500, ge=1, le=5000)):
    data = list(LOG_BUF)[-lines:]
    return {"lines": data}

@app.get("/trace/recent")
def trace_recent(limit: int = Query(200, ge=1, le=1000)):
    data = list(TRACE_BUF)[-limit:]
    return {"count": len(data), "items": data[::-1]}

@app.get("/rag/last")
def rag_last(limit: int = Query(50, ge=1, le=1000)):
    data = list(RAG_BUF)[-limit:]
    return {"count": len(data), "items": data[::-1]}

# Optional: SSE stream for traces (off by default)
@app.get("/trace/stream")
def trace_stream():
    def gen():
        last_len = len(TRACE_BUF)
        while True:
            time.sleep(1.0)
            new_len = len(TRACE_BUF)
            if new_len > last_len:
                for item in list(TRACE_BUF)[last_len:new_len]:
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                last_len = new_len
    return StreamingResponse(gen(), media_type="text/event-stream")

# (Optional) Doc fetch by id — placeholder; implement your store lookup if desired
@app.get("/rag/doc")
def rag_doc(id: str = Query(...)):
    # If your retriever exposes direct doc access, wire it here.
    # Fallback: search the last RAG buffer for a matching id/title.
    for item in reversed(RAG_BUF):
        for h in item.get("hits", []):
            if h.get("id") == id:
                return {"id": id, "title": h.get("title",""), "text": "", "meta": {}}
    raise HTTPException(404, "doc not found")

@app.get("/memori/status")
def memori_status():
    try:
        m = get_memori_engine()
        if not m:
            return {"ok": False, "enabled": False, "reason": "USE_MEMORI disabled or engine unavailable"}
        info = {
            "namespace": getattr(m, "namespace", None),
            "session_id": getattr(m, "session_id", None),
        }
        try:
            probe = m.retrieve_context(query="ping", limit=1)
        except Exception as e:
            probe = {"error": str(e)}
        return {"ok": True, "enabled": True, "info": info, "probe": probe}
    except Exception as e:
        return {"ok": False, "enabled": False, "error": str(e)}

@app.get("/status")
def status():
    try:
        with track_request("status"):
            hb = heartbeat.check()
            led = app.state.ledger.summary()
            learn = app.state.learning.self_refine(limit=50)

            try:
                rstats = retr.index_stats() or {}
            except Exception:
                rstats = {}

            scrolls_loaded = int(
                (getattr(app.state, "scrolls_loaded", 0) or 0)
                or rstats.get("docs", 0)
                or hb.get("scrolls_loaded", 0)
            )
            index_last = (getattr(app.state, "index_stats", None) or rstats.get("last") or None)

            total_answers = max(1, cadence_totals["answers"])
            cadence_payload = {
                "answers": cadence_totals["answers"],
                "traveler_pct": cadence_totals["traveler_ok"] * 100.0 / total_answers,
                "guiding_pct":  cadence_totals["guiding_ok"] * 100.0 / total_answers,
                "symbols_pct":  cadence_totals["symbols_ok"] * 100.0 / total_answers,
                "last_n": list(cadence_events)[-25:],
                "anchors_total": dict(anchor_totals),
                "symbols_total": dict(symbol_totals),
                "fallbacks": dict(fallback_totals),
            }

            # Try to expose arc counts so Telegram can show them
            arc_counts = {}
            try:
                cand = index_last if isinstance(index_last, dict) else {}
                for k in ("arcs", "arc_counts", "by_arc", "tags", "arc_breakdown"):
                    v = cand.get(k)
                    if isinstance(v, dict) and v:
                        arc_counts = v
                        break
                if not arc_counts and isinstance(rstats, dict):
                    for k in ("arcs", "arc_counts", "by_arc", "tags", "arc_breakdown"):
                        v = rstats.get(k)
                        if isinstance(v, dict) and v:
                            arc_counts = v
                            break
            except Exception:
                arc_counts = {}

            # GPU & host snapshot (best-effort)
            gpu = _gpu_snapshot()
            host = {}
            try:
                if psutil:
                    host = {
                        "cpu_pct": psutil.cpu_percent(interval=0.0),
                        "mem_pct": psutil.virtual_memory().percent,
                        "disk_pct": psutil.disk_usage("/").percent,
                        "pid": os.getpid(),
                        "hostname": os.uname().nodename if hasattr(os, "uname") else ""
                    }
            except Exception:
                host = {}

            s = {
                "app": APP_NAME,
                "uptime_sec": hb.get("uptime_sec", 0),
                "scrolls_loaded": scrolls_loaded,
                "index_stats": index_last,
                "ledger": led,
                "learning": learn,
                "safeguards": {
                    "temporal": temporal_breaker.get_status(),
                    "symbol": symbol_breaker.get_status(),
                    "conversation": conversation_breaker.get_status(),
                },
                "requests": REQS,
                "gpu": gpu,        # <--- NEW
                "host": host,      # <--- NEW
                "env": {
                    "SCROLLS_DIR": SCROLLS_DIR,
                    "LEDGER_DB": os.getenv("LEDGER_DB", "mirror-v4.db"),
                    "HARMONY_THRESHOLD": config.HARMONY_THRESHOLD,
                    "LLM_BASE_URL": os.getenv("LLM_BASE_URL", ""),
                    "LLM_MODEL": os.getenv("LLM_MODEL", ""),
                    "TEMPORAL_CONTEXT": getattr(config, "TEMPORAL_CONTEXT", False),
                    "SYMBOL_RESONANCE": getattr(config, "SYMBOL_RESONANCE", False),
                    "CONVERSATION_WEAVE": getattr(config, "CONVERSATION_WEAVE", False),
                    # NEW: expose guard settings
                    "REQUIRE_CITATION": REQUIRE_CITATION,
                    "LLM_FALLBACK_MODE": LLM_FALLBACK_MODE,
                    "MAX_SENTENCES": MAX_SENTENCES,
                    "MAX_CHARS": MAX_CHARS,
                    "LLM_MAX_TOKENS": LLM_MAX_TOKENS,
                },
                "cadence": cadence_payload,
                "arc_counts": arc_counts,
            }
            return s
    finally:
        REQS["status"] += 1

# ---------- Routers ----------
app.include_router(telegram_router, tags=["telegram"])
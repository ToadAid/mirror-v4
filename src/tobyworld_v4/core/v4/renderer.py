# src/tobyworld_v4/core/v4/renderer.py
from __future__ import annotations
from typing import Dict, Any, List, Iterable
import re
from pathlib import Path

# Heuristic for Chinese
_CN = re.compile(r"[\u4e00-\u9fff]")

# Aggressive “header-ish” detectors
_HEADER_KEYS = (
    r"id|prev_id|next_id|prev_l_id|next_l_id|title|source|series|doc_id"
)
_HEADERish = re.compile(
    rf"""^
        \s*
        (?:
            🪞
            |(?:{_HEADER_KEYS})\s*[:：]   # key: or key： (fullwidth colon)
            |a\s+reflection\s+from\s+the\s+scrolls\b
            |卷轴回响
        )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Lines that clearly look like file refs or internal ids
_PATHISH = re.compile(r"""(^/|\\|\.md\b|^TOBY_[A-Z]+[_\w\-\.]*$)""", re.IGNORECASE)

def _lang_from_ctx(ctx: Dict[str, Any]) -> str:
    try:
        prof = ((ctx.get("user") or {}).get("profile") or {})
        lang = (prof.get("language_pref") or "").upper()
        if lang in ("ZH", "CN", "ZH-CN", "ZH_CN", "ZH-TW", "ZH_TW"):
            return "ZH"
    except Exception:
        pass
    if _CN.search(ctx.get("query") or ""):
        return "ZH"
    return "EN"

def _normalize_id(rid: str) -> str:
    try:
        name = Path(rid).name
        return re.sub(r"\.(md|markdown)$", "", name, flags=re.I)
    except Exception:
        return rid or ""

def _first_meta(ctx: Dict[str, Any]) -> Dict[str, str]:
    rid = title = source = series = ""
    prev_id = next_id = ""
    for ch in (ctx.get("retrieval") or []):
        if isinstance(ch, dict):
            d = ch
        else:
            d = getattr(ch, "model_dump", lambda: {})()
            d = d if isinstance(d, dict) else {}
        rid   = rid   or str(d.get("doc_id") or d.get("id") or "")
        title = title or str(d.get("title") or "")
        series= series or str(d.get("series") or "")
        meta  = d.get("meta") or {}
        if isinstance(meta, dict):
            prev_id = prev_id or str(meta.get("prev_id") or meta.get("prev_L_id") or "")
            next_id = next_id or str(meta.get("next_id") or meta.get("next_L_id") or "")
            source  = source  or str(meta.get("source")  or meta.get("origin") or "")
        if rid and title:
            break
    rid = _normalize_id(rid)
    return {
        "id": rid, "title": title, "series": series,
        "source": source, "prev_id": prev_id, "next_id": next_id
    }

def _header(meta: Dict[str, str], lang: str) -> str:
    if lang == "ZH":
        head = "🪞 卷轴回响"
        lines: List[str] = []
        if meta.get("id"):      lines.append(f"id: {meta['id']}")
        if meta.get("prev_id"): lines.append(f"prev_id: {meta['prev_id']}")
        if meta.get("next_id"): lines.append(f"next_id: {meta['next_id']}")
        if meta.get("title"):   lines.append(f"标题: {meta['title']}")
        if meta.get("source"):  lines.append(f"来源: {meta['source']}")
        return head if not lines else f"{head}\n" + "\n".join(lines)

    head = "🪞 A reflection from the Scrolls"
    bits: List[str] = []
    if meta.get("id"):      bits.append(f"id: {meta['id']}.")
    if meta.get("prev_id"): bits.append(f"prev_id: {meta['prev_id']}.")
    if meta.get("next_id"): bits.append(f"next_id: {meta['next_id']}.")
    if meta.get("title"):   bits.append(f"Title: {meta['title']}.")
    if meta.get("source"):  bits.append(f"Source: {meta['source']}.")
    return head if not bits else f"{head}\n" + " ".join(bits)

def _mantra(lang: str) -> str:
    return (
        "🌊 稳呼吸。🍃 轻聚焦。🌀 看得清。"
        if lang == "ZH" else
        "🌊 Steady breath. 🍃 Gentle focus. 🌀 Clear seeing."
    )

def _strip_headerish_lines(text: str) -> str:
    """Remove header-like / path-like lines from a block of text."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    keep: List[str] = []
    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        low = ln.lower()

        # obvious header-ish
        if _HEADERish.match(ln):
            continue
        # full header names without punctuation
        if low in {
            "a reflection from the scrolls", "卷轴回响",
            "🪞 卷轴回响", "🪞 a reflection from the scrolls"
        }:
            continue
        # bare series/doc names, absolute paths, or md filenames
        if _PATHISH.search(ln):
            continue
        keep.append(ln)
    return "\n".join(keep).strip()

def _split_to_lines(s: str) -> List[str]:
    """Split into short, tidy lines."""
    s = re.sub(r"\n{3,}", "\n\n", s)
    lines = [ln.strip(" •-—·\t") for ln in s.split("\n") if ln.strip()]
    if len(lines) < 3:
        # split by sentence punctuation if too few lines
        parts = re.split(r"(?<=[.!?。！？])\s+", s)
        lines = [p.strip(" •-—·\t") for p in parts if p.strip()]
    # dedupe consecutive
    out: List[str] = []
    last = None
    for ln in lines:
        if ln == last:
            continue
        out.append(ln)
        last = ln
        if len(out) >= 6:
            break
    return out

def _fallback_from_retrieval(ctx: Dict[str, Any]) -> List[str]:
    """If body is too thin after cleaning, build 2–4 lines from retrieved chunks."""
    lines: List[str] = []
    for ch in (ctx.get("retrieval") or [])[:5]:
        txt = ""
        if isinstance(ch, dict):
            txt = str(ch.get("text") or "")
        else:
            d = getattr(ch, "model_dump", lambda: {})()
            if isinstance(d, dict):
                txt = str(d.get("text") or "")
        if not txt:
            continue
        txt = _strip_headerish_lines(txt)
        # take first decent sentence
        parts = re.split(r"(?<=[.!?。！？])\s+", txt)
        for p in parts:
            p = p.strip()
            if 15 <= len(p) <= 200:
                lines.append(p)
                break
        if len(lines) >= 4:
            break
    return lines[:4]

def _clean_guiding_question(gq: str, meta: Dict[str, str], lang: str) -> str:
    gq = (gq or "").strip()
    if gq:
        bad = (
            "reflection from the scrolls" in gq.lower()
            or len(gq) > 160
            or gq.count("?") > 2
        )
        if not bad and gq.endswith(("?", "？")):
            return gq
    title = (meta.get("title") or "").strip()
    if title.endswith(("?", "？")):
        return title
    return ""

def render_reflection(ctx: Dict[str, Any], lucidity_out: Dict[str, Any]) -> str:
    """
    Final wrapper:
      Header (ids/title/source) +
      3–6 short lines from the distilled answer (cleaned) or fallback from retrieval +
      optional guiding question (cleaned) +
      Mantra line
    """
    lang = _lang_from_ctx(ctx)
    meta = _first_meta(ctx)

    body_raw = str(lucidity_out.get("sage") or lucidity_out.get("novice") or "")
    cleaned = _strip_headerish_lines(body_raw)
    body_lines = _split_to_lines(cleaned)

    # Fallback if the LLM returned mostly headers/ids
    if len(body_lines) < 2:
        fb = _fallback_from_retrieval(ctx)
        if fb:
            body_lines = fb

    head = _header(meta, lang)
    tail = _mantra(lang)
    gq = _clean_guiding_question(str(lucidity_out.get("guiding_question") or ""), meta, lang)
    gq_line = f"\n\n**引导之问：**{gq}" if (gq and lang == "ZH") else (f"\n\n**Guiding Question:** {gq}" if gq else "")

    body = "\n".join(body_lines) if body_lines else "…"
    return f"{head}\n\n{body}{gq_line}\n\n{tail}"

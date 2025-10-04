from __future__ import annotations
from typing import List, Dict, Any, Tuple
import re
from .config import config

# Synthesis goals:
# - Build a clean draft from retrieved chunks
# - De-duplicate, trim, and order by relevance
# - Light "cadence" normalization (no extra deps)
# - Return (draft_text, trace)

MAX_SNIPPETS = 6            # cap how many snippets to weave
SNIPPET_MIN_CHARS = 40      # skip ultra-short lines
PARA_MAX_CHARS = 600        # keep paragraphs readable

# Precompiled bits for micro-speed and clarity
_RE_SPACES = re.compile(r"[ \t\u00A0]+")
_RE_MANY_NL = re.compile(r"\n{3,}")
_RE_BULLET = re.compile(r"^(?:[-*\u2022])\s*", flags=re.M)
_RE_PUNCT_SP = re.compile(r"\s+([,.;:!?])")
_RE_TITLE_MD = re.compile(r"^#+\s*(.+?)\s*$")
_RE_INVISIBLES = re.compile(r"[\u200B\u200C\u200D\uFEFF]")  # zero-width + BOM
_RE_SENT_END = re.compile(r"[.!?](?:['”\"])?")  # sentence enders, optionally closing quote

def _clean_text(s: str) -> str:
    s = (s or "")
    s = _RE_INVISIBLES.sub("", s)
    s = s.strip()
    s = _RE_SPACES.sub(" ", s)
    s = _RE_MANY_NL.sub("\n\n", s)
    return s.strip()

def _normalize_cadence(s: str) -> str:
    # Tidy quotes/dashes, unify bullets, trim spaces around punctuation
    s = (s or "")
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    # normalize en dash / spaced hyphens to em-dash style
    s = re.sub(r"\s*[–-]\s*", " — ", s)
    s = re.sub(r"\s+—\s+", " — ", s)
    # unify bullets, but do not convert lines that truly start with an em-dash
    s = _RE_BULLET.sub("• ", s)
    s = _RE_PUNCT_SP.sub(r"\1", s)
    return s

def _dedupe(snippets: List[str]) -> List[str]:
    seen = set(); out: List[str] = []
    for t in snippets:
        key = re.sub(r"\s+", " ", (t or "").strip().strip('"').strip("'")).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out

def _shorten(p: str, max_chars: int) -> str:
    if len(p) <= max_chars:
        return p
    # Prefer the last sentence end before max_chars
    window = p[:max_chars]
    last = -1
    for m in _RE_SENT_END.finditer(window):
        last = m.end()
    if last >= 0 and last >= max_chars * 0.6:  # avoid trimming too early
        return p[:last].rstrip()
    # Otherwise, cut at last whitespace before max_chars if possible
    cut = window.rfind(" ")
    if cut > max_chars * 0.5:
        return p[:cut].rstrip()
    return window.rstrip()

def _best_title(chunks: List[Dict[str, Any]], fallback: str = "A reflection from the Scrolls") -> str:
    for c in chunks:
        # Prefer explicit title metadata if present
        title = (c.get("title") or "").strip()
        if title:
            return title
        text = (c.get("text") or "").strip()
        if text:
            first = text.splitlines()[0].strip()
            md = _RE_TITLE_MD.match(first)
            if md:
                return md.group(1).strip()
    return fallback

def _format_sources(chunks: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for c in chunks[:MAX_SNIPPETS]:
        doc = (c.get("doc_id") or "unknown").strip() or "unknown"
        epoch = (c.get("epoch") or "").strip()
        label = f"- {doc}{(' · ' + epoch) if epoch else ''}"
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out

class Synthesis:
    def __init__(self, cfg=config):
        self.cfg = cfg

    def weave(self, chunks: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """
        Returns:
           draft_text: str  (structured, readable, cadence-friendly)
           trace: {graph_stats, chosen_paths, used, dropped, sources_footnote}
        """
        # 1) sanitize & keep top-N
        ch = [c for c in (chunks or []) if c and (c.get("text") or "").strip()]
        ch = ch[:MAX_SNIPPETS]

        # 2) extract and clean snippets
        snippets: List[str] = []
        used: List[Dict[str, Any]] = []
        dropped: List[str] = []

        for c in ch:
            t = _clean_text(c.get("text", ""))
            if len(t) < SNIPPET_MIN_CHARS:
                dropped.append("SHORT:" + (c.get("doc_id") or "doc"))
                continue
            t = _shorten(t, PARA_MAX_CHARS)
            snippets.append(t)
            used.append(c)

        snippets = _dedupe(snippets)

        # 3) construct sections (cadence-friendly, minimal scaffolding)
        _ = _best_title(used)  # kept in case you want to log it; not rendered
        body_parts: List[str] = []

        if len(used) >= 2:
            body_parts.append("A brief weave from multiple scrolls:")

        body_parts.extend(snippets)

        # 4) cadence normalization
        draft = "\n\n".join(body_parts)
        draft = _normalize_cadence(draft)

        # 5) trace with sources (no in-body footer)
        sources = _format_sources(used)
        trace = {
            "graph_stats": {"nodes": len(used), "dropped": len(dropped)},
            "chosen_paths": [u.get("doc_id") for u in used],
            "used": used,
            "dropped": dropped,
            "sources_footnote": sources,
        }
        return draft, trace

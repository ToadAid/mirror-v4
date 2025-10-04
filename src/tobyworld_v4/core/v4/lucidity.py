from __future__ import annotations
from typing import Dict, Any, List, Tuple
import re
from .config import config

# Lucidity goals
#  - Produce two parallel voices from one draft:
#      • novice: concise, plain-language summary (<= ~240 chars)
#      • sage: mirror cadence, slightly poetic, tidy and warm
#  - guiding_question: short prompt (<= 12 words) to nudge reflection
#  - No external deps

MAX_NOVICE_CHARS = 240
MAX_GQ_WORDS = 12

_SENT_RX = re.compile(
    r"""
    (
      [^.!?。？！\n]+          # sentence body
      (?:[.!?。？！]+|$)       # end mark(s) or end of string
    )
    """,
    re.X | re.U,
)

def _strip_md(s: str) -> str:
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)   # headings
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)       # bold
    s = re.sub(r"\*([^*]+)\*", r"\1", s)           # italics
    s = re.sub(r"`([^`]+)`", r"\1", s)             # code
    s = re.sub(r"^\s*[-*•]\s+", "", s, flags=re.M) # bullets
    return s.strip()

def _first_heading(draft: str) -> str:
    for line in (draft or "").splitlines():
        if line.strip().startswith("#"):
            return re.sub(r"^#+\s*", "", line.strip())
    return ""

def _sentences(s: str) -> List[str]:
    s = _strip_md(s)
    parts = [m.group(1).strip() for m in _SENT_RX.finditer(s)]
    # fallback if regex found nothing
    if not parts:
        parts = [p.strip() for p in re.split(r"[。\n.!?]+", s) if p.strip()]
    return [p for p in parts if p]

def _summarize(s: str, max_chars: int = MAX_NOVICE_CHARS) -> str:
    """
    Take the first sentences until we fit under max_chars.
    """
    out: List[str] = []
    total = 0
    for sent in _sentences(s):
        if not sent:
            continue
        # ensure sentence ends with punctuation
        if not re.search(r"[.!?。？！]$", sent):
            sent = sent + "."
        if total + len(sent) + (1 if out else 0) > max_chars:
            break
        out.append(sent)
        total += len(sent) + (1 if out else 0)
        if total >= max_chars:
            break
    if not out:
        # hard fallback: truncate
        clean = _strip_md(s)
        return (clean[: max_chars - 1] + "…") if len(clean) > max_chars else clean
    return " ".join(out)

def _mirror_tidy(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+—\s+", " — ", s)
    s = re.sub(r"\s+–\s+", " — ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _extract_sources(draft: str) -> List[str]:
    # look for a “Sources consulted” section and bullet lines that follow
    lines = draft.splitlines()
    srcs: List[str] = []
    capturing = False
    for ln in lines:
        t = ln.strip()
        if not capturing and re.search(r"(?i)^(\*\*)?sources consulted(\*\*)?$", t):
            capturing = True
            continue
        if capturing:
            if not t or not re.match(r"^[-*•]\s+", t):
                # end of sources block
                break
            srcs.append(re.sub(r"^[-*•]\s+", "", t))
    return srcs

def _guiding_question(draft: str, title_hint: str = "") -> str:
    # prefer a key word from title or draft
    hint = title_hint or ""
    if not hint:
        m = re.search(r"\b(Taboshi1|Taboshi|PATIENCE|Satoby|Epoch\s*[1-9]|Rune\s*[1-9]|Mirror)\b", draft, flags=re.I)
        hint = m.group(0) if m else "this"
    # craft concise question
    s = f"Which truth about {hint} asks attention?"
    words = s.strip().rstrip("?").split()
    if len(words) > MAX_GQ_WORDS:
        words = words[:MAX_GQ_WORDS]
    out = " ".join(words)
    if not out.endswith("?"):
        out += "?"
    return out

def _sage_voice(draft: str, title: str = "") -> str:
    body = _strip_md(draft)
    core = _summarize(body, max_chars=420)  # a bit longer than novice
    title_line = title or "A reflection from the Mirror"
    sage = (
        f"🪞 {title_line}\n"
        f"{core}\n\n"
        f"🌊 Steady breath. 🍃 Gentle focus. 🌀 Clear seeing."
    )
    return _mirror_tidy(sage)

class Lucidity:
    def __init__(self, cfg):
        self.cfg = cfg

    def distill(self, draft: str, level: str = "auto") -> Dict[str, Any]:
        """
        Input: draft (markdown-ish string)
        Output:
          {
            "novice": str,
            "sage": str,
            "guiding_question": str,
            "sources": list[str]     # extracted if present
          }
        """
        text = (draft or "").strip()
        if not text:
            return {"novice": "", "sage": "", "guiding_question": "", "sources": []}

        title = _first_heading(text)
        novice = _summarize(text, MAX_NOVICE_CHARS)
        sage = _sage_voice(text, title)
        gq = _guiding_question(text, title)
        sources = _extract_sources(text)

        return {
            "novice": _mirror_tidy(novice),
            "sage": _mirror_tidy(sage),
            "guiding_question": gq,
            "sources": sources,
        }

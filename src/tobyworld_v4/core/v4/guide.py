from __future__ import annotations
from typing import Dict, List
import re
from .config import config

# Small, zero-dep guider:
# - intent: ask / define / guide / compare / troubleshoot
# - refine: normalize whitespace, strip chatter, canonicalize key Tobyworld terms
# - curiosity_prompt: short “mirror-style” guiding question (<= 12 words)
# - hint: {keywords, prefer_series, depth} for the retriever

# Canonical replacements (normalize, don't erase)
_CANON = [
    (r"\bleaf of yield\b", "Taboshi"),
    (r"\btaboshi\s*1\b|\btaboshi-?1\b|\btaboshi_one\b", "Taboshi1"),
    (r"\bpatience\b", "PATIENCE"),
    (r"\bepoch\s*([1-9])\b", r"Epoch \1"),
    (r"\bsatoby\b", "Satoby"),
    (r"\btoad\s*aid\b", "ToadAid"),
    (r"\brune\s*([0-9])\b", r"Rune \1"),
    (r"\btoby\s*world\b|\btobyworld\b", "Tobyworld"),
]

# Alias expansions used to augment queries when present
_ALIASES = {
    "tobyworld": ["tobyworld", "toby world", "toby"],
    "taboshi": ["taboshi", "leaf of yield"],
    "taboshi1": ["taboshi1", "taboshi 1", "taboshi-1", "777", "zora"],
    "satoby": ["satoby", "proof of time", "e3", "yield"],
    "epoch": ["epoch", "e1", "e2", "e3", "e4", "e5"],
    "mirror": ["mirror", "cadence", "guiding question"],
    "rune": ["rune 1", "rune 2", "rune 3", "rune 4"],
}

_SERIES_HINTS = {
    # lightweight defaults; we’ll tune with data later
    "define": ["TOBY_QA", "TOBY_F", "TOBY_L"],
    "ask":    ["TOBY_L", "TOBY_QA", "TOBY_QL"],
    "guide":  ["TOBY_F", "TOBY_QA", "TOBY_L"],
    "compare":["TOBY_QA", "TOBY_L"],
    "troubleshoot": ["TOBY_QA", "TOBY_F"],
}

_KEYWORDS_EXTRA = [
    ("taboshi1", ["Taboshi1", "777", "burn", "Zora"]),
    ("taboshi", ["Taboshi", "Leaf of Yield", "Zora"]),
    ("satoby", ["Satoby", "Proof of Time", "E3", "Yield"]),
    ("patience", ["PATIENCE", "Jade Chest", "vault", "drip"]),
    ("epoch", ["Epoch", "E1", "E2", "E3", "E4", "E5"]),
    ("rune", ["Rune 1", "Rune 2", "Rune 3", "Rune 4"]),
    ("mirror", ["Mirror", "cadence", "guiding question"]),
    ("tobyworld", ["Tobyworld", "Toby", "Scrolls", "Mirror"]),
]

_STOP = set("""
a an the and or but if then else of for to in on at with by from about into over
after before between within is are was were be being been do does did doing why how
what when where who whom which that this these those often ever never always it
its their his her your my our as i you we they them me us
""".split())

def _normalize_spaces(s: str) -> str:
    s = re.sub(r"[\s\u00A0]+", " ", s or "")
    return s.strip()

def _canonicalize(s: str) -> str:
    out = s or ""
    # drop obvious chat fillers (but do NOT drop 'tobyworld')
    out = re.sub(r"^(hey|hi|hello|brother)\b[:,]?\s*", "", out, flags=re.I)
    # unify quotes/punctuation
    out = re.sub(r"[“”]", "\"", out)
    out = re.sub(r"[‘’]", "'", out)
    # canonical term replacements
    for pat, rep in _CANON:
        out = re.sub(pat, rep, out, flags=re.I)
    return _normalize_spaces(out)

def _tokens(s: str) -> List[str]:
    toks = re.findall(r"[a-z0-9][a-z0-9\-']*", (s or "").lower())
    return [t for t in toks if t not in _STOP]

def _intent(q: str) -> str:
    s = (q or "").lower()
    if any(k in s for k in [" how do i ", " how to ", "steps", "checklist", "guide "]):
        return "guide"
    if any(k in s for k in ["what is", "define", "definition", "explain ", "meaning of"]):
        return "define"
    if any(k in s for k in [" vs ", " versus ", "difference between", "compare"]):
        return "compare"
    if any(k in s for k in ["error", "issue", "broken", "doesn't work", "not working", "hangs"]):
        return "troubleshoot"
    # default “philosophical ask”
    return "ask"

def _depth_hint(q: str) -> str:
    s = (q or "").lower()
    if any(k in s for k in ["deep", "research", "long answer", "detailed"]):
        return "deep"
    return "normal"

def _series_for_intent(intent: str) -> List[str]:
    return _SERIES_HINTS.get(intent, _SERIES_HINTS["ask"])

def _expand_aliases(refined: str) -> str:
    """Append alias variants for terms detected in refined."""
    low = (refined or "").lower()
    add: List[str] = []
    for key, variants in _ALIASES.items():
        if key in low:
            add.extend(variants)
    if add:
        # avoid duplicates while preserving original refined
        extra = " " + " ".join(sorted(set(add)))
        return refined + extra
    return refined

def _expand_keywords(refined: str) -> List[str]:
    base = set(_tokens(refined))
    # add curated expansions
    for needle, extras in _KEYWORDS_EXTRA:
        if needle in refined.lower():
            base.update([e.lower() for e in extras])
    return sorted(base)[:12]  # keep small & cheap

def _curiosity(refined: str, intent: str) -> str:
    # ≤ 12 words, no punctuation weirdness
    m = re.search(r"(?i)\b(Taboshi1|Taboshi|PATIENCE|Satoby|Epoch\s*[1-9]|Rune\s*[1-9]|Mirror|Tobyworld)\b", refined)
    subj = m.group(0) if m else "this"
    if intent == "guide":
        s = f"What is your next step with {subj}?"
    elif intent == "define":
        s = f"What about {subj} matters right now?"
    elif intent == "compare":
        s = f"What truly differs beneath the names?"
    elif intent == "troubleshoot":
        s = f"What’s the smallest failing part to test?"
    else:
        s = f"Which truth about {subj} asks attention?"
    # trim to ~12 words
    words = s.strip().rstrip("?").split()
    if len(words) > 12:
        words = words[:12]
    out = " ".join(words)
    if not out.endswith("?"):
        out += "?"
    return out

class Guide:
    def __init__(self, cfg=config):
        self.cfg = cfg

    def guard(self, query: str, user_ctx: dict) -> dict:
        """
        Returns:
          {
            "intent": str,
            "refined_query": str,
            "curiosity_prompt": str,
            "notes": list[str],
            "hint": {
               "keywords": list[str],
               "prefer_series": list[str],  # e.g. ["TOBY_L","TOBY_QA"]
               "depth": "normal"|"deep"
            }
          }
        """
        q0 = _normalize_spaces(query)
        q1 = _canonicalize(q0)

        # intent/depth
        intent = _intent(q1)
        depth = _depth_hint(q1)
        prefer_series = _series_for_intent(intent)

        # SAFETY: if refinement got anemic, fall back to original
        refined = q1
        if len(refined) < 4 or refined.replace("?", "").strip() == "":
            refined = q0

        # Alias expansion (keeps original words, just appends variants)
        refined = _expand_aliases(refined)

        # Keywords (expanded + boosted if tobyworld present)
        keywords = _expand_keywords(refined)
        if "tobyworld" in refined.lower() or "toby world" in refined.lower():
            for k in ["tobyworld", "toby world", "toby"]:
                if k not in keywords:
                    keywords.append(k)
            keywords = sorted(set(keywords))[:12]

        curiosity = _curiosity(refined, intent)

        return {
            "intent": intent,
            "refined_query": refined,
            "curiosity_prompt": curiosity,
            "notes": [],
            "hint": {
                "keywords": keywords,
                "prefer_series": prefer_series,
                "depth": depth,
            },
        }

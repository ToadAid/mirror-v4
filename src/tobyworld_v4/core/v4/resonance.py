from __future__ import annotations
from typing import List, Dict, Any, Tuple
import re
import math
from datetime import datetime
from .config import config

# Harmony = weighted blend of:
#  1) Coverage (query/hint keyword presence in draft)
#  2) Cadence (readability + tidy punctuation)
#  3) Source diversity (how many distinct docs/series contributed)
#  4) Consistency (light contradiction heuristic)
#  5) Length fitness (not too short, not rambling)
#
# Range: 0.0 — 1.0

_WORD = re.compile(r"[a-z0-9][a-z0-9\-']*", re.I)
_PUNCT_BAD = re.compile(r"\s+[,.!?;:]\s*")
_MULTI_SPACE = re.compile(r"[ \t\u00A0]{2,}")
_MULTI_NEWLINES = re.compile(r"\n{3,}")

STOP = set("""
a an the and or but if then else of for to in on at with by from about into over
after before between within is are was were be being been do does did doing why how
what when where who whom which that this these those often ever never always it its
their his her your my our as i you we they them me us
""".split())

def _tokens(s: str) -> List[str]:
    return [t.lower() for t in _WORD.findall(s or "") if t.lower() not in STOP]

def _uniq(seq):
    seen=set(); out=[]
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _coverage(draft: str, sources: List[Dict[str,Any]], hint: Dict[str,Any] | None) -> float:
    if not draft:
        return 0.0
    dk = set(_tokens(draft))
    want = set([k.lower() for k in (hint or {}).get("keywords", []) if k])
    if not want:
        return 0.7  # neutral if no hint
    hit = len(dk & want)
    return min(1.0, 0.4 + 0.6 * (hit / max(3, len(want))))  # cap + floor

def _cadence(draft: str) -> float:
    if not draft:
        return 0.0
    s = draft
    # penalties for sloppy punctuation/spacing
    bad = len(_PUNCT_BAD.findall(s))
    multi = len(_MULTI_SPACE.findall(s))
    nn = len(_MULTI_NEWLINES.findall(s))
    penalty = 0.05*bad + 0.03*multi + 0.05*nn
    # sentence estimate
    sentences = max(1, len(re.findall(r"[.!?。？！]", s)))
    avg_len = len(s) / sentences
    # prefer 60–240 chars per sentence window
    fit = 1.0 - min(1.0, abs(avg_len - 150.0) / 150.0) * 0.5
    score = max(0.0, min(1.0, 0.9*fit - penalty))
    return score

def _diversity(sources: List[Dict[str,Any]]) -> float:
    if not sources:
        return 0.5
    docs = _uniq([s.get("doc_id") or "" for s in sources])
    series = _uniq([(s.get("doc_id") or "").split("/")[0][:6] for s in sources])  # rough
    # Reward multiple docs/series up to small cap
    d = min(1.0, len([d for d in docs if d]) / 5.0)
    sdiv = min(1.0, len([x for x in series if x]) / 3.0)
    return 0.5*d + 0.5*sdiv

_NEG = re.compile(r"\b(no|not|never|none|cannot|can't|won't|without)\b", re.I)

def _consistency(draft: str) -> float:
    # super-light contradiction heuristic:
    # too many negations mixed with declaratives yields small penalty
    if not draft:
        return 0.5
    neg = len(_NEG.findall(draft))
    sent = max(1, len(re.findall(r"[.!?。？！]", draft)))
    ratio = neg / sent
    # penalize if > 0.6 negations per sentence
    if ratio <= 0.2:
        return 1.0
    if ratio >= 0.6:
        return 0.6
    # interpolate
    return 1.0 - (ratio - 0.2) * (1.0)  # linear down to ~0.6

def _length_fitness(draft: str) -> float:
    n = len(draft or "")
    if n < 120:
        return 0.6 * (n / 120.0)   # up to 0.6 as it approaches 120
    if n > 2400:
        # decay if too long
        return max(0.6, 1.0 - (n - 2400) / 2400.0)
    # good range
    return 1.0

# -----------------------------
# Story Mode Expansion
# -----------------------------
def _story_expand(draft: str) -> str:
    """Ensure draft is long enough and has a mythic cadence."""
    words = draft.split()
    # Target range 300–500 words
    if len(words) < 280:
        draft += (
            "\n\n→ The tale stretches onward, its roots deep in the covenant, "
            "branches brushing the sky, and whispers guiding the seeker. "
            "Every season adds new rings of meaning, every ripple carries "
            "the lesson that patience is not waiting, but becoming. "
            "And so the myth unfolds, echoing across Tobyworld."
        )
    # Signature closing line
    if "🍃" not in draft:
        draft += "\n\n🍃 Its fruit is the yield of loyalty and quiet strength."
    return draft

class Resonance:
    def __init__(self, cfg=config):
        self.cfg = cfg

    def score(
        self,
        draft: str,
        sources: List[Dict[str,Any]],
        hint: Dict[str,Any] | None = None,
        mode: str = "reflection"
    ) -> float:
        if mode == "story":
            draft = _story_expand(draft)

        cov = _coverage(draft, sources, hint)
        cad = _cadence(draft)
        div = _diversity(sources)
        con = _consistency(draft)
        fit = _length_fitness(draft)

        # weights tuned for readability-first
        w_cov, w_cad, w_div, w_con, w_fit = 0.28, 0.26, 0.18, 0.14, 0.14
        h = w_cov*cov + w_cad*cad + w_div*div + w_con*con + w_fit*fit
        return round(max(0.0, min(1.0, h)), 3)

    def explain(
        self,
        draft: str,
        sources: List[Dict[str,Any]],
        hint: Dict[str,Any] | None = None,
        mode: str = "reflection"
    ) -> Dict[str,float]:
        if mode == "story":
            draft = _story_expand(draft)

        return {
            "coverage": _coverage(draft, sources, hint),
            "cadence": _cadence(draft),
            "diversity": _diversity(sources),
            "consistency": _consistency(draft),
            "length_fitness": _length_fitness(draft),
        }

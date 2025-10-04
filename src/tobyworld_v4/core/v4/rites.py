from __future__ import annotations
from typing import Dict, Any
import time

from .config import config
from .guide import Guide
import tobyworld_v4.core.v4.retriever as retr  # <— module import (avoids circular)
from .synthesis import Synthesis
from .lucidity import Lucidity
from .resonance import Resonance

class Rites:
    """
    Ritual tests to verify the Mirror is alive and whole.
    Each rite runs a quick check across one or more modules
    and returns a dict: {pass: bool, notes: str, duration: float}
    """
    def __init__(self, cfg=config):
        self.cfg = cfg

    def run(self, module_name: str = "all") -> Dict[str, Any]:
        t0 = time.perf_counter()
        ok = True
        notes = []
        try:
            if module_name in ("guide", "all"):
                g = Guide(self.cfg)
                out = g.guard("who is toby", {"id": "selfcheck"})
                if not out or "intent" not in out:
                    ok = False; notes.append("Guide: no intent")
                else:
                    notes.append(f"Guide intent={out['intent']}")

            if module_name in ("retriever", "all"):
                r = retr.Retriever(self.cfg)
                rows = r.multi_arc("toby", {"keywords": ["toby"], "depth": "normal"})
                if not isinstance(rows, list):
                    ok = False; notes.append("Retriever: non-list")
                else:
                    notes.append(f"Retriever k={len(rows)}")

            if module_name in ("synthesis", "all"):
                syn = Synthesis(self.cfg)
                draft, trace = syn.weave([{"text": "Toby is the people."}])
                if not draft:
                    ok = False; notes.append("Synthesis: empty draft")
                else:
                    notes.append(f"Synthesis draft_len={len(draft)}")

            if module_name in ("lucidity", "all"):
                luc = Lucidity(self.cfg)
                out = luc.distill("Toby is the people. $TOBY is Proof of Time.")
                if not out or "sage" not in out:
                    ok = False; notes.append("Lucidity: no sage")
                else:
                    notes.append("Lucidity ok")

            if module_name in ("resonance", "all"):
                res = Resonance(self.cfg)
                score = res.score("Taboshi is scarce and mirrors Satoby.", [])
                if score <= 0.0:
                    ok = False; notes.append("Resonance: zero score")
                else:
                    notes.append(f"Resonance score={score:.2f}")

        except Exception as e:
            ok = False
            notes.append(f"Exception in rite: {e}")

        dt = time.perf_counter() - t0
        return {"pass": ok, "notes": "; ".join(notes), "duration": round(dt, 3)}

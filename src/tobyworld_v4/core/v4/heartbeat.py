from __future__ import annotations
from typing import Dict, Any
import time, random
from .config import config
from . import retriever as retr
from .ledger import Ledger
from .learning import Learning

class Heartbeat:
    """
    Reports the Mirror's pulse: latency, queue depth, harmony avg,
    scroll count, ledger summary, learning signals.
    """

    def __init__(self, cfg=config):
        self.cfg = cfg
        self.start_ts = time.time()
        self.ledger = Ledger(cfg)
        self.learning = Learning(cfg)

    def check(self) -> Dict[str, Any]:
        now = time.time()
        uptime = now - self.start_ts

        # synthetic latency / queue for now (stub until async queue added)
        lat_ms = round(2.0 + random.random() * 3.0, 3)
        queue_depth = 0

        # ledger + learning stats
        ledger_summary = {}
        learning_summary = {}
        try:
            ledger_summary = self.ledger.summary()
        except Exception as e:
            ledger_summary = {"error": str(e)}

        try:
            learning_summary = self.learning.self_refine(limit=20)
        except Exception as e:
            learning_summary = {"error": str(e)}

        scrolls_loaded = len(getattr(retr, "_INDEX", []))

        return {
            "ok": True,
            "uptime_sec": round(uptime, 2),
            "lat_ms": lat_ms,
            "queue_depth": queue_depth,
            "scrolls_loaded": scrolls_loaded,
            "ledger": ledger_summary,
            "learning": learning_summary,
        }

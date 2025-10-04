# hooks_connector.py
from __future__ import annotations
from typing import Any, Dict, List
import os

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "on")

def apply_scroll_connector(ctx: Any, retrieved: List[Dict]) -> None:
    """Attach cross-scroll suggestions onto ctx.you_may_also_want if enabled."""
    if not _env_bool("V4_EXPERIMENTAL", False):
        return
    if not retrieved:
        return
    try:
        from tobyworld_v4.core.v4.scroll_connector import ScrollConnector
        try:
            ctx.you_may_also_want = ScrollConnector().find_connections(retrieved)
        except Exception:
            pass
    except Exception as e:
        print(f"[CONNECTOR] import/suggest error: {e}")

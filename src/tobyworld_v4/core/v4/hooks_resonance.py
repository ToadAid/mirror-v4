# hooks_resonance.py
from __future__ import annotations
from typing import Any, Dict, List
import os

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "on")

def apply_symbol_resonance(ctx: Any, retrieved: List[Dict]) -> None:
    """Attach symbol resonance analysis onto ctx.symbol_resonance if enabled."""
    if not _env_bool("V4_EXPERIMENTAL", False):
        return
    if not _env_bool("SYMBOL_RESONANCE", False):
        return
    if not retrieved:
        return
    try:
        from tobyworld_v4.core.v4.symbol_resonance import SymbolResonator
        try:
            ctx.symbol_resonance = SymbolResonator().analyze_symbols(retrieved)
        except Exception:
            pass
    except Exception as e:
        print(f"[SYMBOL] import/analyze error: {e}")

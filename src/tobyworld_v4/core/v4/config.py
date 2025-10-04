from __future__ import annotations
from dataclasses import dataclass, field
import os


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip().lower()
    return v in ("1", "true", "yes", "on", "y")

def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default

def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None else default


@dataclass
class RetrieverConfig:
    # top-k per depth mode
    K_NORMAL: int = _env_int("RETRIEVER_K_NORMAL", 8)
    K_DEEP: int = _env_int("RETRIEVER_K_DEEP", 16)

    # soft ranking knobs
    SERIES_BOOST: float = _env_float("RETRIEVER_SERIES_BOOST", 0.15)     # per rank
    RECENCY_HALF_LIFE_DAYS: float = _env_float("RETRIEVER_RECENCY_HALF_LIFE_DAYS", 180.0)

    # where to look for scrolls by default (also read by server)
    SCROLLS_DIR: str = _env_str("SCROLLS_DIR", "lore-scrolls")


@dataclass
class Config:
    MEMORY: bool = True  # enable memory module
    # Feature flags
    GUIDE_MODE: bool = _env_bool("GUIDE_MODE", True)
    TEMPORAL_RETRIEVER: bool = _env_bool("TEMPORAL_RETRIEVER", True)
    CAUSAL_SYNTH: bool = _env_bool("CAUSAL_SYNTH", True)
    META_LEARN: bool = _env_bool("META_LEARN", True)     # turned on to use learning table
    HARMONY_SCORE: bool = _env_bool("HARMONY_SCORE", True)
    LUCIDITY_TIERS: bool = _env_bool("LUCIDITY_TIERS", True)
    LEDGER_EMBED: bool = _env_bool("LEDGER_EMBED", True)
    OUROBOROS_FEEDBACK: bool = _env_bool("OUROBOROS_FEEDBACK", False)
    HEARTBEAT: bool = _env_bool("HEARTBEAT", True)
    RITES: bool = _env_bool("RITES", True)

    # Thresholds
    HARMONY_THRESHOLD: float = _env_float("HARMONY_THRESHOLD", 0.7)

    # Paths (mirrors defaults used by ledger/learning; can be absolute)
    LEDGER_DB: str = _env_str("LEDGER_DB", "mirror-v4.db")

    # Subsystems
    RETRIEVER: RetrieverConfig = field(default_factory=RetrieverConfig)


@dataclass
class EnhancedConfig(Config):
    # Temporal Context Settings
    TEMPORAL_CONTEXT: bool = _env_bool("TEMPORAL_CONTEXT", True)
    TEMPORAL_DB_PATH: str = _env_str("TEMPORAL_DB_PATH", "temporal_context.db")
    
    # Symbol Resonance Settings - ENABLE THESE
    SYMBOL_RESONANCE: bool = _env_bool("SYMBOL_RESONANCE", True)  # Changed to True
    SYMBOL_DB_PATH: str = _env_str("SYMBOL_DB_PATH", "symbol_context.db")
    SYMBOL_MAP_PATH: str = _env_str("SYMBOL_MAP_PATH", "symbols/meaning_map.json")
    SYMBOL_MIN_CONFIDENCE: float = _env_float("SYMBOL_MIN_CONFIDENCE", 0.3)
    SYMBOL_MAX_COUNT: int = _env_int("SYMBOL_MAX_COUNT", 5)
    
    # Conversation Weaving Settings - ENABLE THESE
    CONVERSATION_WEAVE: bool = _env_bool("CONVERSATION_WEAVE", True)  # Changed to True
    CONVERSATION_DB_PATH: str = _env_str("CONVERSATION_DB_PATH", "conversation_context.db")
    CONVERSATION_HISTORY_SIZE: int = _env_int("CONV_HISTORY_SIZE", 5)
    CONVERSATION_CONTEXT_WINDOW: int = _env_int("CONVERSATION_CONTEXT_WINDOW", 6)
    CONVERSATION_MIN_RELEVANCE: float = _env_float("CONVERSATION_MIN_RELEVANCE", 0.4)
    
    # Additional recommendation: Lower harmony threshold for better flow
    HARMONY_THRESHOLD: float = _env_float("HARMONY_THRESHOLD", 0.5)  # Lowered from 0.7

# Update global config to use EnhancedConfig
config = EnhancedConfig()
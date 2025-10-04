from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import re
import sqlite3
import threading
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import json

from .config import config

# Epoch and Rune timeline definitions
EPOCH_TIMELINE = {
    "E1": {
        "start": "2024-04-20",
        "end": "2024-08-19",
        "alias": ["epoch1", "e1"]
    },
    "E2": {
        "start": "2024-08-20",
        "end": "2024-12-19",
        "alias": ["epoch2", "e2"]
    },
    "E3": {
        "start": "2024-12-20",
        "end": "2025-04-20",
        "alias": ["epoch3", "e3", "satoby"]
    },
    "E4": {
        "start": "2025-04-21",
        "end": "2025-08-20",
        "alias": ["epoch4", "e4", "ceremony"]
    },
    "E5": {
        "start": "2025-08-21",
        "end": "2025-12-20",
        "alias": ["epoch5", "e5"]
    }
}


RUNE_TIMELINE = {
    "Rune1": {
        "release": "2024-03-17",
        "alias": ["rune1", "rune 1", "toby inception"]
    },
    "Rune2": {
        "release": "2024-11-08",
        "alias": ["rune2", "rune 2", "taboshi", "taboshi1"]
    },
    "Rune3": {
        "release": "2025-07-17",
        "alias": ["rune3", "rune 3", "patience", "$patience"]
    },
    "Rune4": {
        "release": None,
        "alias": ["rune4", "rune 4"]
    }
}


@dataclass
class TemporalConfig:
    db_path: str = "temporal_context.db"
    enabled: bool = True

class TemporalContext:
    def __init__(self, cfg: TemporalConfig):
        self.cfg = cfg
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        """Initialize temporal context database"""
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS epoch_references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    epoch TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(doc_id, epoch)
                );
                
                CREATE TABLE IF NOT EXISTS rune_references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    rune TEXT NOT NULL,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(doc_id, rune)
                );
            """)
            conn.commit()
            conn.close()

    def detect_temporal_references(self, text: str) -> Dict[str, List[str]]:
        """Detect epoch and rune references in text"""
        text_lower = text.lower()
        detected_epochs = []
        detected_runes = []
        
        # Detect epochs
        for epoch, data in EPOCH_TIMELINE.items():
            if any(alias in text_lower for alias in data["alias"]):
                detected_epochs.append(epoch)
        
        # Detect runes
        for rune, data in RUNE_TIMELINE.items():
            if any(alias in text_lower for alias in data["alias"]):
                detected_runes.append(rune)
        
        return {
            "epochs": detected_epochs,
            "runes": detected_runes
        }

    def extract_temporal_context(self, query: str, retrieved_chunks: List[Dict]) -> Dict:
        """Extract temporal context from query and retrieved content"""
        # Detect temporal references in query
        query_temporal = self.detect_temporal_references(query)
        
        # Analyze temporal context in retrieved chunks
        chunk_temporal = []
        for chunk in retrieved_chunks:
            chunk_refs = self.detect_temporal_references(chunk.get("text", ""))
            if chunk_refs["epochs"] or chunk_refs["runes"]:
                chunk_temporal.append({
                    "doc_id": chunk.get("doc_id"),
                    "epochs": chunk_refs["epochs"],
                    "runes": chunk_refs["runes"]
                })
        
        return {
            "query_temporal": query_temporal,
            "content_temporal": chunk_temporal,
            "timeline_consistency": self._check_timeline_consistency(query_temporal, chunk_temporal)
        }

    def _check_timeline_consistency(self, query_temporal: Dict, chunk_temporal: List[Dict]) -> float:
        """Check if temporal references are consistent across query and content"""
        if not query_temporal["epochs"] and not query_temporal["runes"]:
            return 1.0  # No temporal references - neutral consistency
        
        # Simple consistency check - could be enhanced with actual timeline logic
        all_epochs = set(query_temporal["epochs"])
        all_runes = set(query_temporal["runes"])
        
        for chunk in chunk_temporal:
            all_epochs.update(chunk["epochs"])
            all_runes.update(chunk["runes"])
        
        # For now, return 1.0 if we found any temporal context, 0.0 otherwise
        return 1.0 if all_epochs or all_runes else 0.0

    def enhance_retrieval(self, temporal_context: Dict, retrieval_result: List[Dict]) -> List[Dict]:
        """Enhance retrieval based on temporal context"""
        if not temporal_context["query_temporal"]["epochs"] and not temporal_context["query_temporal"]["runes"]:
            return retrieval_result  # No temporal context to enhance with
        
        # Boost chunks that match temporal context
        enhanced_results = []
        for chunk in retrieval_result:
            chunk_score = 1.0
            chunk_epochs = self.detect_temporal_references(chunk.get("text", ""))["epochs"]
            chunk_runes = self.detect_temporal_references(chunk.get("text", ""))["runes"]
            
            # Boost if temporal context matches
            if (any(epoch in chunk_epochs for epoch in temporal_context["query_temporal"]["epochs"]) or
                any(rune in chunk_runes for rune in temporal_context["query_temporal"]["runes"])):
                chunk_score *= 1.3  # 30% boost for temporal relevance
            
            enhanced_results.append({
                **chunk,
                "temporal_score": chunk_score,
                "temporal_epochs": chunk_epochs,
                "temporal_runes": chunk_runes
            })
        
        # Sort by temporal relevance if we have temporal context
        if temporal_context["query_temporal"]["epochs"] or temporal_context["query_temporal"]["runes"]:
            enhanced_results.sort(key=lambda x: x.get("temporal_score", 1.0), reverse=True)
        
        return enhanced_results

# Global instance
_temporal_instance = None

def get_temporal_context() -> TemporalContext:
    """Get or create temporal context instance"""
    global _temporal_instance
    if _temporal_instance is None:
        cfg = TemporalConfig(
            enabled=config.TEMPORAL_CONTEXT if hasattr(config, 'TEMPORAL_CONTEXT') else True,
            db_path=getattr(config, 'TEMPORAL_DB_PATH', 'temporal_context.db')
        )
        _temporal_instance = TemporalContext(cfg)
    return _temporal_instance
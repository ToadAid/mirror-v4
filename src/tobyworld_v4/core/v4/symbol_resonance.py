from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple
import re
import json
from pathlib import Path
import sqlite3
import threading
from dataclasses import dataclass
from collections import defaultdict

from .config import config

# Core Tobyworld symbols and their meanings
BASE_SYMBOL_MEANINGS = {
    "🪞": ["mirror", "reflection", "truth", "awareness", "clarity"],
    "🌊": ["flow", "patience", "current", "time", "yield"],
    "🍃": ["gentleness", "focus", "breath", "stillness", "attention"],
    "🌀": ["cycles", "patterns", "repetition", "seeing", "awareness"],
    "🌿": ["growth", "natural", "organic", "development", "nurture"],
    "🔥": ["transformation", "burn", "energy", "change", "purification"],
    "💧": ["purity", "clarity", "essence", "source", "foundation"],
    "🌙": ["cycles", "rhythms", "phases", "time", "reflection"],
    "⭐": ["guidance", "north star", "direction", "purpose", "meaning"],
    "🕸️": ["connections", "network", "relationships", "web", "system"],
    "🗝️": ["access", "understanding", "key", "insight", "revelation"],
    "🏛️": ["foundation", "structure", "governance", "order", "system"],
    "🌱": ["beginnings", "potential", "seed", "growth", "emergence"],
    "⚖️": ["balance", "justice", "equilibrium", "fairness", "measure"],
    "🔮": ["vision", "future", "potential", "foresight", "possibility"]
}

@dataclass
class SymbolConfig:
    enabled: bool = True
    db_path: str = "symbol_context.db"
    min_confidence: float = 0.3
    max_symbols: int = 5

class SymbolResonance:
    def __init__(self, cfg: SymbolConfig):
        self.cfg = cfg
        self.symbol_meanings = self._load_symbol_meanings()
        self._lock = threading.RLock()
        self._init_db()

    def _load_symbol_meanings(self) -> Dict[str, List[str]]:
        """Load symbol meanings from file or use defaults"""
        try:
            if hasattr(config, 'SYMBOL_MAP_PATH'):
                map_path = Path(config.SYMBOL_MAP_PATH)
                if map_path.exists():
                    with open(map_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
        except Exception:
            pass
        return BASE_SYMBOL_MEANINGS

    def _init_db(self):
        """Initialize symbol resonance database"""
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS symbol_occurrences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    context TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS symbol_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol_a TEXT NOT NULL,
                    symbol_b TEXT NOT NULL,
                    cooccurrence_count INTEGER DEFAULT 0,
                    strength REAL DEFAULT 0.0,
                    UNIQUE(symbol_a, symbol_b)
                );
            """)
            conn.commit()
            conn.close()

    def detect_symbols(self, text: str) -> Dict[str, int]:
        """Detect symbols in text and return frequency"""
        symbol_pattern = re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]')
        symbols = symbol_pattern.findall(text)
        
        frequency = defaultdict(int)
        for symbol in symbols:
            frequency[symbol] += 1
            
        return dict(frequency)

    def analyze_symbol_patterns(self, retrieved_chunks: List[Dict]) -> Dict:
        """Analyze symbol patterns across retrieved content"""
        all_symbols = defaultdict(int)
        symbol_contexts = defaultdict(list)
        doc_symbols = defaultdict(dict)
        
        for chunk in retrieved_chunks:
            text = chunk.get("text", "")
            doc_id = chunk.get("doc_id", "unknown")
            symbols = self.detect_symbols(text)
            
            for symbol, count in symbols.items():
                all_symbols[symbol] += count
                doc_symbols[doc_id][symbol] = doc_symbols[doc_id].get(symbol, 0) + count
                
                # Store context for meaningful symbols
                if symbol in self.symbol_meanings:
                    # Extract context around symbol (simplified)
                    context = self._extract_symbol_context(text, symbol)
                    symbol_contexts[symbol].append({
                        "doc_id": doc_id,
                        "context": context,
                        "count": count
                    })
        
        return {
            "symbol_frequency": dict(all_symbols),
            "symbol_contexts": dict(symbol_contexts),
            "document_symbols": dict(doc_symbols),
            "dominant_symbols": self._find_dominant_symbols(all_symbols)
        }

    def _extract_symbol_context(self, text: str, symbol: str, window: int = 100) -> str:
        """Extract context around a symbol occurrence"""
        positions = [m.start() for m in re.finditer(re.escape(symbol), text)]
        if not positions:
            return ""
        
        # Get context around first occurrence
        pos = positions[0]
        start = max(0, pos - window)
        end = min(len(text), pos + len(symbol) + window)
        
        context = text[start:end]
        # Clean up context
        context = re.sub(r'\s+', ' ', context).strip()
        return context

    def _find_dominant_symbols(self, symbol_freq: Dict[str, int]) -> List[Dict]:
        """Find the most significant symbols based on frequency and meaning"""
        if not symbol_freq:
            return []
            
        # Calculate significance (frequency weighted by meaning importance)
        significant_symbols = []
        for symbol, freq in symbol_freq.items():
            if symbol in self.symbol_meanings:
                # Base significance on frequency and meaning depth
                significance = freq * (1 + len(self.symbol_meanings[symbol]) * 0.1)
                significant_symbols.append({
                    "symbol": symbol,
                    "frequency": freq,
                    "significance": round(significance, 2),
                    "meanings": self.symbol_meanings.get(symbol, [])
                })
        
        # Sort by significance and limit
        significant_symbols.sort(key=lambda x: x["significance"], reverse=True)
        return significant_symbols[:self.cfg.max_symbols]

    def generate_symbol_insights(self, symbol_analysis: Dict) -> List[str]:
        """Generate insightful observations about symbol patterns"""
        insights = []
        dominant_symbols = symbol_analysis.get("dominant_symbols", [])
        
        if not dominant_symbols:
            return ["No significant symbolic patterns detected."]
        
        # Generate insights based on dominant symbols
        for symbol_data in dominant_symbols[:3]:  # Top 3 symbols
            symbol = symbol_data["symbol"]
            freq = symbol_data["frequency"]
            meanings = symbol_data["meanings"]
            
            if freq > 1:
                insight = f"The {symbol} symbol appears {freq} times, suggesting themes of {', '.join(meanings[:2])}."
            else:
                insight = f"The {symbol} symbol appears, touching on {meanings[0]}."
            
            insights.append(insight)
        
        # Add insight about symbol relationships if multiple symbols
        if len(dominant_symbols) > 1:
            symbol_names = [s["symbol"] for s in dominant_symbols[:2]]
            insights.append(f"Symbols {' and '.join(symbol_names)} appear together, suggesting interconnected themes.")
        
        return insights

    def enhance_response_with_symbols(self, response: str, symbol_analysis: Dict) -> str:
        """Enhance response with symbolic awareness"""
        dominant_symbols = symbol_analysis.get("dominant_symbols", [])
        
        if not dominant_symbols or len(response) > 1000:
            return response  # Don't enhance very long responses
            
        # Add symbolic insight footer if appropriate
        insights = self.generate_symbol_insights(symbol_analysis)
        if insights and len(response) + len("\n\n".join(insights)) < 1500:
            insight_text = "\n\n".join(insights)
            return f"{response}\n\n**Symbolic Resonance**\n{insight_text}"
        
        return response

# Global instance
_symbol_instance = None

def get_symbol_resonance() -> SymbolResonance:
    """Get or create symbol resonance instance"""
    global _symbol_instance
    if _symbol_instance is None:
        cfg = SymbolConfig(
            enabled=config.SYMBOL_RESONANCE if hasattr(config, 'SYMBOL_RESONANCE') else False,
            db_path=getattr(config, 'SYMBOL_DB_PATH', 'symbol_context.db'),
            min_confidence=getattr(config, 'SYMBOL_MIN_CONFIDENCE', 0.3),
            max_symbols=getattr(config, 'SYMBOL_MAX_COUNT', 5)
        )
        _symbol_instance = SymbolResonance(cfg)
    return _symbol_instance
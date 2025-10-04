from __future__ import annotations
from typing import Dict, List, Optional, Deque, Tuple
import json
import sqlite3
import threading
from dataclasses import dataclass
from collections import deque, defaultdict
import re
import time
from datetime import datetime, timedelta

from .config import config

@dataclass
class ConversationConfig:
    enabled: bool = True
    db_path: str = "conversation_context.db"
    max_history_size: int = 5
    max_context_window: int = 6  # hours
    min_relevance_score: float = 0.4
    
    # Tobyworld Integration
    tobyworld_symbols: List[str] = None
    symbol_weights: Dict[str, float] = None
    
    def __post_init__(self):
        if self.tobyworld_symbols is None:
            self.tobyworld_symbols = [
                "mirror", "pond", "flame", "vow", "patience", "epoch", "rune",
                "toadgod", "toby", "taboshi", "bushido", "stillness", "wave",
                "spiral", "leaf", "guardian", "traveler", "covenant", "distribution",
                "proof of time", "jade chest", "seven reeds", "first flame"
            ]
        
        if self.symbol_weights is None:
            self.symbol_weights = {
                "mirror": 2.0, "vow": 1.8, "flame": 1.5, "pond": 1.7,
                "patience": 2.0, "toadgod": 1.9, "toby": 1.6, "bushido": 1.4
            }

class ConversationWeaver:
    def __init__(self, cfg: ConversationConfig):
        self.cfg = cfg
        self._lock = threading.RLock()
        self._memory_cache: Dict[str, Deque[Dict]] = defaultdict(lambda: deque(maxlen=cfg.max_history_size))
        self._init_db()

    def _init_db(self):
        """Initialize conversation database"""
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    traveler_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    response TEXT NOT NULL,
                    intent TEXT,
                    harmony_score REAL,
                    temporal_context TEXT,
                    symbol_analysis TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP GENERATED ALWAYS AS (
                        datetime(created_at, '+' || (6 * 60) || ' minutes')
                    ) VIRTUAL
                );
                
                CREATE INDEX IF NOT EXISTS idx_conversation_traveler ON conversation_history(traveler_id);
                CREATE INDEX IF NOT EXISTS idx_conversation_expires ON conversation_history(expires_at);
                
                CREATE TABLE IF NOT EXISTS conversation_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    traveler_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    strength REAL DEFAULT 1.0,
                    last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(traveler_id, topic)
                );

                CREATE TABLE IF NOT EXISTS symbol_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    traveler_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 1,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(traveler_id, symbol)
                );
            """)
            conn.commit()
            conn.close()

    def _clean_old_conversations(self):
        """Clean up expired conversations"""
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            conn.execute("DELETE FROM conversation_history WHERE expires_at < CURRENT_TIMESTAMP")
            conn.commit()
            conn.close()

    def get_conversation_history(self, traveler_id: str) -> List[Dict]:
        """Get conversation history for a traveler"""
        self._clean_old_conversations()
        
        # Try cache first
        if traveler_id in self._memory_cache and self._memory_cache[traveler_id]:
            return list(self._memory_cache[traveler_id])
        
        # Fallback to database
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            cursor = conn.execute(
                "SELECT query, response, intent, harmony_score, temporal_context, symbol_analysis, created_at "
                "FROM conversation_history WHERE traveler_id = ? ORDER BY created_at DESC LIMIT ?",
                (traveler_id, self.cfg.max_history_size)
            )
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    "query": row[0],
                    "response": row[1],
                    "intent": row[2],
                    "harmony_score": row[3],
                    "temporal_context": json.loads(row[4]) if row[4] else {},
                    "symbol_analysis": json.loads(row[5]) if row[5] else {},
                    "timestamp": row[6]
                })
            
            conn.close()
            
            # Update cache
            self._memory_cache[traveler_id] = deque(history, maxlen=self.cfg.max_history_size)
            return history

    def save_conversation(self, traveler_id: str, query: str, response: str, 
                         ctx: Optional[Dict] = None) -> None:
        """Save a conversation turn to history"""
        if not traveler_id or not query or not response:
            return
            
        ctx = ctx or {}
        
        # Extract and track Tobyworld symbols
        symbol_analysis = self.analyze_tobyworld_symbols(query + " " + response)
        ctx["symbol_analysis"] = symbol_analysis
        
        # Update symbol usage tracking
        self._update_symbol_usage(traveler_id, symbol_analysis.get("symbols_found", []))
        
        with self._lock:
            # Save to database
            conn = sqlite3.connect(self.cfg.db_path)
            conn.execute(
                "INSERT INTO conversation_history (traveler_id, query, response, intent, harmony_score, temporal_context, symbol_analysis) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    traveler_id,
                    query[:1000],  # Limit length
                    response[:2000],
                    ctx.get("intent"),
                    ctx.get("harmony_score", self._calculate_harmony_score(response)),
                    json.dumps(ctx.get("temporal_context", {})),
                    json.dumps(symbol_analysis)
                )
            )
            conn.commit()
            conn.close()
            
            # Update cache
            history_item = {
                "query": query,
                "response": response,
                "intent": ctx.get("intent"),
                "harmony_score": ctx.get("harmony_score"),
                "symbol_analysis": symbol_analysis,
                "timestamp": datetime.now().isoformat()
            }
            
            if traveler_id not in self._memory_cache:
                self._memory_cache[traveler_id] = deque(maxlen=self.cfg.max_history_size)
            
            self._memory_cache[traveler_id].append(history_item)

    def extract_topics(self, text: str) -> List[str]:
        """Extract key topics from text"""
        # Simple topic extraction - can be enhanced with NLP later
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        stop_words = {'what', 'when', 'where', 'who', 'which', 'that', 'this', 'with', 'about', 'from'}
        
        topics = []
        for word in words:
            if (word not in stop_words and 
                not word.isdigit() and 
                len(word) > 3 and 
                word not in topics):
                topics.append(word)
                
        return topics[:5]  # Limit to top 5 topics

    def extract_tobyworld_topics(self, text: str) -> List[Tuple[str, float]]:
        """Extract and weight Tobyworld-specific topics"""
        text_lower = text.lower()
        symbols_found = []
        
        for symbol in self.cfg.tobyworld_symbols:
            if symbol in text_lower:
                weight = self.cfg.symbol_weights.get(symbol, 1.0)
                
                # Boost weight for multiple occurrences
                count = text_lower.count(symbol)
                if count > 1:
                    weight *= min(1.0 + (count * 0.2), 2.0)  # Cap at 2.0
                
                symbols_found.append((symbol, weight))
        
        return sorted(symbols_found, key=lambda x: x[1], reverse=True)

    def analyze_tobyworld_symbols(self, text: str) -> Dict:
        """Analyze Tobyworld symbol usage in text"""
        tobyworld_topics = self.extract_tobyworld_topics(text)
        emoji_pattern = re.compile(r'[🪞🌊🍃🌀🐸]')
        emojis_found = emoji_pattern.findall(text)
        
        return {
            "symbols_found": [topic[0] for topic in tobyworld_topics],
            "symbol_weights": dict(tobyworld_topics),
            "emoji_usage": emojis_found,
            "tobyworld_relevance": sum(weight for _, weight in tobyworld_topics),
            "is_lore_heavy": len(tobyworld_topics) >= 2
        }

    def _calculate_harmony_score(self, response: str) -> float:
        """Calculate how well the response harmonizes with Tobyworld themes"""
        analysis = self.analyze_tobyworld_symbols(response)
        base_score = min(analysis["tobyworld_relevance"] / 5.0, 1.0)
        
        # Bonus for emoji usage (part of Mirror AI style)
        emoji_bonus = min(len(analysis["emoji_usage"]) * 0.1, 0.3)
        
        # Bonus for lore-heavy responses
        lore_bonus = 0.2 if analysis["is_lore_heavy"] else 0.0
        
        return min(base_score + emoji_bonus + lore_bonus, 1.0)

    def _update_symbol_usage(self, traveler_id: str, symbols: List[str]):
        """Update symbol usage tracking for personalization"""
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            for symbol in symbols:
                conn.execute(
                    "INSERT OR REPLACE INTO symbol_usage (traveler_id, symbol, usage_count, last_used) "
                    "VALUES (?, ?, COALESCE((SELECT usage_count FROM symbol_usage WHERE traveler_id = ? AND symbol = ?), 0) + 1, CURRENT_TIMESTAMP)",
                    (traveler_id, symbol, traveler_id, symbol)
                )
            conn.commit()
            conn.close()

    def get_traveler_symbol_profile(self, traveler_id: str) -> Dict[str, int]:
        """Get a traveler's most used Tobyworld symbols"""
        with self._lock:
            conn = sqlite3.connect(self.cfg.db_path)
            cursor = conn.execute(
                "SELECT symbol, usage_count FROM symbol_usage WHERE traveler_id = ? ORDER BY usage_count DESC LIMIT 10",
                (traveler_id,)
            )
            profile = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()
            return profile

    def analyze_conversation_flow(self, current_query: str, history: List[Dict]) -> Dict:
        """Analyze conversation flow and context"""
        if not history:
            return {"relevant": False, "context_summary": "", "topics": []}
        
        current_topics = self.extract_topics(current_query)
        current_tobyworld = self.extract_tobyworld_topics(current_query)
        historical_context = []
        relevant_history = []
        
        # Analyze each historical turn for relevance
        for turn in history[-3:]:  # Last 3 turns
            historical_topics = self.extract_topics(turn["query"] + " " + turn["response"])
            historical_tobyworld = self.extract_tobyworld_topics(turn["query"] + " " + turn["response"])
            
            # Calculate topic overlap
            topic_overlap = len(set(current_topics) & set(historical_topics))
            symbol_overlap = len(set([t[0] for t in current_tobyworld]) & 
                               set([t[0] for t in historical_tobyworld]))
            
            relevance_score = (topic_overlap * 0.3) + (symbol_overlap * 0.7)
            
            if relevance_score >= self.cfg.min_relevance_score:
                relevant_history.append({
                    "turn": turn,
                    "relevance_score": relevance_score,
                    "topics": historical_topics,
                    "tobyworld_symbols": historical_tobyworld
                })
                historical_context.append(f"Previously: {turn['query'][:100]}...")
        
        # Build context summary
        context_summary = ""
        if historical_context:
            context_summary = " | ".join(historical_context[-2:])  # Last 2 relevant turns
        
        return {
            "relevant": len(relevant_history) > 0,
            "context_summary": context_summary,
            "topics": current_topics,
            "tobyworld_symbols": current_tobyworld,
            "relevant_history": relevant_history,
            "suggested_intent": self._suggest_intent(current_query, current_tobyworld)
        }

    def _suggest_intent(self, query: str, tobyworld_symbols: List[Tuple[str, float]]) -> str:
        """Suggest intent based on query and Tobyworld symbols"""
        query_lower = query.lower()
        
        # Intent mapping based on common patterns
        if any(word in query_lower for word in ["what", "meaning", "significance"]):
            return "seek_understanding"
        elif any(word in query_lower for word in ["how", "guide", "help"]):
            return "seek_guidance" 
        elif any(word in query_lower for word in ["why", "important", "matter"]):
            return "seek_purpose"
        elif any(word in query_lower for word in ["list", "three", "lessons"]):
            return "seek_teaching"
        elif tobyworld_symbols:
            return "lore_exploration"
        else:
            return "general_inquiry"

    def get_context_for_prompt(self, traveler_id: str, current_query: str) -> Dict:
        """Get comprehensive context for prompt generation"""
        history = self.get_conversation_history(traveler_id)
        flow_analysis = self.analyze_conversation_flow(current_query, history)
        symbol_profile = self.get_traveler_symbol_profile(traveler_id)
        
        return {
            "traveler_id": traveler_id,
            "current_query": current_query,
            "conversation_history": history,
            "flow_analysis": flow_analysis,
            "symbol_profile": symbol_profile,
            "is_continuation": flow_analysis["relevant"],
            "preferred_symbols": list(symbol_profile.keys())[:3]  # Top 3 symbols
        }

    # =============================================================================
    # NEW METHODS ADDED FOR SERVER COMPATIBILITY
    # =============================================================================

    def weave_context_into_query(self, query: str, conversation_analysis: Dict) -> str:
        """Weave conversation context into the query - enhanced version"""
        if not conversation_analysis.get("relevant"):
            return query
        
        context_summary = conversation_analysis.get("context_summary", "")
        if context_summary:
            return f"{query} [Context: {context_summary}]"
        return query

    def enhance_query_with_context(self, query: str, conversation_analysis: Dict) -> str:
        """Alias for weave_context_into_query for compatibility"""
        return self.weave_context_into_query(query, conversation_analysis)

# =============================================================================
# GLOBAL INSTANCE AND GETTER FUNCTION
# =============================================================================

# Global instance
conversation_weaver = ConversationWeaver(ConversationConfig())

def get_conversation_weaver() -> ConversationWeaver:
    """Get the global ConversationWeaver instance"""
    return conversation_weaver
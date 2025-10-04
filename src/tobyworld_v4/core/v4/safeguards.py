from __future__ import annotations
from typing import Dict, List, Optional, Callable, Any
import time
import re
from dataclasses import dataclass
import asyncio
from functools import wraps
import threading
import logging

from .config import config

# Import metrics - assuming they're defined in your metrics module
try:
    from .metrics import (
        MODULE_FAILURES, MODULE_PERFORMANCE, MODULE_TIMEOUTS,
        PERFORMANCE_VIOLATIONS, PRIVACY_EVENTS, CONTEXT_REJECTIONS
    )
except ImportError:
    # Fallback dummy metrics for development
    class DummyMetric:
        def labels(self, **kwargs): return self
        def inc(self): pass
        def observe(self, value): pass
    
    MODULE_FAILURES = MODULE_PERFORMANCE = MODULE_TIMEOUTS = DummyMetric()
    PERFORMANCE_VIOLATIONS = PRIVACY_EVENTS = CONTEXT_REJECTIONS = DummyMetric()

logger = logging.getLogger(__name__)

# ==================== CIRCUIT BREAKER SYSTEM ====================

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    recovery_timeout: int = 300  # seconds
    half_open_max_attempts: int = 2

class CircuitBreaker:
    def __init__(self, name: str, cfg: CircuitBreakerConfig):
        self.name = name
        self.cfg = cfg
        self.failures = 0
        self.last_failure_time = 0
        self.half_open_attempts = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.RLock()

    def execute(self, operation: Callable[[], Any], fallback: Callable[[], Any]) -> Any:
        with self._lock:
            current_state = self.state

            if current_state == "OPEN":
                if time.time() - self.last_failure_time > self.cfg.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.half_open_attempts = 0
                    current_state = "HALF_OPEN"
                else:
                    return fallback()

            try:
                result = operation()

                if current_state == "HALF_OPEN":
                    self.half_open_attempts += 1
                    if self.half_open_attempts >= self.cfg.half_open_max_attempts:
                        self.state = "CLOSED"
                        self.failures = 0
                        self.half_open_attempts = 0

                return result

            except Exception as e:
                with self._lock:
                    self.failures += 1
                    self.last_failure_time = time.time()

                    if self.failures >= self.cfg.failure_threshold:
                        self.state = "OPEN"

                    MODULE_FAILURES.labels(module=self.name).inc()
                    logger.warning(f"Circuit breaker {self.name} caught exception: {e}")

                return fallback()

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self.failures,
            "last_failure": self.last_failure_time,
            "half_open_attempts": self.half_open_attempts
        }

# ==================== PRIVACY FILTER SYSTEM ====================

class PrivacyFilter:
    def __init__(self):
        self.sensitive_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b',
            r'\b\d{16}\b',
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            r'\b\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        ]
        self.compiled_patterns = [re.compile(pattern) for pattern in self.sensitive_patterns]

    def _is_opt_out_user(self, traveler_id: str) -> bool:
        return False

    def sanitize_text(self, text: str) -> str:
        if not text:
            return text

        sanitized = text
        for pattern in self.compiled_patterns:
            sanitized = pattern.sub('[REDACTED]', sanitized)

        sanitized = self._sanitize_tobyworld_specific(sanitized)

        if sanitized != text:
            PRIVACY_EVENTS.labels(type="text_sanitization").inc()

        return sanitized

    def _sanitize_tobyworld_specific(self, text: str) -> str:
        return text

    def should_store_conversation(self, traveler_id: str, query: str, response: str) -> bool:
        if len(query.strip()) < 3 or query.strip() in ['?', '??', '???', '!', '!!']:
            PRIVACY_EVENTS.labels(type="short_query_rejection").inc()
            return False

        if self._contains_sensitive_info(response):
            PRIVACY_EVENTS.labels(type="sensitive_content_rejection").inc()
            return False

        if self._is_opt_out_user(traveler_id):
            PRIVACY_EVENTS.labels(type="opt_out_rejection").inc()
            return False

        return True

    def _contains_sensitive_info(self, text: str) -> bool:
        for pattern in self.compiled_patterns:
            if pattern.search(text):
                return True
        return False

# ==================== PERFORMANCE AWARE DECORATOR ====================

def performance_aware(max_ms: int, fallback: Callable, module_name: str = "unknown"):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.perf_counter()

            try:
                if asyncio.iscoroutinefunction(func):
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=max_ms / 1000.0)
                else:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs)),
                        timeout=max_ms / 1000.0
                    )

                duration = (time.perf_counter() - start_time) * 1000
                MODULE_PERFORMANCE.labels(module=module_name).observe(duration)
                return result

            except asyncio.TimeoutError:
                MODULE_TIMEOUTS.labels(module=module_name).inc()
                PERFORMANCE_VIOLATIONS.labels(module=module_name, reason="timeout").inc()
                logger.warning(f"Performance timeout in {module_name} after {max_ms}ms")
                return fallback()

            except Exception as e:
                MODULE_FAILURES.labels(module=module_name).inc()
                logger.error(f"Error in {module_name}: {e}")
                return fallback()

        return wrapper
    return decorator

# ==================== CONFIDENCE VALIDATION SYSTEM ====================

class ConfidenceValidator:
    def __init__(self, min_confidence: float = 0.4, max_confusion_risk: float = 0.3):
        self.min_confidence = min_confidence
        self.max_confusion_risk = max_confusion_risk

    def validate_context_usage(self, current_query: str, historical_context: Dict[str, Any]) -> Dict[str, Any]:
        validation_result = {
            "should_use": False,
            "confidence": 0.0,
            "confusion_risk": 0.0,
            "rejection_reason": None
        }

        if not historical_context or not historical_context.get("relevant", False):
            validation_result["rejection_reason"] = "no_relevant_context"
            return validation_result

        confidence = historical_context.get("confidence", 0.0)
        confusion_risk = self._calculate_confusion_risk(current_query, historical_context)

        validation_result["confidence"] = confidence
        validation_result["confusion_risk"] = confusion_risk

        if confidence < self.min_confidence:
            validation_result["rejection_reason"] = "low_confidence"
            CONTEXT_REJECTIONS.labels(reason="low_confidence").inc()

        elif confusion_risk > self.max_confusion_risk:
            validation_result["rejection_reason"] = "high_confusion_risk"
            CONTEXT_REJECTIONS.labels(reason="high_confusion_risk").inc()

        else:
            validation_result["should_use"] = True

        return validation_result

    def _calculate_confusion_risk(self, current_query: str, context: Dict[str, Any]) -> float:
        risks = []

        current_topics = set(re.findall(r'\b[a-zA-Z]{4,}\b', current_query.lower()))
        historical_topics = set(context.get("historical_topics", []))

        if current_topics and historical_topics:
            similarity = len(current_topics & historical_topics) / len(current_topics | historical_topics)
            risks.append(1.0 - similarity)

        if context.get("time_gap_hours"):
            time_risk = min(1.0, context["time_gap_hours"] / 24.0)
            risks.append(time_risk)

        return sum(risks) / len(risks) if risks else 0.0

# ==================== STORY MODE INTENT DETECTOR ====================

class StoryIntentDetector:
    def __init__(self):
        self.keywords: List[str] = getattr(
            config, "story_keywords",
            ["story", "parable", "legend", "myth", "tale", "fable", "saga"]
        )
        default_patterns = [
            r"\btell (me )?(a|another) (story|parable|legend|myth|tale)\b",
            r"\bspeak (a|the) (parable|legend|myth)\b",
            r"\bonce upon (a|the) time\b",
            r"\bweave (me )?(a )?(story|myth|tale)\b",
            r"\bcan you (tell|write) (me )?(a )?(story|parable|legend|myth|tale)\b",
            r"\bgive me (a )?(story|parable|legend|myth|tale)\b",
        ]
        custom_patterns = getattr(config, "story_patterns", []) or []
        all_patterns = default_patterns + custom_patterns
        self.patterns: List[re.Pattern] = [re.compile(p, re.I) for p in all_patterns]

    def is_story(self, query: str) -> bool:
        if not query:
            return False
        q = query.strip().lower()
        if any(k in q for k in self.keywords):
            return True
        return any(p.search(q) for p in self.patterns)

_story_detector = StoryIntentDetector()

def is_story_request(query: str) -> bool:
    return _story_detector.is_story(query)

def choose_mode(query: str, default: str = "reflection") -> str:
    try:
        if is_story_request(query):
            return "story"
        return default
    except Exception:
        return default

# ==================== GLOBAL SAFEGUARDS INSTANCES ====================

temporal_breaker = CircuitBreaker("temporal", CircuitBreakerConfig())
symbol_breaker = CircuitBreaker("symbol", CircuitBreakerConfig())
conversation_breaker = CircuitBreaker("conversation", CircuitBreakerConfig())

privacy_filter = PrivacyFilter()
confidence_validator = ConfidenceValidator()

__all__ = [
    'temporal_breaker', 'symbol_breaker', 'conversation_breaker',
    'privacy_filter', 'confidence_validator', 'performance_aware',
    'CircuitBreaker', 'PrivacyFilter', 'ConfidenceValidator',
    'StoryIntentDetector', 'is_story_request', 'choose_mode'
]
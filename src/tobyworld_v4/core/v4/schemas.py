from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field, ConfigDict

# ─────────────────────────────────────────────────────────────────────────────
# Core shapes used across V4. Designed for Pydantic v2, but we keep .dict()
# compatibility since server.py calls ctx.dict().
# ─────────────────────────────────────────────────────────────────────────────

class Hint(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    prefer_series: List[str] = Field(default_factory=list)  # e.g., ["TOBY_L","TOBY_QA"]
    depth: str = "normal"                                   # "normal" | "deep"

class GuardResult(BaseModel):
    intent: str
    refined_query: str
    curiosity_prompt: str = ""
    notes: List[str] = Field(default_factory=list)
    hint: Hint = Field(default_factory=Hint)

class RetrievalChunk(BaseModel):
    doc_id: Optional[str] = None
    span: List[int] = Field(default_factory=lambda: [0, 0])  # [start, end]
    ts: Optional[float] = None                                # unix timestamp
    epoch: Optional[str] = None
    score: Optional[float] = None
    symbols: List[str] = Field(default_factory=list)
    text: str = ""

class DraftTrace(BaseModel):
    graph_stats: Dict[str, Any] = Field(default_factory=dict)
    chosen_paths: List[str] = Field(default_factory=list)
    used: Optional[List[Dict[str, Any]]] = None
    dropped: Optional[List[str]] = None

class Draft(BaseModel):
    text: str = ""
    trace: DraftTrace = Field(default_factory=DraftTrace)

class LucidityOut(BaseModel):
    novice: str = ""
    sage: str = ""
    guiding_question: str = ""
    sources: List[str] = Field(default_factory=list)

class Metrics(BaseModel):
    components: Dict[str, float] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)

class RunCtx(BaseModel):
    model_config = ConfigDict(extra="allow")  # accept extra fields without exploding

    user: Dict[str, Any]
    query: str

    # guide
    intent: Optional[str] = None
    refined_query: Optional[str] = None

    # retrieval
    retrieval: Optional[List[RetrievalChunk | Dict[str, Any]]] = None

    # synthesis
    draft: Optional[Draft | Dict[str, Any]] = None

    # resonance
    harmony: Optional[float] = None

    # lucidity
    final: Optional[LucidityOut | Dict[str, Any]] = None

    # metrics / debug
    metrics: Optional[Metrics | Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Preferred in Pydantic v2."""
        return self.model_dump()

    # Back-compat convenience (server currently calls ctx.dict())
    def dict(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        return self.model_dump(*args, **kwargs)

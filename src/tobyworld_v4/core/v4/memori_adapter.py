# memori_adapter.py
import os
import logging
from typing import Optional, Dict, Any, List
from memori import Memori

class MemoriAdapter:
    def __init__(self):
        # ---- Hard gate: stay fully local; never initialize OpenAI-backed agents
        os.environ.setdefault("USE_OPENAI", "false")
        os.environ.setdefault("MEMORI_ENABLE_CONSCIOUS", "false")
        os.environ.setdefault("MEMORI_ENABLE_AUTO", "false")

        # (Optional) Silence Memori’s provider splash + missing-key warnings
        logging.getLogger("memori.core.memory").setLevel(logging.ERROR)

        dsn = os.getenv("MEMORI_DSN", "sqlite:///./memori.db")
        app = os.getenv("MEMORI_APP_NAME", "mirror-v4")
        self.topk = int(os.getenv("MEMORI_TOPK", "12"))

        self.m = Memori(dsn=dsn, app_name=app)
        # Even though we pass False, the SDK already printed its provider line —
        # the logger level change above suppresses it.
        self.m.enable(conscious=False, auto=False)

    def save_interaction(self, user_id: str, question: str, answer: str, meta: Optional[Dict[str,Any]]=None):
        self.m.memory.add_chat_turn(user_id=user_id, role="user", content=question, meta=meta or {})
        self.m.memory.add_chat_turn(user_id=user_id, role="assistant", content=answer, meta=meta or {})

    def upsert_fact(self, user_id: str, fact: str, kind: str="preference", tags: Optional[List[str]]=None):
        self.m.memory.upsert_memory(user_id=user_id, content=fact, kind=kind, tags=tags or [])

    def recall(self, user_id: str, query: str, topk: Optional[int]=None) -> List[Dict[str,Any]]:
        return self.m.search(user_id=user_id, query=query, top_k=topk or self.topk)

    def short_context(self, user_id: str) -> str:
        return self.m.conscious_window(user_id=user_id) or ""

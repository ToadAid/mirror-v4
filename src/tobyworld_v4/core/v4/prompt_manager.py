# tobyworld_v4/core/v4/prompt_manager.py
from __future__ import annotations
import os
from pathlib import Path

class PromptManager:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or os.getenv("PROMPTS_DIR", "prompts")).resolve()

    def get(self, name: str, default: str = "") -> str:
        """
        Load a plain-text prompt file by name from base_dir.
        Example: get("mirror_system_rules.txt")
        """
        try:
            p = self.base_dir / name
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
        return default

PM = PromptManager()

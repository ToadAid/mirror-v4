import os, time, json
from typing import List, Dict, Optional

try:
    import httpx
except Exception:
    httpx = None

class LLMClient:
    def __init__(self):
        self.enabled = os.getenv("MIRROR_LLM_ENABLED", "1") not in ("0","false","False")
        self.base = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECS", "45"))
        if not self.base or not self.model or not httpx:
            self.enabled = False

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def _extract_chat(self, data: dict) -> Optional[str]:
        # OpenAI chat format
        try:
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            content = (msg.get("content") or "").strip()
            return content or None
        except Exception:
            return None

    def _extract_text(self, data: dict) -> Optional[str]:
        # OpenAI completions (text) format
        try:
            content = ((data.get("choices") or [{}])[0].get("text") or "").strip()
            return content or None
        except Exception:
            return None

    def _chat_completions(self, messages: List[Dict[str,str]], **kwargs) -> Optional[str]:
        url = f"{self.base}/chat/completions"
        payload = {"model": self.model, "messages": messages}
        payload.update(kwargs)
        with httpx.Client(timeout=self.timeout) as cli:
            r = cli.post(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        out = self._extract_chat(data) or self._extract_text(data)
        if not out:
            print(f"[LLM][WARN] empty content from /chat/completions; raw={str(data)[:500]}...")
        return out

    def _completions(self, prompt: str, **kwargs) -> Optional[str]:
        url = f"{self.base}/completions"
        payload = {"model": self.model, "prompt": prompt}
        payload.update(kwargs)
        with httpx.Client(timeout=self.timeout) as cli:
            r = cli.post(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        out = self._extract_text(data) or self._extract_chat(data)
        if not out:
            print(f"[LLM][WARN] empty content from /completions; raw={str(data)[:500]}...")
        return out

    def chat(self, messages: List[Dict[str,str]], **kwargs) -> Optional[str]:
        if not self.enabled:
            return None
        t0 = time.perf_counter()
        try:
            out = self._chat_completions(messages, **kwargs)
            dt = time.perf_counter() - t0
            if out:
                print(f"[LLM] ok(chat) model={self.model} dt={dt:.2f}s len={len(out)}")
                return out
            # Fallback to /completions using ChatML-style prompt
            chatml = []
            for m in messages:
                role = m.get("role","user")
                content = m.get("content","")
                if role == "system":
                    chatml.append(f"<|system|>\n{content}\n")
                elif role == "assistant":
                    chatml.append(f"<|assistant|>\n{content}\n")
                else:
                    chatml.append(f"<|user|>\n{content}\n")
            chatml.append("<|assistant|>\n")
            prompt = "".join(chatml)
            out2 = self._completions(prompt, **kwargs)
            dt2 = time.perf_counter() - t0
            if out2:
                print(f"[LLM] ok(comp) model={self.model} dt={dt2:.2f}s len={len(out2)}")
            else:
                print(f"[LLM][ERR] both endpoints returned empty content.")
            return out2
        except Exception as e:
            print(f"[LLM][ERR] {type(e).__name__}: {e}")
            return None

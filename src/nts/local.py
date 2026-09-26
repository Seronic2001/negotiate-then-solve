"""Client for a local model behind an OpenAI-compatible server (llama.cpp's
``llama-server``, Ollama, LM Studio). Same interface as ``GeminiClient``,
so parsers and evaluations take either.

    llama-server -m qwen3.5-4b-nts.Q5_K_M.gguf --jinja -ngl 99 -c 4096 --port 8080

* Output is constrained to the Pydantic schema (``response_format`` with a
  JSON schema; llama.cpp turns it into a grammar), so it always parses.
* Thinking is switched off through ``chat_template_kwargs``, as in training.
* Responses are cached like Gemini's; there is no quota to track.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .llm import LLMError, Usage

T = TypeVar("T", bound=BaseModel)


class LocalClient:
    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str = "http://localhost:8080/v1",
        cache_dir: Path | str = "runs/llm_cache",
        timeout: float = 120.0,
        max_tokens: int = 512,
        thinking: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.model = model or self._served_model()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.usage = Usage()
        self.latencies: list[float] = []
        self._lock = threading.Lock()

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(f"{self.base_url}{path}", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise LLMError(f"local server {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"local server not reachable at {self.base_url}: {e}") from e

    def _served_model(self) -> str:
        models = self._request("/models").get("data", [])
        if not models:
            raise LLMError(f"no model served at {self.base_url}")
        return "local:" + Path(models[0]["id"]).name

    def generate(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        use_cache: bool = True,
    ) -> T:
        schema_json = schema.model_json_schema()
        key = hashlib.sha256(json.dumps(
            [self.model, str(self.thinking), system, prompt, json.dumps(schema_json, sort_keys=True), temperature]
        ).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if use_cache and path.exists():
            with self._lock:
                self.usage.cache_hits += 1
            return schema.model_validate_json(json.loads(path.read_text(encoding="utf-8"))["text"])

        payload = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema.__name__, "schema": schema_json, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": self.thinking},
        }
        started = time.monotonic()
        resp = self._request("/chat/completions", payload)
        latency = time.monotonic() - started
        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response: {str(resp)[:300]}") from e
        result = schema.model_validate_json(text)
        usage = resp.get("usage") or {}
        with self._lock:
            self.usage.calls += 1
            self.usage.prompt_tokens += usage.get("prompt_tokens", 0)
            self.usage.output_tokens += usage.get("completion_tokens", 0)
            self.latencies.append(latency)
        path.write_text(json.dumps({"model": self.model, "text": text, "usage": usage}, ensure_ascii=False),
                        encoding="utf-8")
        return result

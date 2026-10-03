"""Client for a local model behind an OpenAI-compatible server (llama.cpp's
``llama-server``, Ollama, LM Studio). Same interface as ``GeminiClient``,
so parsers and evaluations take either.

    llama-server -m Qwen3.5-2B.Q5_K_M-mutitask-finetune.gguf --jinja -ngl 99 -c 4096 --cache-ram 1024 --port 8080

* Output is constrained to the Pydantic schema (``response_format`` with a
  JSON schema; llama.cpp turns it into a grammar), so it always parses.
  ``grammar_schema`` keeps the grammar's key order that of the training data.
* Thinking is switched off through ``chat_template_kwargs``, as in training.
* Responses are cached like Gemini's; there is no quota to track. The cache
  key holds the model file name, so give each model file its own name.
* A server in router mode (``llama-server --models-dir <dir> --models-max 1``)
  lists every GGUF in the folder and loads the one a request names: choose it
  with ``server_model`` or ``NTS_LOCAL_MODEL`` (the name, the file name or the
  path the server lists).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .llm import LLMError, Usage

T = TypeVar("T", bound=BaseModel)


def grammar_schema(schema: dict) -> dict:
    """The JSON schema as sent to llama.cpp. Its grammar writes required
    properties first and optional ones after, so an optional field declared
    before a required one (``cited_rules`` before ``explanation``) could only
    come after it, out of the training order, and the model left it out.
    Every property up to the last required one is made required, so keys
    come in declaration order, as in the training targets."""
    schema = json.loads(json.dumps(schema))
    for node in [schema, *schema.get("$defs", {}).values()]:
        props, required = list(node.get("properties", {})), set(node.get("required", []))
        if required:
            last = max(props.index(p) for p in required)
            node["required"] = props[:last + 1]
    return schema


def _name(model_id: str) -> str:
    """The model's name in reports and cache keys: its file name, whether the
    server lists the path (one model) or the name without .gguf (router)."""
    return "local:" + Path(model_id).name.removesuffix(".gguf") + ".gguf"


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
        server_model: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.server_model = server_model or os.environ.get("NTS_LOCAL_MODEL") or None
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
        ids = [m["id"] for m in self._request("/models").get("data", [])]
        if not ids:
            raise LLMError(f"no model served at {self.base_url}")
        if self.server_model:
            want = self.server_model.removesuffix(".gguf")
            hits = [i for i in ids if want in (i, Path(i).name, Path(i).name.removesuffix(".gguf"))]
            if not hits:
                raise LLMError(f"{self.server_model!r} is not served at {self.base_url}; it serves {ids}")
            self.server_model = hits[0]  # the id the server knows it by
            return _name(hits[0])
        if len(ids) > 1:
            raise LLMError(f"{self.base_url} serves {len(ids)} models (router mode): choose one with "
                           f"NTS_LOCAL_MODEL or --local-model: {ids}")
        return _name(ids[0])

    def generate(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        use_cache: bool = True,
    ) -> T:
        schema_json = grammar_schema(schema.model_json_schema())
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
        if self.server_model:
            payload["model"] = self.server_model
        started = time.monotonic()
        resp = self._request("/chat/completions", payload)
        latency = time.monotonic() - started
        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response: {str(resp)[:300]}") from e
        try:
            result = schema.model_validate_json(text)
        except ValidationError as e:  # the grammar guarantees valid JSON unless output was cut off
            finish = resp["choices"][0].get("finish_reason")
            raise LLMError(f"invalid {schema.__name__} (finish_reason={finish}, {len(text)} chars)") from e
        usage = resp.get("usage") or {}
        with self._lock:
            self.usage.calls += 1
            self.usage.prompt_tokens += usage.get("prompt_tokens", 0)
            self.usage.output_tokens += usage.get("completion_tokens", 0)
            self.latencies.append(latency)
        path.write_text(json.dumps({"model": self.model, "text": text, "usage": usage}, ensure_ascii=False),
                        encoding="utf-8")
        return result

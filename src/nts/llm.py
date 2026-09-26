"""Gemini API client for the free tier (proposal Section 14).

* Structured output: responses are parsed into a Pydantic model.
* Disk cache keyed by a hash of (model, prompts, schema, temperature), so
  reruns of an experiment never repeat a call.
* A simple requests-per-minute limiter plus retries with backoff on 429/5xx,
  because free-tier quotas are per minute and per day.

The key comes from ``GEMINI_API_KEY`` (environment or a ``.env`` file).
Model ids come from ``GEMINI_MODEL`` / ``GEMINI_LITE_MODEL`` so they can
follow Google's current Flash releases without code changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeVar

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Pinned model ids (not "-latest" aliases, which can be repointed or
# overloaded) so experiment runs are reproducible. Each model has its own
# free-tier quota, so the roles use different models:
#   agent     - System Two parser and negotiator
#   simulator - stakeholder simulators and the LLM judge (bulk calls)
#   flash     - larger-model comparison set (only 20 requests/day)
MODELS = {
    "agent": "gemini-3.5-flash-lite",
    "simulator": "gemini-3.1-flash-lite",
    "flash": "gemini-3.8-flash",
}
_ENV = {"agent": "GEMINI_MODEL", "simulator": "GEMINI_SIM_MODEL", "flash": "GEMINI_FLASH_MODEL"}

# Free-tier (RPM, RPD) per model, from the AI Studio rate-limit page (Sep 2026).
# GEMINI_RPM / GEMINI_RPD override these.
FREE_TIER = {
    "gemini-3.5-flash-lite": (15, 500),
    "gemini-3.1-flash-lite": (15, 500),
    "gemini-3.8-flash": (5, 20),
    "gemini-3.6-flash": (5, 20),
    "gemini-3.5-flash": (5, 20),
    "gemini-2.5-flash": (5, 20),
}
_FALLBACK_LIMITS = (5, 20)  # unknown model: assume the tightest tier


def default_thinking(model: str) -> int | str:
    """Flash accepts thinking_budget=0; Flash-Lite only accepts a thinking level."""
    return "low" if "lite" in model else 0


def default_model(role: str = "agent") -> str:
    load_dotenv(find_dotenv(usecwd=True))
    return os.environ.get(_ENV[role], MODELS[role])


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    last_retry_reason: str = ""


class LLMError(RuntimeError):
    pass


class DailyQuotaReached(LLMError):
    """This run would exceed the per-day request budget. Cached responses
    mean a rerun tomorrow resumes where this one stopped."""


class GeminiClient:
    def __init__(
        self,
        model: str | None = None,
        *,
        cache_dir: Path | str = "runs/llm_cache",
        rpm: float | None = None,
        rpd: int | None = None,
        max_retries: int = 6,
        thinking: int | str | None = None,
        api_key: str | None = None,
    ) -> None:
        from google import genai  # imported here so the rest of nts works without the SDK

        load_dotenv(find_dotenv(usecwd=True))
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set (environment or .env)")
        self._client = genai.Client(api_key=key)
        self.model = model or default_model()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tier_rpm, tier_rpd = FREE_TIER.get(self.model, _FALLBACK_LIMITS)
        rpm = rpm or float(os.environ.get("GEMINI_RPM", tier_rpm))
        self.min_interval = 60.0 / (rpm * 0.9)  # 10% headroom: Google's minute window isn't ours
        self.rpd = rpd or int(os.environ.get("GEMINI_RPD", tier_rpd))
        self.max_retries = max_retries
        # int = thinking token budget, str = thinking level, None = model default
        self.thinking = thinking if thinking is not None else default_thinking(self.model)
        self.usage = Usage()
        self.latencies: list[float] = []  # API time per successful call, excluding pacing
        # Several requests may be in flight at once (latency, not quota, is
        # usually the bottleneck); the lock only serialises when they *start*.
        self._lock = threading.Lock()

    def generate(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        use_cache: bool = True,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
        key = hashlib.sha256(
            json.dumps([self.model, str(self.thinking), system, prompt, schema_json, temperature]).encode()
        ).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if use_cache and path.exists():
            with self._lock:
                self.usage.cache_hits += 1
            return schema.model_validate_json(json.loads(path.read_text(encoding="utf-8"))["text"])

        text, usage = self._call(system, prompt, schema, temperature)
        result = schema.model_validate_json(text)
        path.write_text(
            json.dumps({"model": self.model, "text": text, "usage": usage}, ensure_ascii=False),
            encoding="utf-8",
        )
        return result

    def _call(self, system: str, prompt: str, schema: type[BaseModel], temperature: float) -> tuple[str, dict]:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if isinstance(self.thinking, int):
            config.thinking_config = types.ThinkingConfig(thinking_budget=self.thinking)
        elif isinstance(self.thinking, str):
            config.thinking_config = types.ThinkingConfig(thinking_level=self.thinking)

        delay = 5.0
        for attempt in range(self.max_retries + 1):
            with self._lock:
                self._count_today()
                self._pace()
            started = time.monotonic()
            try:
                resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
                latency = time.monotonic() - started
            except errors.APIError as e:
                if e.code == 429 and "PerDay" in json.dumps(e.details or {}):
                    # A daily quota never clears by waiting minutes; retrying only burns time.
                    raise DailyQuotaReached(f"{self.model}: Google daily free-tier quota exhausted") from e
                retryable = e.code == 429 or (e.code is not None and e.code >= 500)
                if not retryable or attempt == self.max_retries:
                    raise LLMError(f"Gemini call failed ({e.code}): {e.message}") from e
                with self._lock:
                    self.usage.retries += 1
                    self.usage.last_retry_reason = f"{e.code}: {str(e.message)[:300]}"
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            meta = resp.usage_metadata
            usage = {
                "prompt_tokens": (meta.prompt_token_count or 0) if meta else 0,
                "output_tokens": (meta.candidates_token_count or 0) if meta else 0,
            }
            with self._lock:
                self.usage.calls += 1
                self.usage.prompt_tokens += usage["prompt_tokens"]
                self.usage.output_tokens += usage["output_tokens"]
                self.latencies.append(latency)
            if not resp.text:
                raise LLMError(f"empty response (finish reason: {resp.candidates and resp.candidates[0].finish_reason})")
            return resp.text, usage
        raise AssertionError("unreachable")

    def _pace(self) -> None:
        """Keep calls to this model ``min_interval`` apart across *all*
        processes sharing the cache dir; the quota is per project, so two
        concurrent runs would otherwise add up past the RPM limit."""
        stamp = self.cache_dir / f"_last-{self.model}.txt"
        last = float(stamp.read_text()) if stamp.exists() else 0.0
        wait = last + self.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        stamp.write_text(repr(time.time()))

    def _count_today(self) -> None:
        """Count one request against today's budget (Pacific time is when
        Google resets quotas; local date is close enough to stay under)."""
        path = self.cache_dir / f"_quota-{self.model}-{date.today().isoformat()}.txt"
        used = int(path.read_text()) if path.exists() else 0
        if used >= self.rpd:
            raise DailyQuotaReached(
                f"{used} {self.model} requests today reaches the daily budget of {self.rpd} (GEMINI_RPD)"
            )
        path.write_text(str(used + 1))

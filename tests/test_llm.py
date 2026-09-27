"""Unit tests for GeminiClient API key pooling, load balancing, and failover."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from language.llm import (
    DailyQuotaReached,
    GeminiClient,
    LLMError,
    mask_key,
    resolve_api_keys,
)


class DummyOutput(BaseModel):
    answer: str


def test_resolve_api_keys_variants(monkeypatch):
    # 1. Single explicit api_key
    assert resolve_api_keys(api_key="keyA") == ["keyA"]

    # 2. Delimited api_key
    assert resolve_api_keys(api_key="keyA, keyB; keyC\nkeyD") == ["keyA", "keyB", "keyC", "keyD"]

    # 3. List of keys
    assert resolve_api_keys(api_keys=["key1", "key2", "key1"]) == ["key1", "key2"]

    # 4. Delimited string in api_keys
    assert resolve_api_keys(api_keys="k1, k2, k3") == ["k1", "k2", "k3"]

    # 5. Environment variable GEMINI_API_KEYS
    monkeypatch.setenv("GEMINI_API_KEYS", "env1, env2; env3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert resolve_api_keys() == ["env1", "env2", "env3"]
    monkeypatch.delenv("GEMINI_API_KEYS")

    # 6. Environment variable GEMINI_API_KEY
    monkeypatch.setenv("GEMINI_API_KEY", "single_env")
    assert resolve_api_keys() == ["single_env"]
    monkeypatch.delenv("GEMINI_API_KEY")

    # 7. Numbered environment variables
    monkeypatch.setenv("GEMINI_API_KEY_2", "num2")
    monkeypatch.setenv("GEMINI_API_KEY_1", "num1")
    monkeypatch.setenv("GEMINI_API_KEY_3", "num3")
    assert resolve_api_keys() == ["num1", "num2", "num3"]


def test_resolve_api_keys_empty_raises():
    # When explicit empty list is given, it should return [] and GeminiClient raises LLMError
    assert resolve_api_keys(api_keys=[]) == []
    with pytest.raises(LLMError, match="GEMINI_API_KEY is not set"):
        GeminiClient(api_keys=[])


def test_mask_key():
    assert mask_key("short") == "...hort"
    assert mask_key("AIzaSyB1234567890abcdef") == "...abcdef"
    assert mask_key("") == "<empty>"


def _make_mock_client(return_text: str = '{"answer": "ok"}', on_call=None):
    client = MagicMock()
    def _generate(model, contents, config):
        if on_call:
            on_call()
        resp = SimpleNamespace(
            text=return_text,
            usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
            candidates=[SimpleNamespace(finish_reason="STOP")],
        )
        return resp
    client.models.generate_content.side_effect = _generate
    return client


def test_pool_round_robin_distribution(tmp_path):
    mock_clients = {
        "k1": _make_mock_client('{"answer": "from_k1"}'),
        "k2": _make_mock_client('{"answer": "from_k2"}'),
        "k3": _make_mock_client('{"answer": "from_k3"}'),
    }

    client = GeminiClient(
        model="gemini-3.5-flash-lite",
        api_keys=["k1", "k2", "k3"],
        cache_dir=tmp_path,
        rpm=6000,  # high rpm so no sleep wait in unit test
        _client_factory=lambda k: mock_clients[k],
    )

    assert len(client.keys) == 3
    assert client.effective_rpd == 1500  # 500 * 3
    assert client.effective_min_interval < client.min_interval

    # Run 6 non-cached queries
    for i in range(6):
        out = client.generate(
            system="system prompt",
            prompt=f"prompt {i}",
            schema=DummyOutput,
            use_cache=False,
        )
        assert out.answer.startswith("from_k")

    # Each key should have handled exactly 2 calls
    assert client.usage.calls == 6
    status = client.pool_status()
    assert len(status) == 3
    for s in status:
        assert s["calls"] == 2
        assert s["errors"] == 0
        assert not s["exhausted_today"]


def test_pool_failover_on_daily_quota(tmp_path):
    from google.genai import errors

    client1 = MagicMock()
    err_429_per_day = errors.APIError(429, {"error": {"message": "Quota exceeded", "details": [{"quota": "PerDay"}]}})
    client1.models.generate_content.side_effect = err_429_per_day

    client2 = _make_mock_client('{"answer": "from_k2"}')

    factory_map = {"k1": client1, "k2": client2}

    client = GeminiClient(
        model="gemini-3.5-flash-lite",
        api_keys=["k1", "k2"],
        cache_dir=tmp_path,
        rpm=6000,
        _client_factory=lambda k: factory_map[k],
    )

    # First call encounters 429 on k1, marks k1 exhausted, and seamlessly succeeds on k2
    out = client.generate(
        system="sys",
        prompt="call 1",
        schema=DummyOutput,
        use_cache=False,
    )
    assert out.answer == "from_k2"
    assert client.pool.keys[0].exhausted_today is True
    assert client.pool.keys[1].calls == 1

    # Second call uses k2 directly (k1 is skipped)
    out2 = client.generate(
        system="sys",
        prompt="call 2",
        schema=DummyOutput,
        use_cache=False,
    )
    assert out2.answer == "from_k2"
    assert client.pool.keys[1].calls == 2

    # Now if k2 also runs out of quota, DailyQuotaReached is raised
    client2.models.generate_content.side_effect = err_429_per_day
    with pytest.raises(DailyQuotaReached, match="exhausted daily quota"):
        client.generate(
            system="sys",
            prompt="call 3",
            schema=DummyOutput,
            use_cache=False,
        )


def test_pool_failover_on_rate_limit(tmp_path):
    from google.genai import errors

    # k1 fails with 429 rate limit
    client1 = MagicMock()
    err_429_rpm = errors.APIError(429, {"error": {"message": "Rate limit exceeded (RPM)"}})
    client1.models.generate_content.side_effect = err_429_rpm

    client2 = _make_mock_client('{"answer": "recovered_on_k2"}')
    factory_map = {"k1": client1, "k2": client2}

    client = GeminiClient(
        model="gemini-3.5-flash-lite",
        api_keys=["k1", "k2"],
        cache_dir=tmp_path,
        rpm=6000,
        max_retries=2,
        _client_factory=lambda k: factory_map[k],
    )

    out = client.generate(
        system="sys",
        prompt="test retry",
        schema=DummyOutput,
        use_cache=False,
    )
    assert out.answer == "recovered_on_k2"
    assert client.usage.retries == 1
    assert client.pool.keys[0].retries == 1
    assert client.pool.keys[1].calls == 1


def test_pool_failover_on_invalid_api_key(tmp_path):
    from google.genai import errors

    # k1 is an invalid key
    client1 = MagicMock()
    err_bad_key = errors.APIError(400, {"error": {"message": "API key not valid. Please pass a valid API key."}})
    client1.models.generate_content.side_effect = err_bad_key

    client2 = _make_mock_client('{"answer": "valid_key_succeeded"}')
    factory_map = {"bad_key": client1, "good_key": client2}

    client = GeminiClient(
        model="gemini-3.5-flash-lite",
        api_keys=["bad_key", "good_key"],
        cache_dir=tmp_path,
        rpm=6000,
        _client_factory=lambda k: factory_map[k],
    )

    out = client.generate(
        system="sys",
        prompt="test invalid key",
        schema=DummyOutput,
        use_cache=False,
    )
    assert out.answer == "valid_key_succeeded"
    assert client.pool.keys[0].disabled is True
    assert client.pool.keys[1].calls == 1


def test_cache_skips_pool_calls(tmp_path):
    mock_c = _make_mock_client('{"answer": "cached"}')
    client = GeminiClient(
        model="gemini-3.5-flash-lite",
        api_keys=["k1"],
        cache_dir=tmp_path,
        rpm=6000,
        _client_factory=lambda k: mock_c,
    )

    out1 = client.generate(system="sys", prompt="p", schema=DummyOutput, use_cache=True)
    assert out1.answer == "cached"
    assert client.usage.calls == 1
    assert client.usage.cache_hits == 0

    out2 = client.generate(system="sys", prompt="p", schema=DummyOutput, use_cache=True)
    assert out2.answer == "cached"
    assert client.usage.calls == 1
    assert client.usage.cache_hits == 1


def test_concurrent_pool_requests(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    call_count = {"k1": 0, "k2": 0}
    lock = threading.Lock()

    def _make_counting_client(name):
        client = MagicMock()
        def _generate(model, contents, config):
            with lock:
                call_count[name] += 1
            time.sleep(0.01)
            resp = SimpleNamespace(
                text=f'{{"answer": "{name}"}}',
                usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
                candidates=[SimpleNamespace(finish_reason="STOP")],
            )
            return resp
        client.models.generate_content.side_effect = _generate
        return client

    factory_map = {
        "k1": _make_counting_client("k1"),
        "k2": _make_counting_client("k2"),
    }

    client = GeminiClient(
        model="gemini-3.5-flash-lite",
        api_keys=["k1", "k2"],
        cache_dir=tmp_path,
        rpm=60000,
        _client_factory=lambda k: factory_map[k],
    )

    def _worker(idx):
        return client.generate(
            system="sys",
            prompt=f"item {idx}",
            schema=DummyOutput,
            use_cache=False,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(_worker, range(10)))

    assert len(results) == 10
    assert client.usage.calls == 10
    # Both keys should have received roughly equal share (5 each)
    assert call_count["k1"] == 5
    assert call_count["k2"] == 5
    assert client.usage.key_distribution[client.pool.keys[0].key_id] == 5
    assert client.usage.key_distribution[client.pool.keys[1].key_id] == 5

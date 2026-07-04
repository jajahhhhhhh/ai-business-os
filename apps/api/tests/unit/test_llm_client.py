"""AnthropicLlmClient: Messages call shape, provider failover, pricing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from src.infrastructure.llm_client import (
    ANTHROPIC_VERSION,
    AnthropicLlmClient,
    LlmError,
    ModelCandidate,
    candidate_cost_usd,
)

HAIKU = ModelCandidate("anthropic", "claude-haiku-4-5-20251001", Decimal("1.00"), Decimal("5.00"))
OPUS = ModelCandidate("anthropic", "claude-opus-4-8", Decimal("5.00"), Decimal("25.00"))
SONNET = ModelCandidate("anthropic", "claude-sonnet-5", Decimal("3.00"), Decimal("15.00"))
GPT = ModelCandidate("openai", "gpt-4o", Decimal("2.50"), Decimal("10.00"))


class StubResponse:
    def __init__(self, payload: dict[str, Any] | None = None, status_code: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class StubClient:
    def __init__(self, *results: StubResponse | Exception) -> None:
        self.results = list(results)
        self.requests: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: dict, json: dict) -> StubResponse:
        self.requests.append({"url": url, "headers": headers, "json": json})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _payload(text: str, tokens_in: int = 1000, tokens_out: int = 200) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }


# ------------------------------------------------------------------ complete


async def test_complete_success_and_request_shape() -> None:
    stub = StubClient(StubResponse(_payload("ตอบ")))
    client = AnthropicLlmClient("sk-test", client=stub)

    text, tokens_in, tokens_out = await client.complete("m-1", "system!", "prompt", 300)

    assert (text, tokens_in, tokens_out) == ("ตอบ", 1000, 200)
    [request] = stub.requests
    assert request["headers"]["x-api-key"] == "sk-test"
    assert request["headers"]["anthropic-version"] == ANTHROPIC_VERSION
    assert request["json"]["model"] == "m-1"
    assert request["json"]["max_tokens"] == 300
    assert request["json"]["system"] == "system!"
    assert request["json"]["messages"] == [{"role": "user", "content": "prompt"}]


async def test_complete_omits_system_when_none() -> None:
    stub = StubClient(StubResponse(_payload("x")))
    client = AnthropicLlmClient("sk-test", client=stub)
    await client.complete("m-1", None, "prompt", 100)
    assert "system" not in stub.requests[0]["json"]


async def test_complete_without_key_raises_nonretryable() -> None:
    client = AnthropicLlmClient("", client=StubClient())
    with pytest.raises(LlmError) as excinfo:
        await client.complete("m-1", None, "p", 10)
    assert excinfo.value.retryable is False


async def test_complete_empty_text_carries_token_counts() -> None:
    stub = StubClient(StubResponse(_payload("", tokens_in=7, tokens_out=3)))
    client = AnthropicLlmClient("sk-test", client=stub)
    with pytest.raises(LlmError) as excinfo:
        await client.complete("m-1", None, "p", 10)
    assert excinfo.value.tokens_in == 7 and excinfo.value.tokens_out == 3


# ------------------------------------------------------------------ failover


async def test_failover_first_fails_second_succeeds_with_its_pricing() -> None:
    stub = StubClient(StubResponse(status_code=529), StubResponse(_payload("รายงาน")))
    client = AnthropicLlmClient("sk-test", client=stub)

    response = await client.complete_with_failover([OPUS, SONNET], None, "p", 100)

    assert response.model == SONNET.model_id
    assert response.text == "รายงาน"
    # 1000 in * $3/M + 200 out * $15/M = 0.003 + 0.003
    assert response.cost_usd == Decimal("0.0060")
    assert [r["json"]["model"] for r in stub.requests] == [OPUS.model_id, SONNET.model_id]


async def test_failover_skips_non_anthropic_candidates() -> None:
    stub = StubClient(StubResponse(_payload("ok")))
    client = AnthropicLlmClient("sk-test", client=stub)

    response = await client.complete_with_failover([GPT, HAIKU], None, "p", 100)

    assert response.model == HAIKU.model_id
    assert [r["json"]["model"] for r in stub.requests] == [HAIKU.model_id]


async def test_failover_all_fail_raises_retryable() -> None:
    stub = StubClient(ConnectionError("down"), StubResponse(status_code=500))
    client = AnthropicLlmClient("sk-test", client=stub)
    with pytest.raises(LlmError) as excinfo:
        await client.complete_with_failover([OPUS, SONNET], None, "p", 100)
    assert excinfo.value.retryable is True


async def test_failover_with_only_unsupported_candidates_raises() -> None:
    client = AnthropicLlmClient("sk-test", client=StubClient())
    with pytest.raises(LlmError):
        await client.complete_with_failover([GPT], None, "p", 100)


# ------------------------------------------------------------------- pricing


def test_candidate_cost_quantizes_to_4_decimals() -> None:
    assert candidate_cost_usd(HAIKU, 1_000_000, 1_000_000) == Decimal("6.0000")
    assert candidate_cost_usd(HAIKU, 1000, 200) == Decimal("0.0020")
    assert candidate_cost_usd(OPUS, 0, 0) == Decimal("0.0000")

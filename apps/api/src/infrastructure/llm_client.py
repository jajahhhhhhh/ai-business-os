"""Reusable Anthropic Messages client with provider failover (M4).

Generalizes the ChangeAnalyst httpx call from M3 into one place:

- ``complete(model_id, system, prompt, max_tokens)`` -> (text, tokens_in,
  tokens_out); raises LlmError on any problem (missing key, HTTP error,
  empty text). No SDK — plain httpx with x-api-key + anthropic-version.
- ``complete_with_failover(candidates, ...)`` walks a tier's candidate list
  (orchestrator ModelRouter order) and returns the first success. Anthropic
  only for now: candidates with any other provider are skipped with a debug
  log because no other provider key exists in Settings (documented in
  docs/tech-debt.md TD-9). Cost comes from the candidate's per-mtok prices.

This module deliberately does NOT import the orchestrator package — it sits
on the main API import chain (via change_analyst/adapters). ModelCandidate
mirrors orchestrator.router.ModelSpec structurally; infrastructure/
agent_runtime.py converts between the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
import structlog

logger = structlog.get_logger("infrastructure.llm_client")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT_S = 60.0
ERROR_MAX_CHARS = 500

_MTOK = Decimal(1_000_000)
_CENT4 = Decimal("0.0001")  # agent_runs.cost_usd is numeric(10,4)

SUPPORTED_PROVIDER = "anthropic"


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """Structural mirror of orchestrator.router.ModelSpec (no import)."""

    provider: str
    model_id: str
    usd_per_mtok_in: Decimal
    usd_per_mtok_out: Decimal


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    cost_usd: Decimal


class LlmError(Exception):
    """One failed completion attempt. `retryable` mirrors AgentError semantics;
    token counts are carried so callers can still book the failed attempt."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        self.retryable = retryable
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        super().__init__(message)


def candidate_cost_usd(candidate: ModelCandidate, tokens_in: int, tokens_out: int) -> Decimal:
    """Exact cost from the candidate's price card, quantized to 4 decimals."""
    cost = (
        Decimal(tokens_in) * candidate.usd_per_mtok_in
        + Decimal(tokens_out) * candidate.usd_per_mtok_out
    ) / _MTOK
    return cost.quantize(_CENT4, rounding=ROUND_HALF_UP)


class AnthropicLlmClient:
    """Messages API over httpx. Tests inject a stub `client`; production
    builds an AsyncClient lazily and releases it via aclose()."""

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        self._api_key = api_key
        self._client = client

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _client_or_build(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            aclose = getattr(self._client, "aclose", None)
            if aclose is not None:
                await aclose()

    async def complete(
        self, model_id: str, system: str | None, prompt: str, max_tokens: int
    ) -> tuple[str, int, int]:
        """One Messages API call. Returns (text, tokens_in, tokens_out);
        raises LlmError on any problem."""
        if not self._api_key:
            raise LlmError("ANTHROPIC_API_KEY is not configured", retryable=False)
        body: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        try:
            response = await self._client_or_build().post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized to LlmError for callers
            message = str(exc)[:ERROR_MAX_CHARS] or exc.__class__.__name__
            raise LlmError(message) from exc

        usage = payload.get("usage") or {}
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        text = "\n".join(
            block.get("text", "")
            for block in payload.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            raise LlmError("empty text response", tokens_in=tokens_in, tokens_out=tokens_out)
        return text, tokens_in, tokens_out

    async def complete_with_failover(
        self,
        candidates: list[ModelCandidate],
        system: str | None,
        prompt: str,
        max_tokens: int,
    ) -> LlmResponse:
        """Try each candidate in order; first success wins.

        Non-anthropic candidates are skipped (no key config exists for other
        providers yet). Raises a retryable LlmError when every candidate
        fails or none is usable.
        """
        last_error: LlmError | None = None
        for candidate in candidates:
            if candidate.provider != SUPPORTED_PROVIDER:
                logger.debug(
                    "llm_candidate_skipped_unsupported_provider",
                    provider=candidate.provider,
                    model=candidate.model_id,
                )
                continue
            try:
                text, tokens_in, tokens_out = await self.complete(
                    candidate.model_id, system, prompt, max_tokens
                )
            except LlmError as exc:
                logger.warning("llm_candidate_failed", model=candidate.model_id, error=str(exc))
                last_error = exc
                if not exc.retryable:
                    break  # e.g. missing key: no point walking the rest
                continue
            return LlmResponse(
                text=text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=candidate.model_id,
                cost_usd=candidate_cost_usd(candidate, tokens_in, tokens_out),
            )
        if last_error is not None:
            raise LlmError(
                f"all candidates failed (last: {last_error})",
                retryable=last_error.retryable,
            ) from last_error
        raise LlmError("no usable model candidates for this tier", retryable=True)

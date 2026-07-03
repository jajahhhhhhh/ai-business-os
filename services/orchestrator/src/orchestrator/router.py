"""Model-tier routing with provider failover (ADR-7).

Claude primary, OpenAI fallback. Tier → model mapping is config, not code
scattered across agents. Prices are per million tokens, USD, used for the
budget ledger — keep in sync with provider pricing pages (checked in CI
weekly job, docs/tech-debt.md#pricing).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from orchestrator.contract import ModelTier


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str  # "anthropic" | "openai"
    model_id: str
    usd_per_mtok_in: Decimal
    usd_per_mtok_out: Decimal


DEFAULT_ROUTES: dict[ModelTier, list[ModelSpec]] = {
    # First entry is primary; the rest are failover order.
    ModelTier.LOW: [
        ModelSpec("anthropic", "claude-haiku-4-5-20251001", Decimal("1.00"), Decimal("5.00")),
        ModelSpec("openai", "gpt-4o-mini", Decimal("0.15"), Decimal("0.60")),
    ],
    ModelTier.MID: [
        ModelSpec("anthropic", "claude-sonnet-5", Decimal("3.00"), Decimal("15.00")),
        ModelSpec("openai", "gpt-4o", Decimal("2.50"), Decimal("10.00")),
    ],
    ModelTier.HIGH: [
        ModelSpec("anthropic", "claude-opus-4-8", Decimal("5.00"), Decimal("25.00")),
        ModelSpec("anthropic", "claude-sonnet-5", Decimal("3.00"), Decimal("15.00")),
    ],
}


class ModelRouter:
    def __init__(self, routes: dict[ModelTier, list[ModelSpec]] | None = None) -> None:
        self._routes = routes or DEFAULT_ROUTES

    def candidates(self, tier: ModelTier) -> list[ModelSpec]:
        specs = self._routes.get(tier, [])
        if not specs:
            raise ValueError(f"no models configured for tier {tier}")
        return list(specs)

    @staticmethod
    def estimate_cost(spec: ModelSpec, tokens_in: int, tokens_out: int) -> Decimal:
        return (spec.usd_per_mtok_in * tokens_in + spec.usd_per_mtok_out * tokens_out) / Decimal(
            1_000_000
        )

"""Environment-driven application settings (pydantic-settings)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_agent_budgets() -> dict[str, Decimal]:
    """Per-agent daily USD caps (M4). Env override: AGENT_BUDGETS_JSON."""
    return {
        "analytics": Decimal("1.00"),
        "planner": Decimal("0.50"),
        "memory": Decimal("0.20"),
        "qa": Decimal("0.50"),
        "change-analyst": Decimal("2.00"),
    }


class MissingSecretError(RuntimeError):
    """Raised when a required secret is requested but not configured."""


class Settings(BaseSettings):
    """All runtime configuration. Every field maps to an UPPER_CASE env var."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # agent_budgets uses validation_alias AGENT_BUDGETS_JSON for its env
        # var; populate_by_name keeps Settings(agent_budgets=...) working in
        # tests and factories.
        populate_by_name=True,
    )

    env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    version: str = "0.1.0"

    # Infrastructure endpoints (safe defaults for local docker-compose).
    database_url: str = "postgresql+asyncpg://osuser:ospass@localhost:5432/aibos"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    meili_url: str = "http://localhost:7700"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "aibos"

    # Knowledge base (M2).
    embedding_model: str = "BAAI/bge-m3"
    kb_max_upload_mb: int = 25

    # LLM (M3 competitor intel; generalized in M4).
    change_analyst_model: str = "claude-haiku-4-5-20251001"
    # Hard daily spend cap across all agents; at/over -> LLM calls fall back
    # to rule-based paths. Env: LLM_DAILY_BUDGET_USD.
    llm_daily_budget_usd: Decimal = Decimal("5.00")

    # M4 agent runtime: per-agent daily USD caps enforced by the orchestrator
    # Runner via SqlDailyBudget. Env override: AGENT_BUDGETS_JSON, a JSON
    # object like {"analytics": 1.0, "planner": 0.5}. Unknown agents default
    # to a zero cap and never run.
    agent_budgets: dict[str, Decimal] = Field(
        default_factory=_default_agent_budgets,
        validation_alias="AGENT_BUDGETS_JSON",
    )
    # Prompt-template root (packages/prompts). Empty -> auto-resolve:
    # /app/prompts in the container, walk-up to packages/prompts in dev.
    prompts_dir: str = ""

    # Secrets: default empty; access through `require()` when actually needed.
    meili_master_key: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    api_secret_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    line_channel_access_token: str = ""
    line_owner_user_id: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""

    def require(self, name: str) -> str:
        """Return the named setting, raising a clear error if it is empty.

        Use for secrets that are optional at boot but mandatory for a feature,
        e.g. ``settings.require("anthropic_api_key")``.
        """
        try:
            value = getattr(self, name.lower())
        except AttributeError as exc:
            raise MissingSecretError(f"Unknown setting {name!r}") from exc
        if not isinstance(value, str) or not value:
            raise MissingSecretError(
                f"Required secret {name.upper()} is not set. "
                f"Export it as an environment variable or add it to the .env file."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

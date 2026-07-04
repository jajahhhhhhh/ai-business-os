"""SqlDailyBudget: orchestrator DailyBudget semantics over agent_runs sums.

Requires the orchestrator package (services/orchestrator); skipped cleanly
when it is not on the path (dev: PYTHONPATH=services/orchestrator/src).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("orchestrator")

from orchestrator.budget import BudgetExceeded  # noqa: E402

from src.infrastructure.agent_runtime import SqlDailyBudget  # noqa: E402
from tests.fakes import FakeCostAggregator  # noqa: E402

CAPS = {"analytics": Decimal("1.00"), "memory": Decimal("0.20")}


def _budget(
    sums: dict[str, Decimal] | None = None,
    caps: dict[str, Decimal] | None = None,
    global_cap: Decimal = Decimal("5.00"),
) -> SqlDailyBudget:
    return SqlDailyBudget(
        caps=caps or CAPS,
        global_cap=global_cap,
        aggregator=FakeCostAggregator(sums),
    )


async def test_fresh_day_under_cap_passes() -> None:
    budget = _budget()
    await budget.refresh()
    budget.check("analytics")  # no raise


async def test_unknown_agent_has_zero_cap_and_never_runs() -> None:
    budget = _budget()
    await budget.refresh()
    with pytest.raises(BudgetExceeded):
        budget.check("rogue-agent")


async def test_zero_cap_blocks_even_with_no_spend() -> None:
    budget = _budget(caps={"analytics": Decimal("0")})
    await budget.refresh()
    with pytest.raises(BudgetExceeded):
        budget.check("analytics")


async def test_restart_survival_prior_spend_from_rows_blocks() -> None:
    # Simulates a restart: nothing recorded in-memory, but agent_runs already
    # holds today's spend at the cap.
    budget = _budget(sums={"analytics": Decimal("1.00")})
    await budget.refresh()
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.check("analytics")
    assert excinfo.value.spent == Decimal("1.00")


async def test_record_accumulates_on_top_of_refreshed_spend() -> None:
    budget = _budget(sums={"analytics": Decimal("0.90")})
    await budget.refresh()
    budget.check("analytics")  # 0.90 < 1.00
    budget.record("analytics", Decimal("0.10"))
    with pytest.raises(BudgetExceeded):
        budget.check("analytics")  # now at the cap


async def test_global_cap_blocks_across_agents() -> None:
    caps = {"analytics": Decimal("10.00"), "change-analyst": Decimal("10.00")}
    budget = _budget(
        sums={"change-analyst": Decimal("4.50"), "analytics": Decimal("0.50")},
        caps=caps,
        global_cap=Decimal("5.00"),
    )
    await budget.refresh()
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.check("analytics")  # under its own cap, but the day is spent
    assert excinfo.value.agent == "__global__"


async def test_refresh_replaces_stale_ledger() -> None:
    budget = _budget(sums={"analytics": Decimal("1.00")})
    await budget.refresh()
    with pytest.raises(BudgetExceeded):
        budget.check("analytics")
    # New day / rows cleared: refresh drops the old ledger.
    budget._aggregator.sums = {}  # type: ignore[attr-defined]
    await budget.refresh()
    budget.check("analytics")  # no raise

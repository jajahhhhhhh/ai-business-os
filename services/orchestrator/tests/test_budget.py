from decimal import Decimal

import pytest

from orchestrator.budget import BudgetExceeded, DailyBudget


def make_budget(**caps: str) -> DailyBudget:
    return DailyBudget(caps={k: Decimal(v) for k, v in caps.items()}, global_cap=Decimal("10.00"))


def test_spend_within_cap_passes() -> None:
    b = make_budget(analytics="1.00")
    b.record("analytics", Decimal("0.50"))
    b.check("analytics")  # no raise


def test_spend_over_cap_raises() -> None:
    b = make_budget(analytics="1.00")
    b.record("analytics", Decimal("1.01"))
    with pytest.raises(BudgetExceeded) as exc:
        b.check("analytics")
    assert exc.value.agent == "analytics"


def test_upcoming_cost_counts_toward_cap() -> None:
    b = make_budget(analytics="1.00")
    b.record("analytics", Decimal("0.90"))
    with pytest.raises(BudgetExceeded):
        b.check("analytics", upcoming_cost=Decimal("0.20"))


def test_unknown_agent_has_zero_cap() -> None:
    b = make_budget()
    with pytest.raises(BudgetExceeded):
        b.check("rogue", upcoming_cost=Decimal("0.01"))


def test_global_cap_enforced_across_agents() -> None:
    b = DailyBudget(caps={"a": Decimal("8.00"), "b": Decimal("8.00")}, global_cap=Decimal("10.00"))
    b.record("a", Decimal("6.00"))
    b.record("b", Decimal("5.00"))  # total 11 > 10
    with pytest.raises(BudgetExceeded) as exc:
        b.check("a")
    assert exc.value.agent == "__global__"


def test_agents_tracked_independently() -> None:
    b = make_budget(a="1.00", b="1.00")
    b.record("a", Decimal("0.99"))
    b.check("b")  # b unaffected by a's spend

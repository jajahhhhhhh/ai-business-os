"""Per-agent daily spend caps (NFR-4). Hard limits, checked before every LLM call."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


class BudgetExceeded(Exception):
    def __init__(self, agent: str, spent: Decimal, cap: Decimal) -> None:
        self.agent = agent
        self.spent = spent
        self.cap = cap
        super().__init__(f"{agent}: spent {spent} of daily cap {cap} USD")


@dataclass
class DailyBudget:
    """Tracks USD spend per agent per UTC day.

    In production the ledger is persisted to Redis (survives restarts within
    the day); this in-memory form has identical semantics and is used in tests
    and single-process runs.
    """

    caps: dict[str, Decimal]
    global_cap: Decimal = Decimal("10.00")
    _spent: dict[tuple[str, str], Decimal] = field(default_factory=dict)

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def spent(self, agent: str) -> Decimal:
        return self._spent.get((agent, self._today()), Decimal("0"))

    def total_spent(self) -> Decimal:
        today = self._today()
        return sum(
            (v for (agent, day), v in self._spent.items() if day == today),
            Decimal("0"),
        )

    def check(self, agent: str, upcoming_cost: Decimal = Decimal("0")) -> None:
        """Raise if the agent (or the whole system) has no budget headroom.

        An agent at (or over) its cap may not start new work — hence ``>=``,
        which also makes a zero cap mean "never runs".
        """
        cap = self.caps.get(agent, Decimal("0"))
        spent = self.spent(agent)
        if spent >= cap or spent + upcoming_cost > cap:
            raise BudgetExceeded(agent, spent, cap)
        total = self.total_spent()
        if total >= self.global_cap or total + upcoming_cost > self.global_cap:
            raise BudgetExceeded("__global__", total, self.global_cap)

    def record(self, agent: str, cost_usd: Decimal) -> None:
        key = (agent, self._today())
        self._spent[key] = self._spent.get(key, Decimal("0")) + cost_usd

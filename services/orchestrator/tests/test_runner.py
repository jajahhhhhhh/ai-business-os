import asyncio
from decimal import Decimal

from orchestrator.budget import DailyBudget
from orchestrator.contract import (
    AgentError,
    Context,
    FailurePolicy,
    ModelTier,
    Step,
    StepResult,
    Task,
)
from orchestrator.runner import Runner, RunRecord, RunStatus


class MemorySink:
    def __init__(self) -> None:
        self.records: list[RunRecord] = []

    async def save(self, record: RunRecord) -> None:
        self.records.append(record)


class MemoryEscalator:
    def __init__(self) -> None:
        self.calls: list[tuple[RunRecord, str]] = []

    async def escalate(self, record: RunRecord, reason: str) -> None:
        self.calls.append((record, reason))


class StubAgent:
    name = "stub"
    model_tier = ModelTier.LOW
    daily_budget_usd = Decimal("1.00")

    def __init__(self, fail_times: int = 0, retryable: bool = True) -> None:
        self._fail_times = fail_times
        self._retryable = retryable
        self.attempts = 0

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        return [Step(name="only", input={})]

    async def execute(self, step: Step) -> StepResult:
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise AgentError("boom", retryable=self._retryable)
        return StepResult(step=step, output={"ok": True}, cost_usd=Decimal("0.01"))

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE


def run(coro):
    return asyncio.run(coro)


def make_runner(caps: str = "1.00") -> tuple[Runner, MemorySink, MemoryEscalator]:
    sink, esc = MemorySink(), MemoryEscalator()
    budget = DailyBudget(caps={"stub": Decimal(caps)})
    return Runner(budget, sink, esc), sink, esc


def test_successful_run_is_traced() -> None:
    runner, sink, esc = make_runner()
    record = run(runner.run(StubAgent(), Task(kind="t", payload={}), Context([], [])))
    assert record.status is RunStatus.SUCCEEDED
    assert record.cost_usd == Decimal("0.01")
    assert sink.records == [record]
    assert esc.calls == []


def test_transient_failure_retries_then_succeeds(monkeypatch) -> None:
    import orchestrator.runner as runner_mod

    monkeypatch.setattr(runner_mod, "BACKOFF_BASE_S", 0.0)
    runner, _, esc = make_runner()
    agent = StubAgent(fail_times=2)
    record = run(runner.run(agent, Task(kind="t", payload={}), Context([], [])))
    assert record.status is RunStatus.SUCCEEDED
    assert agent.attempts == 3
    assert esc.calls == []


def test_exhausted_retries_escalate_and_park(monkeypatch) -> None:
    import orchestrator.runner as runner_mod

    monkeypatch.setattr(runner_mod, "BACKOFF_BASE_S", 0.0)
    runner, sink, esc = make_runner()
    record = run(runner.run(StubAgent(fail_times=99), Task(kind="t", payload={}), Context([], [])))
    assert record.status is RunStatus.PARKED
    assert len(esc.calls) == 1
    assert sink.records  # parked runs are still persisted — never silently dropped


def test_non_retryable_failure_does_not_retry(monkeypatch) -> None:
    import orchestrator.runner as runner_mod

    monkeypatch.setattr(runner_mod, "BACKOFF_BASE_S", 0.0)
    runner, _, _ = make_runner()
    agent = StubAgent(fail_times=99, retryable=False)
    record = run(runner.run(agent, Task(kind="t", payload={}), Context([], [])))
    assert agent.attempts == 1
    assert record.status is RunStatus.PARKED


def test_over_budget_blocks_before_any_execution() -> None:
    runner, _, esc = make_runner(caps="0.00")
    agent = StubAgent()
    record = run(runner.run(agent, Task(kind="t", payload={}), Context([], [])))
    assert record.status is RunStatus.OVER_BUDGET
    assert agent.attempts == 0
    assert len(esc.calls) == 1

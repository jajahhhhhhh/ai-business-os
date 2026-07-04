"""M4 agents against fake gateways: plan lists, additive enhancement,
planner fallback, memory dedupe, qa sampling + scoring, failure policy.

Requires the orchestrator package; skipped cleanly when absent
(dev: PYTHONPATH=services/orchestrator/src).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

pytest.importorskip("orchestrator")

from orchestrator.contract import AgentError, Context, FailurePolicy, ModelTier, Task  # noqa: E402

from src.application.agents.analytics import (  # noqa: E402
    DAILY_ENHANCE_HEADER_TH,
    AnalyticsAgent,
)
from src.application.agents.memory import MemoryAgent  # noqa: E402
from src.application.agents.planner import PlannerAgent  # noqa: E402
from src.application.agents.planning import PLAN_HEADER_TH, PlannerInputs  # noqa: E402
from src.application.agents.ports import EvalCandidate, SignalEvent  # noqa: E402
from src.application.agents.qa import QaAgent, select_for_eval  # noqa: E402
from src.application.agents.rubric import (  # noqa: E402
    RUBRIC_REPORT_QUALITY,
    RUBRIC_RUN_HEALTH,
)
from tests.fakes import (  # noqa: E402
    FakeAgentLlm,
    FakeAnalyticsGateway,
    FakeMemoryGateway,
    FakePlannerGateway,
    FakeQaGateway,
    ScriptedRng,
)

CTX = Context(memories=[], kb_chunks=[], locale="th")
BUDGET = Decimal("1.00")


async def _run_steps(agent, task: Task) -> list[dict]:
    """plan + execute all steps (what the Runner does, minus retries/budget)."""
    outputs = []
    for step in agent.plan(task, CTX):
        result = await agent.execute(step)
        outputs.append(result)
    return outputs


def _analytics(llm: FakeAgentLlm | None = None) -> tuple[AnalyticsAgent, FakeAnalyticsGateway]:
    gateway = FakeAnalyticsGateway()
    return AnalyticsAgent(gateway, llm or FakeAgentLlm(), daily_budget_usd=BUDGET), gateway


# -------------------------------------------------------------- plan() lists


def test_plan_step_lists_per_task_kind() -> None:
    analytics, _ = _analytics()
    assert [s.name for s in analytics.plan(Task(kind="daily-snapshot", payload={}), CTX)] == [
        "gather",
        "llm-enhance",
        "deliver",
    ]
    assert [s.name for s in analytics.plan(Task(kind="weekly-competitor", payload={}), CTX)] == [
        "gather",
        "llm-enhance",
        "deliver",
    ]

    memory = MemoryAgent(FakeMemoryGateway(), daily_budget_usd=BUDGET)
    assert [s.name for s in memory.plan(Task(kind="consolidate", payload={}), CTX)] == [
        "consolidate"
    ]
    assert [s.name for s in memory.plan(Task(kind="capture-signals", payload={}), CTX)] == [
        "scan",
        "capture",
    ]

    planner = PlannerAgent(FakePlannerGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET)
    assert [s.name for s in planner.plan(Task(kind="weekly-plan", payload={}), CTX)] == [
        "gather",
        "compose",
        "deliver",
    ]

    qa = QaAgent(FakeQaGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET)
    assert [s.name for s in qa.plan(Task(kind="evaluate", payload={}), CTX)] == [
        "sample",
        "evaluate",
    ]


def test_unknown_task_kind_raises_nonretryable_and_escalates() -> None:
    for agent in (
        _analytics()[0],
        MemoryAgent(FakeMemoryGateway(), daily_budget_usd=BUDGET),
        PlannerAgent(FakePlannerGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET),
        QaAgent(FakeQaGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET),
    ):
        with pytest.raises(AgentError) as excinfo:
            agent.plan(Task(kind="nonsense", payload={}), CTX)
        assert excinfo.value.retryable is False
        # §5.3: whatever survives the Runner's retries gets escalated + parked.
        assert agent.on_failure(excinfo.value) is FailurePolicy.ESCALATE


def test_agent_protocol_attributes() -> None:
    agent, _ = _analytics()
    assert agent.name == "analytics" and agent.model_tier is ModelTier.HIGH
    assert agent.daily_budget_usd == BUDGET
    assert MemoryAgent(FakeMemoryGateway(), daily_budget_usd=BUDGET).model_tier is ModelTier.LOW
    assert (
        PlannerAgent(FakePlannerGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET).model_tier
        is ModelTier.MID
    )
    assert QaAgent(FakeQaGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET).model_tier is (
        ModelTier.MID
    )


# ------------------------------------------------- analytics: additive LLM


async def test_daily_report_generates_unchanged_when_llm_off() -> None:
    agent, gateway = _analytics(FakeAgentLlm())  # empty script -> None
    outputs = await _run_steps(agent, Task(kind="daily-snapshot", payload={}))

    [delivered] = gateway.delivered
    assert delivered.kind == "daily"
    assert delivered.body == gateway.daily_draft  # draft untouched
    assert outputs[1].output == {"enhanced": False}
    assert outputs[1].cost_usd == Decimal("0")


async def test_daily_report_llm_enhancement_is_appended() -> None:
    llm = FakeAgentLlm("- เร่งยืนยันรายการโอน\n- ตามงวดเบิกไซต์ Chaweng")
    agent, gateway = _analytics(llm)
    outputs = await _run_steps(agent, Task(kind="daily-snapshot", payload={}))

    [delivered] = gateway.delivered
    assert delivered.body.startswith(gateway.daily_draft)  # additive, not replacing
    assert DAILY_ENHANCE_HEADER_TH in delivered.body
    assert "เร่งยืนยันรายการโอน" in delivered.body
    assert outputs[1].output["enhanced"] is True
    assert outputs[1].cost_usd == Decimal("0.0100")
    assert llm.calls[0]["tier"] == "high"
    assert gateway.daily_draft in llm.calls[0]["prompt"]  # figures fed to the LLM


async def test_weekly_report_uses_the_upgrade_path_not_the_agent_llm() -> None:
    llm = FakeAgentLlm("should not be used")
    agent, gateway = _analytics(llm)
    await _run_steps(agent, Task(kind="weekly-competitor", payload={}))

    [delivered] = gateway.delivered
    assert delivered.kind == "weekly"
    assert delivered.body.startswith(gateway.weekly_draft)
    assert gateway.upgrade_calls == [gateway.weekly_draft]
    assert llm.calls == []  # weekly enhancement goes through the ChangeAnalyst


# ----------------------------------------------------------------- planner


async def test_planner_llm_body_is_delivered_with_header_guard() -> None:
    llm = FakeAgentLlm("1) โฟกัสงานไฟฟ้า เพราะเลยกำหนดแล้ว")
    gateway = FakePlannerGateway(PlannerInputs(overdue_milestones=("Lipa — ไฟฟ้า",)))
    agent = PlannerAgent(gateway, llm, daily_budget_usd=BUDGET)
    await _run_steps(agent, Task(kind="weekly-plan", payload={}))

    [delivered] = gateway.delivered
    assert delivered.kind == "planning"
    assert delivered.body.startswith(PLAN_HEADER_TH)  # header enforced
    assert "โฟกัสงานไฟฟ้า" in delivered.body


async def test_planner_falls_back_to_rules_when_llm_off() -> None:
    inputs = PlannerInputs(overdue_milestones=("Lipa — ไฟฟ้า",), unconfirmed_count=2)
    gateway = FakePlannerGateway(inputs)
    agent = PlannerAgent(gateway, FakeAgentLlm(), daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="weekly-plan", payload={}))

    [delivered] = gateway.delivered
    assert delivered.body.startswith(PLAN_HEADER_TH)
    assert "1) เร่งตาม milestone" in delivered.body
    assert "2) ยืนยันรายการโอน" in delivered.body
    assert outputs[1].output["source"] == "fallback"


# ------------------------------------------------------------------ memory


async def test_memory_consolidate_wraps_use_case() -> None:
    gateway = FakeMemoryGateway()
    agent = MemoryAgent(gateway, daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="consolidate", payload={}))
    assert gateway.consolidate_calls == 1
    assert outputs[0].output == {"merged": 2, "expired": 1}


async def test_memory_capture_dedupes_by_subject_and_body() -> None:
    now = datetime.now(UTC)
    events = [
        SignalEvent("Villa B", "ลดราคา 20%", "critical", now),
        SignalEvent("Villa C", "โปรใหม่", "high", now),
        SignalEvent("Villa B", "ลดราคา 20%", "critical", now),  # dupe within batch
    ]
    gateway = FakeMemoryGateway(events=events, existing=[("Villa C", "โปรใหม่")])
    agent = MemoryAgent(gateway, daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="capture-signals", payload={}))

    assert outputs[0].output == {"events": 3}
    # Villa C already remembered; second Villa B deduped against the first.
    assert gateway.remembered == [("Villa B", "ลดราคา 20%")]
    assert outputs[1].output == {"created": 1, "skipped": 2}


# ---------------------------------------------------------------------- qa


def _candidate(
    agent: str,
    *,
    status: str = "succeeded",
    kind: str | None = None,
    body: str | None = None,
) -> EvalCandidate:
    return EvalCandidate(
        run_id=uuid.uuid4(),
        agent=agent,
        status=status,
        started_at=datetime.now(UTC),
        report_kind=kind,
        report_body=body,
    )


def test_sampling_takes_all_analytics_and_ten_percent_of_rest() -> None:
    analytics = [_candidate("analytics") for _ in range(3)]
    rest = [_candidate("change-analyst") for _ in range(4)]
    qa_runs = [_candidate("qa")]
    rng = ScriptedRng([0.05, 0.50, 0.09, 0.99])  # picks rest[0] and rest[2]

    selected = select_for_eval(analytics + rest + qa_runs, rng)

    assert [c.run_id for c in selected[:3]] == [c.run_id for c in analytics]
    assert {c.run_id for c in selected[3:]} == {rest[0].run_id, rest[2].run_id}
    assert all(c.agent != "qa" for c in selected)  # never self-evaluates


def test_sampling_caps_at_20_with_analytics_first() -> None:
    analytics = [_candidate("analytics") for _ in range(25)]
    rng = ScriptedRng([])
    selected = select_for_eval(analytics, rng)
    assert len(selected) == 20
    assert [c.run_id for c in selected] == [c.run_id for c in analytics[:20]]


GOOD_DAILY = (
    "สรุปประจำวัน 4 ก.ค. 2569\n[Lipa Noi]\n- ยอดเบิกรอจ่าย: 1 รายการ\n" "สิ่งสำคัญที่สุด: ไม่มีเรื่องเร่งด่วน"
)


async def test_qa_writes_deterministic_eval_when_llm_off() -> None:
    candidate = _candidate("analytics", kind="daily", body=GOOD_DAILY)
    gateway = FakeQaGateway([candidate])
    agent = QaAgent(gateway, FakeAgentLlm(), daily_budget_usd=BUDGET, rng=ScriptedRng([]))
    await _run_steps(agent, Task(kind="evaluate", payload={}))

    [eval_row] = gateway.evals
    assert eval_row["run_id"] == candidate.run_id
    assert eval_row["rubric"] == RUBRIC_REPORT_QUALITY
    assert eval_row["score"] == 100  # deterministic only, no blend


async def test_qa_blends_llm_score_50_50_for_analytics_reports() -> None:
    candidate = _candidate("analytics", kind="daily", body=GOOD_DAILY)
    gateway = FakeQaGateway([candidate])
    llm = FakeAgentLlm('{"score": 50, "notes": "อ่านยากเล็กน้อย"}')
    agent = QaAgent(gateway, llm, daily_budget_usd=BUDGET, rng=ScriptedRng([]))
    outputs = await _run_steps(agent, Task(kind="evaluate", payload={}))

    [eval_row] = gateway.evals
    assert eval_row["score"] == 75  # (100 + 50) / 2
    assert "LLM: อ่านยากเล็กน้อย" in eval_row["notes"]
    assert outputs[1].cost_usd == Decimal("0.0100")  # LLM usage booked on the step


async def test_qa_run_without_report_gets_run_health_rubric() -> None:
    ok = _candidate("analytics")
    parked = _candidate("analytics", status="parked")
    gateway = FakeQaGateway([ok, parked])
    agent = QaAgent(gateway, FakeAgentLlm(), daily_budget_usd=BUDGET, rng=ScriptedRng([]))
    await _run_steps(agent, Task(kind="evaluate", payload={}))

    by_run = {row["run_id"]: row for row in gateway.evals}
    assert by_run[ok.run_id]["rubric"] == RUBRIC_RUN_HEALTH
    assert by_run[ok.run_id]["score"] == 100
    assert by_run[parked.run_id]["score"] == 0

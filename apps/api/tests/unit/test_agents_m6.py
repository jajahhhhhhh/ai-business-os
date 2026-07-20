"""M6 marketing agents against fake gateways: plan lists, additive LLM
enhancement with deterministic fallbacks (seo/content), the deterministic
social calendar, and the escalate-on-failure policy.

Requires the orchestrator package; skipped cleanly when absent
(dev: PYTHONPATH=services/orchestrator/src).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("orchestrator")

from orchestrator.contract import AgentError, Context, FailurePolicy, ModelTier, Task  # noqa: E402

from src.application.agents.content import ContentAgent  # noqa: E402
from src.application.agents.marketing import (  # noqa: E402
    CALENDAR_HEADER_TH,
    CONTENT_HEADER,
    SEO_HEADER,
    THAI_SUMMARY_HEADER,
)
from src.application.agents.ports import ContentGap, SeoInputs  # noqa: E402
from src.application.agents.seo import SeoAgent  # noqa: E402
from src.application.agents.social import SocialAgent  # noqa: E402
from tests.fakes import FakeAgentLlm, FakeMarketingGateway, make_report_ref  # noqa: E402

CTX = Context(memories=[], kb_chunks=[], locale="th")
BUDGET = Decimal("1.00")
GAP = ContentGap(competitor_name="Villa B", summary="wellness promo", category="promo")


async def _run_steps(agent, task: Task) -> list:
    outputs = []
    for step in agent.plan(task, CTX):
        outputs.append(await agent.execute(step))
    return outputs


# -------------------------------------------------------------- plan + protocol


def test_plan_step_lists_and_protocol_attributes() -> None:
    seo = SeoAgent(FakeMarketingGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET)
    content = ContentAgent(FakeMarketingGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET)
    social = SocialAgent(FakeMarketingGateway(), daily_budget_usd=BUDGET)

    assert [s.name for s in seo.plan(Task(kind="seo-brief", payload={}), CTX)] == [
        "gather",
        "compose",
        "deliver",
    ]
    assert [s.name for s in content.plan(Task(kind="content-draft", payload={}), CTX)] == [
        "gather",
        "draft",
        "deliver",
    ]
    assert [s.name for s in social.plan(Task(kind="content-calendar", payload={}), CTX)] == [
        "gather",
        "schedule",
        "deliver",
    ]

    assert (seo.name, seo.model_tier) == ("seo", ModelTier.MID)
    assert (content.name, content.model_tier) == ("content", ModelTier.HIGH)
    assert (social.name, social.model_tier) == ("social", ModelTier.LOW)


def test_unknown_task_kind_raises_nonretryable_and_escalates() -> None:
    for agent in (
        SeoAgent(FakeMarketingGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET),
        ContentAgent(FakeMarketingGateway(), FakeAgentLlm(), daily_budget_usd=BUDGET),
        SocialAgent(FakeMarketingGateway(), daily_budget_usd=BUDGET),
    ):
        with pytest.raises(AgentError) as excinfo:
            agent.plan(Task(kind="nonsense", payload={}), CTX)
        assert excinfo.value.retryable is False
        assert agent.on_failure(excinfo.value) is FailurePolicy.ESCALATE


# ------------------------------------------------------------------------ seo


async def test_seo_llm_brief_is_delivered_with_header_guard() -> None:
    llm = FakeAgentLlm("target: private pool villa koh samui")  # no header in text
    gateway = FakeMarketingGateway(seo_inputs=SeoInputs(content_gaps=(GAP,)))
    agent = SeoAgent(gateway, llm, daily_budget_usd=BUDGET)
    await _run_steps(agent, Task(kind="seo-brief", payload={}))

    [delivered] = gateway.delivered
    assert delivered.kind == "seo" and delivered.lang == "en"
    assert delivered.body.startswith(SEO_HEADER)  # header enforced
    assert delivered.line_sent is False  # internal artifact, not pushed
    assert llm.calls[0]["tier"] == "mid"


async def test_seo_falls_back_to_rules_when_llm_off() -> None:
    gateway = FakeMarketingGateway(seo_inputs=SeoInputs(content_gaps=(GAP,)))
    agent = SeoAgent(gateway, FakeAgentLlm(), daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="seo-brief", payload={}))

    [delivered] = gateway.delivered
    assert delivered.body.startswith(SEO_HEADER)
    assert "Villa B" in delivered.body  # gap flowed into the fallback brief
    assert outputs[1].output["source"] == "fallback"


# -------------------------------------------------------------------- content


async def test_content_drafts_from_recent_seo_brief() -> None:
    brief = make_report_ref(f"{SEO_HEADER} — 2026-W30\nprivate pool villa koh samui")
    gateway = FakeMarketingGateway(reports={"seo": [brief]})
    llm = FakeAgentLlm("Working title: Quiet Mornings\nbody\n\nสรุปภาษาไทย\nดราฟต์")
    agent = ContentAgent(gateway, llm, daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="content-draft", payload={}))

    assert outputs[0].output == {"briefs": 1}
    [delivered] = gateway.delivered
    assert delivered.kind == "content" and delivered.lang == "en"
    assert delivered.body.startswith(CONTENT_HEADER)  # header enforced
    assert brief.body in llm.calls[0]["prompt"]  # brief fed to the model
    assert llm.calls[0]["tier"] == "high"


async def test_content_fallback_when_llm_off_has_thai_summary() -> None:
    brief = make_report_ref(f"{SEO_HEADER} — 2026-W30\nboutique villa koh samui")
    gateway = FakeMarketingGateway(reports={"seo": [brief]})
    agent = ContentAgent(gateway, FakeAgentLlm(), daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="content-draft", payload={}))

    [delivered] = gateway.delivered
    assert delivered.body.startswith(CONTENT_HEADER)
    assert THAI_SUMMARY_HEADER in delivered.body
    assert outputs[1].output["source"] == "fallback"


# --------------------------------------------------------------------- social


async def test_social_builds_calendar_from_drafts_and_pushes_to_line() -> None:
    draft = make_report_ref(f"{CONTENT_HEADER} — 2026-W30\nWorking title: Slow Sundays")
    gateway = FakeMarketingGateway(reports={"content": [draft]})
    agent = SocialAgent(gateway, daily_budget_usd=BUDGET)
    outputs = await _run_steps(agent, Task(kind="content-calendar", payload={}))

    assert outputs[0].output == {"drafts": 1}
    [delivered] = gateway.delivered
    assert delivered.kind == "content-calendar" and delivered.lang == "th"
    assert delivered.body.startswith(CALENDAR_HEADER_TH)
    assert "Slow Sundays" in delivered.body
    assert delivered.line_sent is True  # owner gets the calendar to approve

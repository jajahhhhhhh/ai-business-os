"""Trigger name routing + jobs DISPATCHABLE registry (M4)."""

from __future__ import annotations

import pytest

from src.application.errors import NotFoundError
from src.interfaces.routers.agents import TRIGGERS, resolve_trigger
from src.interfaces.routers.jobs import DISPATCHABLE


def test_trigger_names_route_to_the_right_agent_and_task() -> None:
    assert resolve_trigger("analytics-daily") == ("analytics", "daily-snapshot")
    assert resolve_trigger("analytics-weekly") == ("analytics", "weekly-competitor")
    assert resolve_trigger("planner") == ("planner", "weekly-plan")
    assert resolve_trigger("memory-consolidate") == ("memory", "consolidate")
    assert resolve_trigger("memory-capture") == ("memory", "capture-signals")
    assert resolve_trigger("qa-evaluate") == ("qa", "evaluate")


def test_trigger_registry_matches_the_web_contract_exactly() -> None:
    # apps/web/lib/types.ts AgentTaskName — keep in lockstep.
    assert set(TRIGGERS) == {
        "analytics-daily",
        "analytics-weekly",
        "planner",
        "memory-consolidate",
        "memory-capture",
        "qa-evaluate",
        "customer-discovery",
    }


def test_unknown_trigger_name_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        resolve_trigger("rm-rf-agent")


def test_dispatchable_registry_covers_agent_jobs_with_args() -> None:
    # Legacy task names stay stable (their bodies route through agents now).
    assert DISPATCHABLE["send_daily_snapshot"] == ("src.worker.send_daily_snapshot", ())
    assert DISPATCHABLE["weekly_competitor_report"] == (
        "src.worker.weekly_competitor_report",
        (),
    )
    assert DISPATCHABLE["consolidate_memories"] == ("src.worker.consolidate_memories", ())
    # New agent jobs dispatch the generic runner with (agent, task_kind) args.
    assert DISPATCHABLE["memory_capture_signals"] == (
        "src.worker.run_agent_task",
        ("memory", "capture-signals"),
    )
    assert DISPATCHABLE["planner_weekly_plan"] == (
        "src.worker.run_agent_task",
        ("planner", "weekly-plan"),
    )
    assert DISPATCHABLE["qa_evaluate"] == ("src.worker.run_agent_task", ("qa", "evaluate"))

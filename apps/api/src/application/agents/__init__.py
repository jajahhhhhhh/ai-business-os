"""M4 agents (ARCHITECTURE.md §5): analytics, planner, memory, qa.

Each agent module implements the orchestrator Agent protocol (plan/execute/
on_failure) over application-level gateway ports (ports.py); infrastructure/
agent_runtime.py supplies the SQL/LINE/LLM implementations and the shared
run_agent() entrypoint.

The orchestrator package is a real dependency of these modules (installed in
the image; PYTHONPATH=services/orchestrator/src in dev). The pure helpers
(planning.py, rubric.py, ports.py) deliberately do NOT import it so their
unit tests run anywhere.
"""

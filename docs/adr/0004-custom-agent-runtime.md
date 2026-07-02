# ADR-0004: Custom lightweight agent runtime

**Status:** accepted · **Date:** 2026-07-02

## Context
Agent frameworks (CrewAI, AutoGen, LangChain agents) churn quickly, hide token spend, and obscure control flow — unacceptable when every baht of LLM spend needs a budget line.

## Decision
A ~500-line orchestrator (services/orchestrator): explicit Agent protocol (plan/execute/on_failure), per-agent daily USD caps enforced before every call, every run traced to agent_runs, model-tier routing with provider failover.

## Consequences
We own retry/rate-limit/budget code (~small, well-tested). No framework lock-in; agents are plain Python.

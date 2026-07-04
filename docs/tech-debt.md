# Technical Debt Register

Groomed monthly (Planner agent + owner). Every entry has a trigger for repayment —
debt without a trigger is a wish, not a plan.

| ID | Debt | Why accepted | Repay when |
|---|---|---|---|
| TD-1 | Jobs `:run` dispatches only the two M1 tasks (bank sync, daily snapshot); other jobs record-only | Generic task registry is M4 orchestrator scope | M4 orchestrator milestone |
| TD-2 | In-memory rate limiter in ComplianceGate | Single worker process in M0 | Second worker process, or M3 collector sweep goes multi-process |
| TD-3 | RSS parser is stdlib ElementTree, not feedparser | Zero-dep; feeds curated by us | First malformed feed in production |
| TD-4 | <a id="pricing"></a>Model pricing table hand-maintained in router.py | No pricing API worth the dependency | Pricing drift found by weekly CI check |
| TD-5 | Auth: dev-mode bypass + API keys only; no Auth.js session flow | M0 has no UI writes needing user identity | M1 renovation module UI |
| TD-6 | Locale toggle in dashboard is visual only | Thai-only owner today | First non-Thai user |
| TD-7 | KB hybrid search fuses with RRF only — no cross-encoder reranker (ARCHITECTURE.md §10 plans bge-reranker over the top-20) | Reranker adds a second heavyweight model download + inference latency; RRF alone is adequate for M2's corpus size (tens of documents) | KB exceeds ~1k documents, or owner reports irrelevant top-5 results |
| TD-8 | TD-1 partially repaid in M4: jobs `:run` + `/v1/agents/{name}:trigger` dispatch through a (task, args) registry, but it is still a hand-maintained dict in `routers/jobs.py`/`routers/agents.py`, not a DB-driven task registry | Six agent tasks don't justify a registry table; the dicts are unit-tested against the web contract | Agent roster grows past Phase B (SEO/Content/Social agents) |
| TD-9 | LLM provider failover is Anthropic-only: ModelRouter's openai candidates are skipped with a debug log (`apps/api/src/infrastructure/llm_client.py`) because no OpenAI key/config exists in Settings | ADR-7 failover needs a second provider account + pricing plumbing; single-provider risk accepted at M4 scale | First Anthropic outage that costs a daily report, or Phase B content volume |
| TD-10 | services/orchestrator is a PYTHONPATH/image dependency of apps/api, not a declared package dependency (no monorepo workspace tooling); orchestrator-dependent tests `pytest.importorskip` it, and worker/report paths degrade to deterministic fallbacks when it is absent | uv/pip path deps across the monorepo add lockfile friction; the API Dockerfile installs it anyway | Monorepo adopts workspace tooling, or a second Python service needs orchestrator |
| TD-11 | QA joins reports to runs via `reports.generated_by_run_id`, stamped post-run by `run_agent` (best-effort UPDATE) rather than transactionally with the run | The RunRecord id is only known after the orchestrator Runner finishes; earlier stamping means changing the orchestrator contract (out of M4 scope) | Orchestrator contract revision, or missed report evals observed in agent_evals |

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

# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

### Fixed — M6 content fallback title
- The Content agent's deterministic (no-LLM) fallback picked an SEO brief's
  `Site:` metadata line as the working title, which then propagated into every
  Social calendar slot. It now extracts the first **target keyword** from the
  brief (e.g. "Private Pool Villa Koh Samui"), falling back to the top brand
  theme. Surfaced by a live pipeline run; regression-tested.

### Added — M6 Marketing (Content & SEO)
- Three budget-capped agents forming a content pipeline over the `reports`
  table, each additive-LLM with a deterministic fallback (a brief/draft/calendar
  is always produced): **SEO** (tier MID, `seo-brief`) seeds evergreen Koh Samui
  keyword themes and layers recent high/critical competitor content/promo moves
  into an English brief (`kind='seo'`); **Content** (tier HIGH, `content-draft`)
  drafts English marketing copy + a Thai owner summary from the latest briefs
  (`kind='content'`, a draft for approval); **Social** (tier LOW,
  `content-calendar`, deterministic) spreads recent drafts across a 4-week
  calendar (`kind='content-calendar'`) and pushes it to LINE for approval — the
  M6 gate deliverable.
- Weekly beat schedule (SEO Tue 09:00 → Content Wed 09:00 → Calendar Thu 09:00),
  manual triggers (`POST /v1/agents/{seo,content,social}:trigger`), dispatchable
  jobs, and dashboard trigger buttons; per-agent daily caps in `AGENT_BUDGETS`.
- Brand guide + versioned prompt templates (`packages/prompts/{seo,content}`).
  Postiz/Ahrefs stay MCPs consumed as-is (§7) — the backend produces the
  briefs/calendar; publishing is not re-wrapped in the API.

### Added — Deployment readiness
- Terraform module for the production VPS (Hetzner CPX31, Singapore, hardened
  cloud-init: key-only SSH, UFW, fail2ban, Docker) + first-deploy runbook
  covering DNS → secrets → seed → basic auth → smoke test → backups.
- `scripts/gen-secrets.sh` (strong random production .env) and
  `scripts/smoke.sh` (post-deploy verification incl. live snapshot generation);
  `make seed / api-key / smoke`.
- Interim prod auth (TD-5): `AUTH_MODE=proxy` trusts keyless requests as the
  owner strictly behind Caddy basic_auth (boot warning; Bearer keys still
  validated); `python -m src.create_api_key` mints scoped keys for MCP/automation.

### Fixed — deploy blockers found in pre-deploy audit
- Web client bundle baked `localhost:8000`: `NEXT_PUBLIC_API_URL` is now a
  build arg (bake verified by inspecting built chunks).
- GlitchTip pointed at a database Postgres never created (first-boot initdb
  script added).
- Prometheus metrics endpoint was publicly reachable through Caddy (now 403
  from outside; scraped internally only).

### Added — M5 Lead discovery
- Compliant lead sources: Reddit via the official API only (app-only OAuth,
  honest User-Agent, `skipped: no credentials` — never HTML scraping) and RSS
  feeds; registry endpoints with blocklist refusal at registration; three
  Samui subreddits seeded.
- Customer Discovery agent (tier LOW, budget-capped): keyword prefilter (zero
  LLM spend on noise) → batched LLM classify/score with deterministic §8.3
  fallback → dedup (exact hash + embedding ≥0.92 → "reobserved") → leads with
  score features, Thai follow-up suggestions, and full event timelines.
- PDPA: contact = platform/handle/url only, Fernet-encrypted at rest
  (`PII_ENCRYPTION_KEY`); 18-month inactivity anonymization + weekly greedy
  embedding clustering (Sun beats).
- CRM board: 5-stage pipeline with allowed-transition advances, kind/score/q
  filters, lead detail page (decrypted contact, suggestion copy, score
  features, timeline), source management UI.

### Added — M4 Agent runtime + QA
- Orchestrator wired into production: agent runs execute through the traced,
  budgeted Runner (retry → escalate to LINE → park, never silently dropped);
  budgets survive restarts by seeding from `agent_runs` spend; per-agent USD
  caps via `AGENT_BUDGETS_JSON`.
- Agents live: **analytics** (daily snapshot + weekly competitor report now
  agent-generated with additive LLM "คำแนะนำวันนี้"/executive sections),
  **memory** (consolidation + capture of high-severity competitor signals),
  **planner** (Monday "แผนสัปดาห์" top-3 focus report with rule-based
  fallback), **qa** (Sunday eval sampling — deterministic rubric checks
  blended with LLM scoring — written to `agent_evals`).
- Prompts moved to versioned Jinja2 templates in `packages/prompts` (with
  in-code fallbacks and golden regression cases exercised in CI).
- Cost dashboard: per-agent today budget bars, 7-day stacked cost chart,
  eval scores, manual agent triggers; `GET /v1/agents/costs`, `/evals`,
  `POST /v1/agents/{name}:trigger` (§11 complete except /v1/kb upload UI
  parity — kb endpoints shipped in M2).

### Added — M3 Competitor intelligence
- Competitor registry with per-competitor monitored sources (website/RSS);
  Facebook/Airbnb/Booking/Agoda URLs refused at registration with a Thai
  §8.4 policy explanation (compliance gate, structurally enforced).
- Daily sweep (06:00 Asia/Bangkok + per-competitor "ตรวจตอนนี้"): compliance-
  gated fetch → text normalization → content-hash diffing → snapshot archive
  in MinIO → change events with category/severity.
- ChangeAnalyst: Haiku-tier Thai diff summaries and severity classification,
  hard daily USD budget from `agent_runs` spend; over budget or key absent →
  deterministic keyword fallback. Every LLM attempt traced to `agent_runs`.
- Weekly Thai competitor report (Mon 08:00 + on-demand): grouped change
  digest upgraded with "บทวิเคราะห์" and "3 สิ่งที่ควรทำ", stored + LINE push.
- คู่แข่ง dashboard rebuild: add/manage competitors and sources, sweep
  status chips, global change feed with severity filter, weekly report button.
- API Docker image now builds from repo root and bundles the shared
  compliance-gated collectors package; ruff pinned <0.9 and all Python
  packages `ruff format`-normalized (CI formatting gate now actually passes).

### Added — M2 Knowledge base + memory
- Document ingestion pipeline: upload (25 MB cap) → MinIO original → text
  extraction (PDF via pdfplumber, Thai OCR fallback via Tesseract, images,
  plain text with TIS-620 fallback) → Thai-aware chunking (~512-token target)
  → Meilisearch keyword index + Qdrant bge-m3 embeddings. Celery-dispatched
  with in-process fallback when the broker is down.
- Hybrid search (`GET /v1/kb/search`): keyword + semantic fused with RRF;
  degrades to keyword-only (flagged) when the vector side is unavailable.
- Long-term memory (`/v1/memory`): remember/recall/consolidate — semantic +
  ILIKE recall fusion, Sunday 03:00 consolidation task merging near-duplicates
  (embedding similarity ≥ 0.92, never across kinds) and expiring stale rows.
- MCP servers `knowledge-base` (search, ingest_document, get_document,
  list_documents) and `memory` (remember, recall, consolidate).
- คลังความรู้ dashboard page: hybrid search with mode toggle, upload with
  ingest-status tracking, document table with OCR/embedding indicators.
- Embeddings ship as an optional `[ml]` extra (torch-free installs keep
  working); bge-m3 weights cached in the shared `hf_models` compose volume.

### Added — M1 Renovation module
- Thai bank-alert ingestion: parser for KBank/SCB/Bangkok Bank/Krungsri/KTB
  e-mail formats (Buddhist-era dates, satang, OTP/marketing rejection),
  dedup by content hash, automatic matching against pending contractor draws,
  and confirm/ignore/manual-match reconciliation endpoints + การเงิน dashboard page.
- Gmail auto-sync (2-hourly Celery task, read-only scope, skips when
  unconfigured) with one-time OAuth helper `apps/api/scripts/gmail_authorize.py`.
- Daily Thai snapshot (07:30 Asia/Bangkok): per-site pending draws, week's
  payments, awaiting-confirmation count, overdue milestones, top action —
  stored inline in `reports` and pushed to LINE when configured.
- Renovation write flows: quotations, draws (pay with confirm step),
  milestones CRUD with overdue highlighting; site list/summary responses
  aligned to the dashboard contract; money fields serialize as JSON numbers.
- Celery worker + beat (`src/worker.py`) wired into the compose stack;
  `POST /v1/jobs/{id}:run` now dispatches the M1 tasks.
- Idempotent seed (`python -m src.seed`): owner user, Lipa Noi + Chaweng,
  MR.HOME.

### Added — M0 Foundation
- M0 Foundation scaffold: monorepo layout, Docker Compose stack (PostgreSQL, Redis,
  Qdrant, Meilisearch, MinIO, Caddy, Prometheus, Grafana, GlitchTip).
- FastAPI core API with Clean Architecture layout, health/metrics endpoints,
  core database schema (Alembic migration 0001) covering identity, renovation
  (Phase A), leads, competitors, collection, knowledge base, memory, agents, audit.
- Next.js 15 dashboard shell (Thai-first): overview, renovation, leads, competitors,
  knowledge base, agents, reports, settings routes.
- Agent runtime skeleton: agent contract, model-tier router, per-agent budget
  enforcement, run tracing to `agent_runs`.
- Compliance-gated collector framework: robots.txt check, per-source rate limiting,
  ToS policy registry — disallowed sources are structurally unfetchable.
- CI pipeline (GitHub Actions): lint, typecheck, unit + integration tests, image builds.

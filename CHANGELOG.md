# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

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

# MCP servers

Each server is an independent FastMCP (Python) package exposing one internal
capability over stdio + SSE (§6 of the architecture). Third-party MCPs
(Gmail, Calendar, Drive, Ahrefs, Canva, Postiz) are consumed as-is — never re-wrapped.

| Server | Status | Backing store | Tools |
|---|---|---|---|
| `renovation` | planned (M2.5) | Postgres | draws_outstanding, spend_by_category, milestone_status |
| [`knowledge-base`](knowledge-base/) | ✅ shipped | Meili + Qdrant + MinIO via `/v1/kb` | search (hybrid), ingest_document, get_document, list_documents |
| [`memory`](memory/) | ✅ shipped | Postgres + Qdrant via `/v1/memory` | remember, recall, consolidate |
| `competitor-intel` | M3 | Postgres | list_competitors, get_snapshot_diff, get_report |
| `automation` | M4 | Celery API | list_jobs, trigger_job, job_status |
| `analytics` | M4 | Postgres | kpi_query, spend_by_site |
| `line-notify` | M4 | LINE Messaging API | send_message, send_report |
| `crm` | M5 | Postgres | search_leads, get_lead, update_stage, log_touch |

Conventions (enforced by review):
- Package name `mcp-<server>`, entrypoint `python -m mcp_<server>`.
- Auth: scoped API key via `AIBOS_API_KEY` env var; read-only scopes by default.
- Every server ships a README with a tool schema table and example calls.

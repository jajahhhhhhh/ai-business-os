# Architecture Decision Records

Summary table lives in [ARCHITECTURE.md §4](../ARCHITECTURE.md). One file per decision;
new decisions get the next number. Status: accepted | superseded-by-NNN.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-single-vps-docker-compose.md) | Single VPS + Docker Compose (K8s-ready images) | accepted |
| [0002](0002-meilisearch-over-elasticsearch.md) | Meilisearch over Elasticsearch | accepted |
| [0003](0003-celery-over-temporal.md) | Celery + Redis over Temporal | accepted |
| [0004](0004-custom-agent-runtime.md) | Custom lightweight agent runtime over CrewAI/AutoGen | accepted |
| [0005](0005-auth-strategy.md) | Auth.js (web) + API keys (services) | accepted |
| [0006](0006-api-first-data-collection.md) | API-first data collection; scraping only where ToS-permitted | accepted |
| [0007](0007-llm-provider-strategy.md) | Claude primary, OpenAI fallback, bge-m3 local embeddings | accepted |
| [0008](0008-glitchtip-over-sentry.md) | GlitchTip over Sentry SaaS | accepted |
| [0009](0009-minio-over-cloud-s3.md) | MinIO + off-site B2 backup over cloud S3 | accepted |

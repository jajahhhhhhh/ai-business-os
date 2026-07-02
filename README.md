# AI Business OS

AI-powered operating system for a Koh Samui property renovation → boutique villa rental business
(howtoniksen.com). Finds leads, monitors competitors, builds business intelligence, automates
reports (Thai-first), and recommends decisions backed by data — operable by one person.

Full architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Monorepo layout

| Path | What it is |
|---|---|
| `apps/web` | Next.js 15 dashboard (Thai-first UI) |
| `apps/api` | FastAPI core API — auth, business logic, system of record |
| `services/orchestrator` | Agent runtime — budgets, tracing, model-tier routing |
| `services/collectors` | Compliance-gated data collectors (robots.txt, ToS registry, rate limits) |
| `packages/prompts` | Versioned prompt templates (Jinja2), per agent, per language |
| `mcp-servers` | MCP servers exposing internal capabilities |
| `infra/compose` | Docker Compose stack (dev + prod) |
| `docs` | Architecture, ADRs, runbooks |

## Quick start (development)

Prerequisites: Docker + Compose v2, Node 20+, Python 3.12+.

```bash
cp infra/compose/.env.example infra/compose/.env   # then fill secrets
make dev            # start data services (postgres, redis, qdrant, meilisearch, minio)
make api-dev        # FastAPI on :8000 (docs at /docs)
make web-dev        # Next.js on :3000
```

## Production (single VPS)

```bash
make deploy         # docker compose -f infra/compose/docker-compose.yml --profile prod up -d
```

Deployment pipeline, rollback, and restore procedures: [docs/runbooks/](docs/runbooks/).

## Testing

```bash
make test           # api unit + integration, web lint + typecheck + unit
```

## Status

Milestone **M0 — Foundation** (see §18 of the architecture doc for the roadmap).
Changes: [CHANGELOG.md](CHANGELOG.md). Decisions: [docs/adr/](docs/adr/).

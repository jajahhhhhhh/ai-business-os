COMPOSE := docker compose -f infra/compose/docker-compose.yml --env-file infra/compose/.env

.PHONY: dev dev-down deploy api-dev web-dev test test-api test-web lint migrate backup seed api-key smoke

dev: ## Start data services only (develop api/web on host)
	$(COMPOSE) --profile data up -d

dev-down:
	$(COMPOSE) --profile data down

deploy: ## Full production stack
	$(COMPOSE) --profile prod up -d --build

api-dev:
	cd apps/api && uvicorn src.main:app --reload --port 8000

web-dev:
	cd apps/web && npm run dev

migrate:
	cd apps/api && alembic upgrade head

test: test-api test-web

test-api:
	cd apps/api && python -m pytest tests/unit -q && python -m pytest tests/integration -q

test-web:
	cd apps/web && npm run lint && npx tsc --noEmit

lint:
	cd apps/api && ruff check src tests && ruff format --check src tests
	cd apps/web && npm run lint

backup: ## Manual backup (also runs nightly via cron on VPS)
	bash infra/backup/backup.sh

seed: ## Owner user, sites, contractor, default lead sources (idempotent)
	$(COMPOSE) run --rm api python -m src.seed

api-key: ## Mint a scoped API key: make api-key NAME=mcp-kb
	$(COMPOSE) run --rm api python -m src.create_api_key $(NAME)

smoke: ## Post-deploy verification: make smoke DOMAIN=os.example.com
	DOMAIN=$(DOMAIN) bash scripts/smoke.sh

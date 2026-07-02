# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- deps + app
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Runtime dependencies pinned in lockstep with pyproject.toml [project.dependencies].
# Listed explicitly so this layer stays cached until the dep set actually changes.
COPY pyproject.toml ./
RUN pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30" \
    "alembic>=1.14" \
    "pydantic>=2.9" \
    "pydantic-settings>=2.6" \
    "structlog>=24.4" \
    "prometheus-client>=0.21" \
    "celery[redis]>=5.4" \
    "httpx>=0.27"

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 apiuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER apiuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/v1/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

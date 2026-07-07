# syntax=docker/dockerfile:1
# Build context is the REPO ROOT (compose: context ../.., dockerfile apps/api/Dockerfile)
# so the image can install the shared services/collectors package (M3 sweep).

# ---------------------------------------------------------------- deps + app
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Runtime dependencies pinned in lockstep with pyproject.toml [project.dependencies].
# Listed explicitly so this layer stays cached until the dep set actually changes.
COPY apps/api/pyproject.toml ./
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
    "httpx>=0.27" \
    "python-multipart>=0.0.12" \
    "boto3>=1.35" \
    "qdrant-client>=1.12" \
    "jinja2>=3.1" \
    "cryptography>=43"

# M2 document parsing (mirrors pyproject [project.optional-dependencies].parsing).
RUN pip install \
    "pdfplumber>=0.11" \
    "pytesseract>=0.3.13" \
    "pdf2image>=1.17"

# bge-m3 embeddings (pyproject extra `ml`). INSTALL_ML=false builds a slim
# image; the KB then degrades to keyword-only search (NFR-1).
ARG INSTALL_ML=true
RUN if [ "$INSTALL_ML" = "true" ]; then pip install "sentence-transformers>=3.2"; fi

# Shared monorepo libraries: compliance-gated collectors (§8.4, M3 sweep) and
# the agent runtime (§5, M4 orchestrator).
COPY services/collectors /tmp/collectors
COPY services/orchestrator /tmp/orchestrator
RUN pip install /tmp/collectors /tmp/orchestrator && rm -rf /tmp/collectors /tmp/orchestrator

COPY apps/api/src ./src
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
# Versioned prompt templates (packages/prompts) — loader default /app/prompts.
COPY packages/prompts ./prompts

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim

# tesseract-ocr(-tha) + poppler-utils: OCR and PDF rasterization binaries for
# the M2 parsing pipeline (pytesseract / pdf2image call them at runtime).
# upgrade first: fixed CVEs land in the debian security repo faster than
# python:*-slim base-image rebuilds (keeps the trivy CI gate green honestly).
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        curl tesseract-ocr tesseract-ocr-tha poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 apiuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
# COPY preserves source file modes. When the build context originates on a
# filesystem without Unix permissions (e.g. ExFAT via rsync), files can arrive
# mode 0700 owned by root and be unreadable to the non-root runtime user. Force
# world-readable so the app can always read its own code/config.
RUN chmod -R a+rX /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER apiuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/v1/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

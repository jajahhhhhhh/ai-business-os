# ADR-0002: Meilisearch over Elasticsearch

**Status:** accepted · **Date:** 2026-07-02

## Context
Keyword search must handle Thai tokenization on an 8 GB VPS shared with ~12 other services. Elasticsearch needs 2–4 GB heap alone.

## Decision
Meilisearch: ~100 MB RSS, sub-50 ms queries, built-in Thai support.

## Consequences
No aggregations/analytics queries — those belong in Postgres anyway. Re-index is cheap (source of truth is Postgres + MinIO).

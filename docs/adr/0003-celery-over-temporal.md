# ADR-0003: Celery + Redis over Temporal

**Status:** accepted · **Date:** 2026-07-02

## Context
Workflows are cron-driven sweeps and short chains (<20 steps). Temporal adds a server cluster, a new programming model, and more RAM.

## Decision
Celery + Celery Beat with Redis broker. Retries with backoff, task routing per queue.

## Consequences
No durable long-running workflow state. Revisit (recorded trigger: any workflow exceeding ~20 chained steps or needing human-in-the-loop pauses > 1 day).

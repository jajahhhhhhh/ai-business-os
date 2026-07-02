# ADR-0008: GlitchTip over Sentry SaaS

**Status:** accepted · **Date:** 2026-07-02

## Context
Error tracking is required (NFR-5) but Sentry SaaS per-event pricing is unpredictable with noisy collectors.

## Decision
Self-hosted GlitchTip: Sentry-SDK-compatible, one container + shared Postgres/Redis.

## Consequences
We patch/upgrade it ourselves. If it becomes a burden, swap to Sentry SaaS — SDKs unchanged.

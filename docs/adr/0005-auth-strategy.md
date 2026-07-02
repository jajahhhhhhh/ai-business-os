# ADR-0005: Auth.js (web) + API keys (services)

**Status:** accepted · **Date:** 2026-07-02

## Context
Single-tenant, one owner today, possible staff later. Per-MAU vendor pricing (Clerk) buys nothing here.

## Decision
Auth.js on the dashboard (email magic-link + TOTP), scoped API keys (hashed at rest) for services and MCP servers. RBAC roles owner/staff/readonly seeded from day one; enforced in the API dependency layer.

## Consequences
We manage magic-link email delivery. M0 ships the API-key seam only; Auth.js lands with the first protected UI (M1).

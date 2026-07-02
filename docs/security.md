# Security Checklist (OWASP ASVS L1 scope)

Status legend: ✅ implemented · 🔜 milestone-gated · Every 🔜 names its milestone.

## Authentication & sessions
- ✅ API keys hashed at rest (SHA-256), scoped, expirable (`api_keys` table)
- 🔜 M1: Auth.js email magic-link + TOTP for dashboard (ADR-0005)
- ✅ Dev-mode auth bypass is impossible when `ENV=prod` (checked at startup)

## Access control
- ✅ RBAC roles owner/staff/readonly in schema; enforced in API dependency layer
- ✅ MCP servers require scoped API keys

## Input/output
- ✅ Pydantic validation on every request body/query
- ✅ RFC 9457 problem+json errors — no stack traces to clients
- ✅ React default encoding; no `dangerouslySetInnerHTML`

## Transport & infrastructure
- ✅ Caddy: TLS everywhere, HSTS, nosniff, frame-deny, no Server header
- ✅ Only 80/443 exposed; all data services bound to 127.0.0.1 / internal network
- ✅ VPS: UFW default-deny, SSH key-only, fail2ban (runbook: deploy.md)

## Data
- 🔜 M5: pgcrypto for `leads.contact_json` (PII lands with lead discovery)
- ✅ MinIO credentials scoped; off-site backups age-encrypted
- ✅ PDPA retention: leads anonymized after 18 months inactivity (§8.5) — job ships with M5

## Secrets
- ✅ No secrets in code or images; env-only via pydantic-settings
- ✅ SOPS + age for at-rest secrets in repo; plaintext only on VPS (mode 600)

## Auditing & monitoring
- ✅ `audit_log` rows for all mutations; agent outbound messages approval-gated
- ✅ Dependency scanning in CI (pip-audit / npm audit / trivy) — weekly schedule
- 🔜 M4: per-agent spend alerts to LINE

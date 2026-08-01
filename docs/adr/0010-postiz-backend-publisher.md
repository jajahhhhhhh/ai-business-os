# ADR-0010: Postiz as a backend publisher (deviating from §7)

**Status:** accepted · **Date:** 2026-08-01

## Context
§7 says third-party MCPs (Gmail, Drive, Ahrefs, Canva, **Postiz**, …) are
"consumed as-is — no re-wrapping." The Social agent (M6) therefore produced the
4-week content calendar and left publishing to the Postiz MCP, driven by the
owner/assistant. The M6 milestone, however, also lists "Postiz publishing," and
the owner wants the calendar **auto-scheduled** with no human in the loop each
week — which the MCP-only path cannot do unattended from the backend.

## Decision
Re-wrap Postiz as a backend REST integration (`infrastructure/postiz.py` +
`application/postiz_publish.py`), mirroring the M7 PMS-collector pattern:
config-gated (`POSTIZ_API_URL` / `POSTIZ_API_KEY` / `POSTIZ_CHANNELS_JSON`),
skips cleanly when unconfigured, and a weekly `publish_content_calendar` beat
recomputes the same rolling schedule the Social agent renders and creates
scheduled posts. Idempotency via a `published_posts` ledger (dedup by
`date|channel|title`) so re-runs never double-post.

## Consequences
A deliberate, localized deviation from §7 — the trade is unattended automation
vs. one more API surface to own. Payload follows Postiz's documented public API
and must be validated against the live instance before first production use.
Only channels present in `POSTIZ_CHANNELS_JSON` publish; others are skipped and
counted. If the maintenance cost outweighs the benefit, revert to the MCP path —
the calendar (the source) is unchanged.

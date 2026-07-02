# ADR-0006: API-first data collection; scraping only where ToS-permitted

**Status:** accepted · **Date:** 2026-07-02

## Context
Legal compliance is a hard constraint (§1.4): Thailand PDPA, platform ToS, robots.txt, copyright. Facebook/OTA scraping is prohibited by ToS and high-value enough to tempt shortcuts.

## Decision
Every fetch passes a compliance gate (services/collectors/compliance.py): hard domain blocklist (Facebook, Airbnb, Booking, Agoda), per-source ToS policy registry, robots.txt honoring, honest User-Agent, per-source rate limits. Violations raise, are counted, and are never retried around.

## Consequences
Competitor OTA pricing requires licensed data (AirDNA, budgeted from M3) or manual spot-checks. Slower data acquisition, zero legal exposure.

# ADR-0009: MinIO + off-site B2 over cloud S3

**Status:** accepted · **Date:** 2026-07-02

## Context
Object storage for originals, snapshots, reports. Cloud S3 adds egress costs and an external dependency for every read.

## Decision
MinIO on the VPS (data locality, S3 API), nightly age-encrypted sync to Backblaze B2 for off-site durability (~$1–3/mo).

## Consequences
VPS disk is the primary copy — B2 sync is the durability story; restore runbook tested weekly.

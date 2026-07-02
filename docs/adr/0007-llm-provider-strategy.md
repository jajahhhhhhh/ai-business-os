# ADR-0007: Claude primary, OpenAI fallback, bge-m3 local embeddings

**Status:** accepted · **Date:** 2026-07-02

## Context
Need Thai + English quality, cost tiering, and resilience to a single provider outage. Embeddings run constantly (ingestion) — API embedding costs compound.

## Decision
Model router (orchestrator/router.py) maps LOW/MID/HIGH tiers to Claude models with OpenAI fallback per tier. Embeddings: bge-m3 (multilingual incl. Thai, 1024-dim) on CPU, free at our volume.

## Consequences
Two SDKs to maintain. Pricing table must be kept current (weekly CI check). bge-m3 adds ~2 GB RAM to the worker.

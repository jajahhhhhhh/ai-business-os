# ADR-0001: Single VPS + Docker Compose

**Status:** accepted · **Date:** 2026-07-02

## Context
Solo operator, ~$40–80/mo infra ceiling. Kubernetes or managed PaaS adds cost and operational surface with no benefit at this scale.

## Decision
Run everything on one VPS with Docker Compose v2. All services are 12-factor (env config, stateless where possible, health probes) so images are Kubernetes-ready; a Helm chart skeleton is kept in infra/k8s.

## Consequences
One machine is a single point of failure — mitigated by nightly tested backups (RPO 24 h, RTO 4 h). Migration path: provision managed PG + object storage, helm install, cut DNS.

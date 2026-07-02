# Runbook — Backup & Restore

**RPO 24 h / RTO 4 h.** Nightly backups are *tested* by a weekly automated
restore-to-scratch-container job; an untested backup is not a backup.

## What is backed up (02:00 daily, `infra/backup/backup.sh` via cron)

| Data | Method | Destination |
|---|---|---|
| PostgreSQL | `pg_dump -Fc` | MinIO `backups/pg/` → B2 |
| MinIO buckets (documents, snapshots, reports) | `mc mirror` | Backblaze B2 (age-encrypted) |
| Qdrant | snapshot API | MinIO `backups/qdrant/` → B2 |
| `.env` | age-encrypted copy | B2 (separate key) |

Meilisearch and Redis are **not** backed up: both are derived/rebuildable
(re-index from Postgres + MinIO; Redis is cache + queue only).

## Restore (full VPS loss)

```bash
# 1. Provision fresh VPS (docs/runbooks/deploy.md prerequisites)
# 2. Fetch repo + decrypt .env
git clone git@github.com:OWNER/ai-business-os.git /opt/aibos && cd /opt/aibos
sops -d infra/compose/.env.enc > infra/compose/.env
# 3. Start data services
make dev
# 4. Restore Postgres
b2 download-file latest pg.dump && pg_restore -h 127.0.0.1 -U osuser -d aibos --clean pg.dump
# 5. Restore MinIO + Qdrant snapshots
bash infra/backup/restore.sh
# 6. Rebuild search index (derived data)
docker compose run --rm api python -m src.tasks.reindex
# 7. Full stack + verify
make deploy && curl -fsS https://$DOMAIN/api/v1/health/ready
```

## Weekly restore test (automated)

Cron Sunday 04:30 runs `infra/backup/verify_restore.sh`: restores latest pg dump
into a scratch container, runs `SELECT count(*)` sanity queries on core tables,
alerts LINE on failure.

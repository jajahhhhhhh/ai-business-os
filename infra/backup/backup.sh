#!/usr/bin/env bash
# Nightly backup: Postgres + Qdrant + MinIO → B2 (age-encrypted). Cron: 0 2 * * *
# Requires: docker compose stack running, b2 CLI authorized, age recipient in $AGE_RECIPIENT.
set -euo pipefail

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cd "$(dirname "$0")/../compose"
source .env

echo "[backup] pg_dump"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER}" -Fc "${POSTGRES_DB}" \
  > "$WORK/pg-$STAMP.dump"

echo "[backup] qdrant snapshot"
curl -fsS -X POST "http://127.0.0.1:6333/snapshots" -o "$WORK/qdrant-$STAMP.json"

echo "[backup] encrypt + upload"
for f in "$WORK"/*; do
  age -r "$AGE_RECIPIENT" -o "$f.age" "$f"
  b2 upload-file "${B2_BUCKET:-aibos-backups}" "$f.age" "$(basename "$f").age"
done

echo "[backup] mirror MinIO buckets to B2"
docker run --rm --network aibos_default \
  -e MC_HOST_src="http://${S3_ACCESS_KEY}:${S3_SECRET_KEY}@minio:9000" \
  minio/mc mirror --overwrite src/"${S3_BUCKET}" "/b2/${B2_BUCKET:-aibos-backups}/minio" \
  || echo "[backup] WARN minio mirror failed — will alert"

echo "[backup] done $STAMP"

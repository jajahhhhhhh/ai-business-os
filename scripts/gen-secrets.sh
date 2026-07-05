#!/usr/bin/env bash
# Generate a production .env from .env.example with strong random secrets.
# Usage:  DOMAIN=os.example.com bash scripts/gen-secrets.sh > infra/compose/.env
# Then fill the external API keys (ANTHROPIC/GMAIL/LINE/REDDIT) by hand —
# this script only generates what can be generated.
set -euo pipefail

if [ -z "${DOMAIN:-}" ]; then
  echo "Set DOMAIN first, e.g.: DOMAIN=os.howtoniksen.com bash scripts/gen-secrets.sh" >&2
  exit 1
fi

rand() { openssl rand -hex "${1:-24}"; }
fernet_key() { openssl rand 32 | base64 | tr '+/' '-_'; }

EXAMPLE="$(dirname "$0")/../infra/compose/.env.example"

sed -e "s|^ENV=dev|ENV=prod|" \
    -e "s|^DOMAIN=localhost|DOMAIN=${DOMAIN}|" \
    -e "s|^PUBLIC_API_URL=.*|PUBLIC_API_URL=https://${DOMAIN}/api|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand)|" \
    -e "s|^MEILI_MASTER_KEY=.*|MEILI_MASTER_KEY=$(rand)|" \
    -e "s|^S3_ACCESS_KEY=.*|S3_ACCESS_KEY=aibos|" \
    -e "s|^S3_SECRET_KEY=.*|S3_SECRET_KEY=$(rand)|" \
    -e "s|^API_SECRET_KEY=.*|API_SECRET_KEY=$(rand 32)|" \
    -e "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(rand 12)|" \
    -e "s|^GLITCHTIP_SECRET_KEY=.*|GLITCHTIP_SECRET_KEY=$(rand 32)|" \
    -e "s|^PII_ENCRYPTION_KEY=.*|PII_ENCRYPTION_KEY=$(fernet_key)|" \
    "$EXAMPLE"

# DATABASE_URL must embed the generated postgres password — remind the operator.
echo "" >&2
echo "IMPORTANT: update DATABASE_URL in the output to use the generated" >&2
echo "POSTGRES_PASSWORD (same value, asyncpg URL), then fill the external" >&2
echo "API keys. See docs/runbooks/first-deploy.md step 4." >&2

#!/usr/bin/env bash
# Post-deploy smoke test — run ON the VPS (or anywhere with access to $DOMAIN).
# Usage: DOMAIN=os.example.com bash scripts/smoke.sh
# Every check prints PASS/FAIL; exits non-zero if any check fails.
set -uo pipefail

DOMAIN="${DOMAIN:?set DOMAIN}"
BASE="https://${DOMAIN}"
FAIL=0

check() { # name, expected, actual
  if [ "$2" = "$3" ]; then
    echo "PASS  $1"
  else
    echo "FAIL  $1 (expected $2, got $3)"
    FAIL=1
  fi
}

code() { curl -ks -o /dev/null -w "%{http_code}" "$1"; }

echo "== HTTP surface =="
check "dashboard /"            200 "$(code "$BASE/")"
check "api liveness"           200 "$(code "$BASE/api/v1/health")"
check "api readiness"          200 "$(code "$BASE/api/v1/health/ready")"
check "api docs hidden (prod)" 404 "$(code "$BASE/api/docs")"
check "metrics blocked"        403 "$(code "$BASE/api/v1/metrics")"

echo "== Readiness detail =="
READY=$(curl -ks "$BASE/api/v1/health/ready")
echo "$READY"
echo "$READY" | grep -q '"database":{"status":"up"' || { echo "FAIL  database not up"; FAIL=1; }

echo "== Containers (run on the VPS) =="
if command -v docker >/dev/null 2>&1; then
  EXPECTED="api web worker beat caddy postgres redis qdrant meilisearch minio prometheus grafana glitchtip"
  for svc in $EXPECTED; do
    STATE=$(docker compose -f "$(dirname "$0")/../infra/compose/docker-compose.yml" ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s{print $2}')
    if [ "$STATE" = "running" ]; then echo "PASS  container $svc"; else echo "WARN  container $svc state='$STATE'"; fi
  done
else
  echo "SKIP  docker not available here — run on the VPS for container checks"
fi

echo "== Functional: generate today's Thai snapshot =="
SNAP=$(curl -ks -X POST "$BASE/api/v1/reports/daily-snapshot:generate" -H "Authorization: Bearer ${AIBOS_API_KEY:-}" -w "\n%{http_code}")
CODE=$(echo "$SNAP" | tail -1)
if [ "$CODE" = "201" ]; then
  echo "PASS  snapshot generated"
  echo "$SNAP" | head -1 | head -c 300; echo
else
  echo "FAIL  snapshot generate returned $CODE (auth needed? see runbook step 8)"
  FAIL=1
fi

[ "$FAIL" = 0 ] && echo "== ALL CHECKS PASSED ==" || echo "== FAILURES ABOVE =="
exit "$FAIL"

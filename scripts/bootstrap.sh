#!/usr/bin/env bash
# One-command deploy — run on YOUR MAC, from the repo root, with the CHU! drive mounted.
#
#   HCLOUD_TOKEN=xxx DOMAIN=os.howtoniksen.com bash scripts/bootstrap.sh
#
# It provisions the VPS (Terraform), waits for it to harden, copies the code up,
# generates secrets, and brings the whole stack live. What it does NOT do — and
# what only you can do first — is:
#   1. create the Hetzner account + add a payment method
#   2. generate the Read/Write API token  -> HCLOUD_TOKEN above
#   3. own a domain and be able to set its DNS
#
# After it finishes it prints the 3 short manual steps that must stay in your
# hands (password gate, optional API keys, final check). Safe to re-run: every
# step is idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
: "${HCLOUD_TOKEN:?Set HCLOUD_TOKEN (Hetzner console -> Security -> API tokens, Read/Write)}"
: "${DOMAIN:?Set DOMAIN, e.g. DOMAIN=os.howtoniksen.com}"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*"; }

# --- 0. prerequisites -------------------------------------------------------
say "Checking prerequisites"
for bin in terraform ssh rsync dig; do
  command -v "$bin" >/dev/null || { warn "missing '$bin' — install it and re-run"; exit 1; }
done
[ -f "$SSH_KEY.pub" ] || { warn "no SSH public key at $SSH_KEY.pub — run: ssh-keygen -t ed25519"; exit 1; }

# --- 1. provision the server -----------------------------------------------
say "Provisioning the VPS with Terraform (idempotent)"
cd "$REPO_ROOT/infra/terraform"
terraform init -input=false >/dev/null
terraform apply -auto-approve -input=false \
  -var "hcloud_token=$HCLOUD_TOKEN" \
  -var "ssh_public_key=$(cat "$SSH_KEY.pub")"
SERVER_IP="$(terraform output -raw server_ip)"
say "Server IP: $SERVER_IP"

# --- 2. wait for SSH (cloud-init hardening takes ~2 min) --------------------
say "Waiting for the server to finish first-boot hardening"
for i in $(seq 1 40); do
  if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
       "deploy@$SERVER_IP" 'test -d /opt/aibos' 2>/dev/null; then
    say "Server is ready"; break
  fi
  [ "$i" = 40 ] && { warn "server not reachable after ~5 min — check Hetzner console"; exit 1; }
  printf '.'; sleep 8
done

# --- 3. DNS: the A record must point at the server before Caddy can get TLS -
say "Checking DNS: $DOMAIN must resolve to $SERVER_IP"
if [ "$(dig +short "$DOMAIN" | tail -1)" != "$SERVER_IP" ]; then
  warn "Set an A record:  $DOMAIN  ->  $SERVER_IP   (then press Enter)"
  warn "TLS certificate issuance will fail until this resolves."
  read -r _
  until [ "$(dig +short "$DOMAIN" | tail -1)" = "$SERVER_IP" ]; do
    printf 'waiting for DNS...\n'; sleep 15
  done
fi
say "DNS resolves correctly"

# --- 4. copy the code up (rsync; no GitHub auth needed on the VPS) ----------
say "Copying the application to the server"
rsync -az --delete \
  --exclude '.git' --exclude 'node_modules' --exclude '.next' \
  --exclude '._*' --exclude '.venv' --exclude '__pycache__' \
  -e "ssh -i $SSH_KEY" \
  "$REPO_ROOT/" "deploy@$SERVER_IP:/opt/aibos/"

# --- 5. generate secrets + bring the stack up (idempotent) -----------------
say "Generating secrets and starting the stack (first build ~15 min)"
ssh -i "$SSH_KEY" "deploy@$SERVER_IP" DOMAIN="$DOMAIN" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/aibos
if [ ! -f infra/compose/.env ]; then
  DOMAIN="$DOMAIN" bash scripts/gen-secrets.sh > infra/compose/.env
  # propagate the generated postgres password into DATABASE_URL (asyncpg URL)
  PGPW=$(grep '^POSTGRES_PASSWORD=' infra/compose/.env | cut -d= -f2-)
  sed -i "s#^DATABASE_URL=.*#DATABASE_URL=postgresql+asyncpg://osuser:${PGPW}@postgres:5432/aibos#" infra/compose/.env
  chmod 600 infra/compose/.env
  echo "generated infra/compose/.env"
else
  echo "infra/compose/.env already exists — leaving it untouched"
fi
make deploy
make seed
REMOTE

say "Stack is live at https://$DOMAIN"
cat <<EOF

$(printf '\033[1;32m')DEPLOY DONE.$(printf '\033[0m') Three short steps remain in your hands
(the system is already running and degrades gracefully until you do them):

  ssh deploy@$SERVER_IP
  cd /opt/aibos

  1. PASSWORD-GATE the dashboard (do this before sharing the URL):
       docker run --rm caddy:2-alpine caddy hash-password        # pick a password
       nano infra/compose/Caddyfile                              # uncomment basic_auth, paste hash
       docker compose -f infra/compose/docker-compose.yml restart caddy

  2. (optional, anytime) add API keys for LINE + AI features:
       nano infra/compose/.env      # ANTHROPIC_API_KEY, LINE_*, GMAIL_*, REDDIT_*
       docker compose -f infra/compose/docker-compose.yml up -d --build worker beat api
       # get keys the runbook way: docs/runbooks/gmail-line-setup.md, lead-sources.md

  3. VERIFY everything (also generates a live Thai snapshot):
       make api-key NAME=smoke-test      # copy the printed key
       DOMAIN=$DOMAIN AIBOS_API_KEY=<that key> make smoke

Full detail + troubleshooting: docs/runbooks/first-deploy.md
EOF

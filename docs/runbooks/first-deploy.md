# Runbook — First deploy (from zero to green smoke test)

Follow in order. Steps marked 💻 run on your Mac, 🖥 on the VPS.
Estimated time: ~60–90 minutes, most of it waiting on DNS and image builds.

## 0. Prerequisites (💻)

- A domain (e.g. `os.howtoniksen.com`) whose DNS you control.
- [Hetzner Cloud](https://console.hetzner.cloud) account + project → API token
  (Security → API tokens → Read/Write).
- Terraform ≥1.7 (`brew install terraform`), an SSH key (`ssh-keygen -t ed25519`).
- This repo pushed to a git remote the VPS can pull (GitHub private repo is fine).

## 1. Provision the server (💻)

```bash
cd infra/terraform
terraform init
terraform apply \
  -var "hcloud_token=<token>" \
  -var "ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)"
# note the server_ip output
```

Cloud-init hardens the box automatically (deploy user, key-only SSH, UFW
deny-in + 22/80/443, fail2ban, Docker). Give it ~2 minutes after boot.

## 2. Point DNS (💻)

`A` record: `os.howtoniksen.com` → `<server_ip>`. Wait until
`dig +short os.howtoniksen.com` returns the IP (Caddy needs it for the TLS cert).

## 3. Clone the repo (🖥)

```bash
ssh deploy@<server_ip>
git clone <your-git-remote> /opt/aibos && cd /opt/aibos
```

## 4. Create the production .env (🖥)

```bash
DOMAIN=os.howtoniksen.com bash scripts/gen-secrets.sh > infra/compose/.env
chmod 600 infra/compose/.env
nano infra/compose/.env
```

Hand-edit the remaining values:

| Variable | Where it comes from | Needed for |
|---|---|---|
| `DATABASE_URL` | replace password with the generated `POSTGRES_PASSWORD` | everything |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys | LLM analysis (agents fall back to rules without it) |
| `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` | [gmail-line-setup.md](gmail-line-setup.md) | bank-alert auto-sync (manual paste works without) |
| `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_OWNER_USER_ID` | [gmail-line-setup.md](gmail-line-setup.md) | daily snapshot + escalations to LINE |
| `REDDIT_CLIENT_ID/SECRET` | [lead-sources.md](lead-sources.md) | lead discovery (sources report `skipped` without) |

Every external key is optional at boot — the system degrades gracefully — but
LINE + Anthropic are the two that deliver the most immediate value.

Back up this file now (password manager): it is the only copy of your secrets.

## 5. First stack start (🖥)

```bash
cd /opt/aibos
make deploy          # builds images (~10-15 min first time), runs migrations, starts all
docker compose -f infra/compose/docker-compose.yml ps   # everything running/healthy?
```

Common first-boot checks: `docker compose ... logs migrate` (must end with
`Running upgrade ... -> 0005`), `logs api | head`, `logs caddy | grep -i cert`
(TLS issuance).

## 6. Seed business data (🖥)

```bash
make seed
# created user ch_company@howtoniksen.com / sites Lipa Noi + Chaweng /
# contractor MR.HOME / 3 reddit lead sources
```

## 7. Enable basic auth — REQUIRED before sharing the URL (🖥)

`AUTH_MODE=proxy` (set by gen-secrets) trusts keyless requests as you, which
is only safe behind Caddy's password gate:

```bash
docker run --rm caddy:2-alpine caddy hash-password   # enter a strong password
nano infra/compose/Caddyfile    # uncomment basic_auth, paste the hash
docker compose -f infra/compose/docker-compose.yml restart caddy
```

Verify: opening `https://os.howtoniksen.com` must now ask for the password.

## 8. Mint API keys for automation (🖥)

```bash
make api-key NAME=smoke-test     # copy the printed key
make api-key NAME=mcp-kb         # one per MCP server you connect
```

## 9. Smoke test (🖥 or 💻)

```bash
DOMAIN=os.howtoniksen.com AIBOS_API_KEY=<smoke-test key> bash scripts/smoke.sh
```

All checks must PASS — including the live Thai daily snapshot at the end.
If LINE is configured you'll receive it on your phone immediately.

## 10. Backups (🖥)

```bash
# Backblaze B2: create bucket aibos-backups + app key; age: generate a key pair
sudo apt install -y age && pip install --user b2
age-keygen -o ~/aibos-backup.key    # PUBLIC key -> AGE_RECIPIENT below; store both in password manager
crontab -e
```

```cron
0 2 * * *  cd /opt/aibos && AGE_RECIPIENT=<age1...> B2_BUCKET=aibos-backups bash infra/backup/backup.sh >> /var/log/aibos-backup.log 2>&1
```

Run it once by hand and confirm files land in B2 before trusting the cron.

## 11. First-week operations

- Enter your real quotations + draws (งานรีโนเวท) — retire the manual HTML (M1 exit).
- Add ~10 competitor villas (คู่แข่ง) — M3 exit needs your curated list.
- Forward a real bank alert e-mail to test matching (การเงิน) if Gmail isn't wired yet.
- Upload 2–3 quotation PDFs (คลังความรู้) and search them in Thai.
- 07:30 next morning: the daily snapshot should arrive on LINE unprompted.
- Friday: skim the ค้นพบ lead column — your accept/reject ratio is the M5
  precision measure.

## Troubleshooting

| Symptom | Look at |
|---|---|
| TLS errors / cert not issued | `logs caddy`; DNS A record propagated? port 80 reachable? |
| api unhealthy | `logs api`; usually DATABASE_URL password mismatch (step 4) |
| glitchtip crashloop | fresh volume? `initdb/01-glitchtip.sql` only runs on FIRST postgres boot — for an existing volume: `docker compose exec postgres createdb -U osuser glitchtip` |
| snapshot has no LLM section | ANTHROPIC_API_KEY unset or daily budget spent — deterministic report still sends |
| reddit sources `skipped: no credentials` | REDDIT_* unset (step 4) — by design, never scraped |

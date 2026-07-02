# Runbook — Deploy

## Prerequisites (one-time VPS setup)

Ubuntu 24.04 LTS, 4 vCPU / 8 GB (Hetzner CPX31-class).

```bash
# as root
adduser deploy && usermod -aG docker deploy
apt update && apt install -y docker.io docker-compose-v2 fail2ban ufw
ufw default deny incoming && ufw allow 22,80,443/tcp && ufw enable
# SSH: key-only — set PasswordAuthentication no in /etc/ssh/sshd_config
```

## Normal deploy (from CI)

Release tag on `main` triggers the deploy job:

1. Images built + trivy-scanned + pushed to GHCR (`ci.yml`).
2. SSH to VPS: `docker compose pull && docker compose --profile prod up -d`.
3. Migrations run in the one-shot `migrate` container **before** the api starts
   (compose `depends_on: service_completed_successfully`).
4. Health gate: `curl -fsS https://$DOMAIN/api/v1/health` must return 200 within 120 s.

## Manual deploy

```bash
ssh deploy@vps
cd /opt/aibos
git pull --ff-only
make deploy
curl -fsS https://$DOMAIN/api/v1/health
```

## Rollback

Images are tagged by commit SHA. To roll back:

```bash
export TAG=<previous-good-sha>        # from GHCR or `docker image ls`
docker compose --profile prod up -d --no-build \
  --scale migrate=0                   # do NOT rerun newer migrations
```

If a migration must be reverted: `docker compose run --rm api alembic downgrade -1`
(every migration ships a tested `downgrade()`), then start the previous image tag.

## Secrets

Plaintext `.env` exists only on the VPS at `/opt/aibos/infra/compose/.env`
(mode 600, owner deploy). The SOPS/age-encrypted copy `infra/compose/.env.enc`
may be committed; decrypt with the age key stored in the owner's password manager:

```bash
sops -d infra/compose/.env.enc > infra/compose/.env
```

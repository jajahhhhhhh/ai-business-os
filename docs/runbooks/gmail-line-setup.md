# Runbook — Gmail & LINE credentials (M1)

Both integrations are optional at runtime: with credentials unset, bank alerts are
ingested by pasting into the การเงิน page, and the daily snapshot is generated but
not pushed. Fill these to make both automatic.

## Gmail (bank-alert sync, read-only)

1. Google Cloud Console → new project `aibos` → enable **Gmail API**.
2. OAuth consent screen: Internal is unavailable for personal accounts — choose
   External, add the owner Gmail (ch_company@howtoniksen.com) as a test user.
3. Credentials → OAuth client ID → Desktop app. Note client ID + secret.
4. Obtain a refresh token with the loopback flow, scope
   `https://www.googleapis.com/auth/gmail.readonly` (one-time, on any machine):

   ```bash
   python3 apps/api/scripts/gmail_authorize.py  # prints the URL, paste the code, prints GMAIL_REFRESH_TOKEN
   ```

   (If the helper script is missing, any standard OAuth loopback flow works —
   the API only needs `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`.)
5. Put the three values in `infra/compose/.env`, restart `worker`:
   `docker compose restart worker`. The `sync_bank_alerts` task polls every 2 h.

Security notes: read-only scope; the query filter only pulls bank-sender domains,
and non-transaction mail is rejected by the parser (never stored).

## LINE (daily Thai snapshot, 07:30)

1. https://developers.line.biz → create provider → **Messaging API** channel.
2. Channel access token (long-lived) → `LINE_CHANNEL_ACCESS_TOKEN`.
3. Add the bot as a friend from the QR in the channel settings.
4. Owner user ID: Messaging API tab → "Your user ID" (starts with `U`) →
   `LINE_OWNER_USER_ID`.
5. Restart `worker` and `beat`. Test without waiting for 07:30:
   the การเงิน page → "ส่งสรุปรายวันตอนนี้", or
   `curl -X POST https://$DOMAIN/api/v1/reports/daily-snapshot:generate`.

## Interim dashboard protection (until Auth.js lands — TD-5)

The dashboard has no login yet. Before exposing the VPS publicly, enable Caddy
basic auth: uncomment the `basic_auth` block in `infra/compose/Caddyfile` and set
a bcrypt hash generated with `docker run --rm caddy:2-alpine caddy hash-password`.

# Runbook — Lead sources (M5)

Lead discovery pulls from **public sources only**, through the compliance gate
(§8.4). Facebook/Airbnb/Booking/Agoda are refused at registration. Two source
types ship in M5:

## RSS feeds

Add on the ลูกค้า page → แหล่งค้นหาลูกค้า → type `rss` + feed URL. Good picks:
travel blogs covering Samui, community news feeds, supplier/trade blogs
(Phase A). robots.txt and per-source rate limits are enforced automatically.

## Reddit (official API, read-only)

1. https://www.reddit.com/prefs/apps → "create another app" → type **script**.
2. Note the client id (under the app name) and secret →
   `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in `infra/compose/.env`.
3. Restart the worker. Without credentials, reddit sources report
   `skipped: no credentials` and collect nothing — the system never falls back
   to scraping reddit.com HTML.
4. Suggested starting subreddits (add via UI): `kohsamui`, `Thailand`,
   `digitalnomad` (optionally with a query like `samui villa`).

Rate limits: sources default to 12 fetches/hour each; Reddit's own API limits
also apply and are respected via the honest User-Agent.

## PDPA (§8.5)

Only the public handle, post URL, and post content are stored. Contact data is
encrypted at rest (`PII_ENCRYPTION_KEY` — set a dedicated 32-byte urlsafe-base64
key in prod; without it a key is derived from `API_SECRET_KEY` with a warning).
Leads inactive for 18 months are anonymized automatically every Sunday.

## Exit criterion tracking (M5, §18)

≥20 scored leads/week from ≥3 sources, precision ≥70% on your review: skim the
ค้นพบ column weekly; move real prospects to คัดกรองแล้ว and junk to ปิดไม่ได้ —
that ratio is the precision measure.

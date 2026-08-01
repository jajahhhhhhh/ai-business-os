# Runbook — PMS booking ingestion & occupancy analytics (M7)

Connects a property-management system (Smoobu or Lodgify) so the OS ingests
reservations and can report **occupancy %, ADR, and RevPAR**. Like every other
external integration, it **skips cleanly when unconfigured** — no credentials
means the daily sync logs `sync_bookings_skipped` and does nothing.

## What it does

```
PMS (Smoobu / Lodgify)                 bookings table              analytics
        │  official API                      │                        │
        ▼                                     ▼                        ▼
  build_booking_collector  ──fetch──▶  BookingIngestion  ──upsert──▶  occupancy_summary()
  (config-gated)                       (idempotent per                (occupancy / ADR / RevPAR)
                                        provider+external_id)
```

- **No guest PII.** Only dates, amount, status, channel and property ref are
  stored (`bookings` table) — enough for analytics, nothing sensitive.
- **Idempotent.** Reservations upsert by `(provider, external_id)`: new ones
  insert, changed ones (dates/amount/status, e.g. a cancellation) update,
  unchanged ones are skipped. Safe to run repeatedly.
- **Daily sync** at 05:00 Asia/Bangkok (`sync_bookings` beat), or on demand via
  the `sync_bookings` job.

## Configure (in `infra/compose/.env`)

Pick one provider and set its key:

```
PMS_PROVIDER=smoobu            # or lodgify
SMOOBU_API_KEY=...             # Smoobu → Settings → For developers → API key
# LODGIFY_API_KEY=...          # Lodgify → Settings → Public API
PMS_ROOM_COUNT=1               # bookable inventory (villas/rooms) for occupancy
PMS_CURRENCY=THB               # reporting currency; stays in other currencies
                               # are skipped (and counted) in analytics
```

Restart the worker. Verify with a manual run (the `sync_bookings` job, or the
Celery task) and check `sync_bookings_done` in the logs with the created/updated
counts.

## The metrics

Standard lodging math over a `[start, end)` window for `PMS_ROOM_COUNT` rooms:

- **Occupancy** = room-nights sold ÷ available room-nights (capped at 100%).
- **ADR** (average daily rate) = room revenue ÷ room-nights sold.
- **RevPAR** = room revenue ÷ available room-nights (≈ ADR × occupancy).

Stays that straddle the window are clipped to their in-window nights and their
revenue is pro-rated; cancelled stays are excluded. All amounts are exact
`Decimal`.

## Provider notes

- **Smoobu** — `GET /api/reservations` (header `Api-Key`), paginated by
  `page`/`page_count`. Owner "blocked" holds are skipped; `type=cancellation`
  → cancelled.
- **Lodgify** — `GET /v2/reservations/bookings` (header `X-ApiKey`). `Booked`
  → booked, `Declined` → cancelled; tentative/open are skipped.

Field mappings follow the documented APIs — validate against a live account
before the first production sync.

## Guest comms — post-checkout review requests (M7)

Once bookings are syncing, the OS can nudge you to collect Google reviews — the
biggest local-SEO lever (see `local-seo.md`). A daily 10:00 task
(`send_review_requests`) finds guests who checked out in the last few days,
sends **one LINE message to you** listing them plus a ready-to-send review
request (EN + TH) carrying your review link, and marks each booking so it's
nudged once. No guest PII is stored — you forward the copy through the channel
that already holds the guest (PMS thread, chat).

Enable it in `infra/compose/.env` (needs LINE configured too):

```
GBP_REVIEW_URL=https://g.page/r/xxxxxxxx/review   # your Google review short-link
REVIEW_REQUEST_LOOKBACK_DAYS=3
```

Empty `GBP_REVIEW_URL` (or unconfigured LINE) → the nudge skips cleanly.

## Scope / next phase

This milestone lands ingestion + the analytics engine. **Phase 2** wires the
occupancy/ADR/RevPAR figures into the weekly Analytics report and the dashboard
(a `bookings` reader over a reporting window + a metrics tile), and can trigger
guest comms (e.g. the post-checkout review request from the local-SEO plan) on
booking events.

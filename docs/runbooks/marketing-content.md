# Runbook — Marketing content pipeline (M6)

Three agents turn competitor/keyword signals into an approved 4-week content
calendar. Each is budget-capped and additive-LLM: if the LLM is unavailable
(no key, over cap, failure) a deterministic brief/draft/calendar is still
produced, so the pipeline never stalls. All outputs land in the **reports**
archive (`GET /v1/reports?kind=…`).

## The pipeline

| Agent | Tier | Task | Reads | Writes (`reports.kind`) |
|---|---|---|---|---|
| `seo` | MID | `seo-brief` | evergreen keyword themes + recent high/critical competitor content/promo moves | `seo` (English brief) |
| `content` | HIGH | `content-draft` | latest `seo` briefs + brand guide | `content` (English draft + Thai summary — **a draft for approval**) |
| `social` | LOW | `content-calendar` | recent `content` drafts | `content-calendar` (Thai calendar, pushed to LINE) |

Weekly beat (Asia/Bangkok), staggered so each stage's inputs exist:
SEO **Tue 09:00** → Content **Wed 09:00** → Calendar **Thu 09:00**.

## Running it manually

Dashboard → agent trigger buttons (**บรีฟ SEO / ร่างคอนเทนต์ / ปฏิทินคอนเทนต์**),
or the API:

```
POST /v1/agents/seo:trigger
POST /v1/agents/content:trigger
POST /v1/agents/social:trigger
```

Run them in order the first time (content needs a brief; the calendar needs
drafts). Review each artifact in the reports archive; the content draft is
**not published** — it waits for you.

## Approve & publish (Postiz / Ahrefs stay MCPs — §7)

The backend produces briefs and the calendar; it does **not** re-wrap the
Postiz or Ahrefs MCPs. To publish: review the `content-calendar` report, then
schedule the approved drafts through the Postiz MCP. Use the Ahrefs MCP to
sanity-check the brief's keywords against live volume/difficulty before drafting.

## Brand guide & budgets

Voice, keyword themes and channels live in
`apps/api/src/application/agents/marketing.py` (the brand guide) and the prompt
templates in `packages/prompts/{seo,content}`. Daily USD caps are in
`AGENT_BUDGETS` (`seo` 0.50, `content` 1.00, `social` 0.10); the social agent
makes no LLM call. Marketing content is English; the owner-facing calendar and
summaries are Thai (§3).

# Runbook — Facebook Group (official Graph API, own group only)

**Compliance:** this is the ONE sanctioned Facebook path (ARCHITECTURE §8.4): the
official Graph API, for a group **you administer**, with your own access token.
It is NOT scraping — the collector hits `graph.facebook.com` with an auth token,
never `facebook.com` HTML. General Facebook scraping stays blocked by the
compliance gate.

> ⚠️ **Read this first.** Facebook's Groups API is the most restricted integration
> in this whole system. Reading group **content** (`/{group-id}/feed`) requires a
> Facebook App, the app installed in your group, and the `groups_access_member_info`
> permission — which needs **App Review + Business Verification** (typically 1–3
> weeks, and Meta can decline). This runbook's Steps 1–5 **test whether your group
> is reachable at all** before anyone invests in the App Review or the collector.
> Do the test first.

---

## Step 0 — What do you want out of the group?

The answer decides whether this is even worth the App Review effort. Tell me which:

- **Leads** — members asking questions you can answer / sell to → feeds M5 lead discovery
- **Sentiment / themes** — what members complain about or praise
- **Competitor mentions** — when rivals get named
- **Just archiving posts** into the knowledge base

(If you only need occasional analysis, the **manual export** in Step 6 may be
enough and skips the entire App Review wall.)

## Step 1 — Create a Facebook App 💻

1. Go to [developers.facebook.com](https://developers.facebook.com/) → log in as
   yourself (the group admin) → **My Apps → Create App**.
2. Use case: **Other** → Type: **Business** → name it e.g. `CHOWTO Group Reader`.
3. Note the **App ID** and **App Secret** (Settings → Basic).

## Step 2 — Find your Group ID 💻

Open your group in a browser. The URL is `facebook.com/groups/<something>`. If
`<something>` is a number, that's your Group ID. If it's a name, use
[lookup-id.com](https://lookup-id.com/) or the Graph API Explorer search.

## Step 3 — Generate a test token (Graph API Explorer) 💻

1. In your App → **Tools → Graph API Explorer**.
2. **User or Page token** → your app selected → **Add permissions**:
   `groups_access_member_info`, `public_profile`. Add `email` if you want contact.
3. Click **Generate Access Token** → approve the consent screen (this is where
   *you* authenticate — I never see your password).

## Step 4 — TEST whether your group content is reachable 💻

In Graph API Explorer, run each and note what comes back:

```
GET /me/groups                 # groups your app can see for you (admin groups)
GET /<GROUP_ID>?fields=id,name,member_count
GET /<GROUP_ID>/feed?fields=message,from,created_time,permalink_url&limit=5
```

**This is the moment of truth:**
- ✅ If `/feed` returns posts → your group is reachable. Continue to Step 5.
- ❌ If you get `(#200) Requires ... permission` or empty data → the group feed
  needs **App Review** for `groups_access_member_info` (App → App Review →
  Permissions and Features → request it, with a screencast of your use case).
  Meta may still decline group-content access. **Tell me the exact error** and
  we decide: pursue App Review, or use the Step 6 manual export instead.

## Step 5 — Long-lived token + hand off to me 🔒

Once `/feed` works with the short token:

1. Exchange it for a **long-lived (60-day) token**:
   ```
   GET /oauth/access_token?grant_type=fb_exchange_token
       &client_id=<APP_ID>&client_secret=<APP_SECRET>&fb_exchange_token=<SHORT_TOKEN>
   ```
2. Save it privately on your Mac (like the Hetzner token — not pasted in chat):
   ```bash
   read -s -p "Paste long-lived FB token then Enter: " T; \
     printf %s "$T" > ~/aibos_fb_token && chmod 600 ~/aibos_fb_token; echo; \
     echo "saved: $(wc -c < ~/aibos_fb_token) chars"
   ```
3. Tell me your **Group ID** and that the token is saved. I then:
   - add `FB_GRAPH_TOKEN` + `FB_GROUP_ID` to the server `.env`,
   - build the `facebook_group` collector (Graph API only, compliance-gated to
     `graph.facebook.com` + token — the hard blocklist still refuses plain
     `facebook.com`),
   - wire it into your chosen module (leads / KB / sentiment from Step 0).
   - Note: 60-day tokens expire — we'll set a reminder to refresh, or use a
     System User token (never expires) if you convert the app to Business.

## Step 6 — Fallback: manual export (no App Review) 💻

If Facebook won't grant API access (common), you still have a compliant path:
your group's **built-in tools** → any post you want analyzed, copy the text and
paste it to me, or use Facebook's **Download Your Information** (group content
you posted). Owner-provided content is explicitly allowed (§8.4) — I'll run it
through leads/sentiment/KB exactly the same way, just without the live feed.

---

## Why the OS handles this differently from scraping

`services/collectors/compliance.py` keeps `facebook.com` on the HARD_BLOCKLIST.
The Facebook collector will target `graph.facebook.com` with a bearer token and
be marked `tos_policy: allowed` **only** because it is the official API for a
group you own — the sanctioned exception, not a loophole. If the token is
absent, the collector reports `skipped: no credentials` and does nothing.

# Meta Pixel + Conversions API — MojaIgracka.com

## Implemented

Pixel `1761995418366231` is read from `META_PIXEL_ID`. The previous integration is extended, not loaded twice. Browser initialization is guarded per document. Public GET pages have PageView; staff/superusers and admin/panel/WMS are excluded. No layout changes were made.

| Event | Browser | CAPI | Trigger/value |
|---|---|---|---|
| PageView | Yes | No | Successful public HTML page |
| ViewContent | Yes | Yes | Existing product page, current product price |
| AddToCart | Yes | Yes | Actual successful quantity increase; includes AJAX, forms, sets and quantity updates |
| InitiateCheckout | Yes | Yes | Checkout form opened with valid cart; calculated payable total |
| Purchase | Yes | Yes | Successful COD order transaction; confirmed payment only for future card integration |

Commerce parameters: `currency=BAM`, actual `value`, `content_ids`, `content_type=product`, `contents` with `id`, `quantity`, `item_price`, `num_items`, `quantity`, and `order_id` for Purchase. IDs are string database product IDs, consistently across browser/server and current site schema. A catalog feed must use those same IDs.

AddToCart value covers the newly added units at their current promoted prices, not the entire cart. Checkout/Purchase value includes delivery and deducts selected loyalty discounts/points. Purchase contents use persisted order line prices; order-level deductions and delivery are reflected in final `value`.

## Purchase and deduplication

One persistent event per order (`MetaTrackingEvent.order` one-to-one), one UUID, identical browser `eventID` / server `event_id`, identical event name. Browser Purchase is atomically claimed once on the session-owned confirmation page; refreshing cannot re-claim it. Local storage also prevents browser replays.

COD events are written inside the successful order transaction after line items and final total. Rollback leaves no Purchase. Worker/browser skip draft/cancelled orders. Cancellation after an already accepted event cannot retract an event from Meta.

**The project has no card processor or payment webhook.** The integration exposes the tested internal service:

```python
purchase_event(request, order, payment_method='card', payment_confirmed=True)
```

Call this only from a future **verified payment provider webhook/service**, after payment confirmation, within its order transaction. No public client parameter or success URL sets `payment_confirmed`. Unconfirmed card purchases are rejected; repeated verified callbacks return the same event. No unsupported payment gateway has been invented or enabled.

At-most-once browser enqueueing does not guarantee receipt (ad blockers/network failures). CAPI retries lost acknowledgments with the same UUID so Meta can deduplicate. Sent events are not selected again.

## Background delivery and reliability

Web requests only create outbox records. They never call Meta over HTTP. A separate Render Background Worker runs:

```sh
python manage.py send_meta_events --watch
```

No Redis/Celery dependency is needed. The worker uses the same PostgreSQL database as the web service. Rows are claimed using atomic conditional updates, a 120-second lease and unique lock token, so competing processes do not send the same live claim. Abandoned leases recover after restart. Success is persisted; transient network/429/5xx errors retry with exponential backoff, at most 8 attempts by default. Permanent errors are marked failed. Stored/logged error codes are sanitized; response bodies, URLs containing secrets and tokens are never printed. Only events less than 24 hours old are delivered, keeping retries within the browser/server deduplication window. No cleanup or deletion runs automatically.

One-shot/manual controls:

```sh
python manage.py send_meta_events --limit 100
python manage.py send_meta_events --retry-failed --limit 100
```

The second command is optional after fixing a permanent configuration error; it keeps original event IDs and only requeues recent failed records. It does not replay sent records.

## Matching data and privacy

CAPI includes event_name, event_time, event_id, event_source_url (path, no query string), action_source=website, custom_data and consented user_data:

- `client_user_agent` from the request, when present.
- `client_ip_address` only when valid and globally routable. Default uses REMOTE_ADDR, not arbitrary spoofable headers.
- Existing `_fbp`, `_fbc` cookies, validated. A valid landing-page `fbclid` can form `_fbc` persisted for the session.
- SHA-256 anonymous session external_id.
- Email/phone **only** if `META_SEND_HASHED_PII=true` **and** the configured server consent cookie/callable explicitly permits marketing. Defaults do not send email or phone. Email is trimmed/lowercased; phone is normalized to digits with country code (BiH default 387); ambiguous numbers are omitted. Raw email/phone, names, addresses, passwords and payment credentials are never sent.

No existing cookie consent manager was found. Existing configurable hooks are retained; no new consent UI or design changes were added. Without a configured gate, marketing technical events run when Pixel is configured. If your consent policy requires opt-in, configure the gate **before** enabling production tracking. PII remains excluded without explicit gate regardless of the PII flag.

Server consent configuration (choose one):

```text
META_CONSENT_CHECK=myapp.consent.marketing_allowed
```

Callable takes `request` and returns boolean; or:

```text
META_CONSENT_COOKIE=marketing_consent
META_CONSENT_GRANTED_VALUE=granted
```

Denied consent prevents browser markup and server events. A later request with revoked consent suppresses pending server events for that session. Already sent/in-flight requests cannot be recalled.

Browser hook: set `window.metaMarketingConsent=false` before the deferred script, and grant/revoke with:

```javascript
window.dispatchEvent(new CustomEvent('meta:consent-change', {
  detail: {marketing: true} // false revokes browser tracking
}));
```

Use a server gate for CAPI; a browser-only variable cannot gate server collection. If the server gate originally denied consent, reload after accepting. No blocked historical events are backfilled.

For Render's reverse proxy, `META_TRUSTED_PROXY_HOPS` defaults to 0. Set it to the **verified** trusted hop count for your actual proxy chain (e.g. 1 only if the rightmost X-Forwarded-For entry is the real client). Never trust a user-supplied first header entry blindly. Private/internal addresses are omitted rather than reported as client IPs. The footer privacy text distinguishes local analytics from Meta marketing data.

## All environment variables

| Variable | Default | Purpose |
|---|---|---|
| META_PIXEL_ID | 1761995418366231 in development; empty in production | Pixel/dataset ID |
| META_CAPI_ACCESS_TOKEN | empty | Secret, server/worker only; already present on Render, do not print it |
| META_CAPI_ENABLED | true | Enabled only if ID, token and valid API version also exist; explicit false disables |
| META_CAPI_API_VERSION | v26.0 | Graph API version, verified against Meta's current official Python SDK |
| META_CAPI_TIMEOUT | 5 | HTTP timeout seconds, bounded to 1–30 |
| META_CAPI_MAX_ATTEMPTS | 8 | Automatic attempts per event |
| META_CAPI_RETRY_SECONDS | 30 | Initial exponential backoff, capped at 3600 seconds |
| META_CAPI_POLL_SECONDS | 5 | Worker poll interval |
| META_CAPI_TEST_EVENT_CODE | empty | Optional Meta Test Events code, server only |
| META_SEND_HASHED_PII | false | Allow hashed contact fields only with explicit consent |
| META_DEFAULT_COUNTRY_CALLING_CODE | 387 | Phone normalization for local BiH numbers |
| META_TRUSTED_PROXY_HOPS | 0 | Verified trusted proxy count; 0 ignores forwarded headers |
| META_CONSENT_CHECK | empty | Dotted server marketing-consent callable |
| META_CONSENT_COOKIE | empty | Alternative server consent-cookie name |
| META_CONSENT_GRANTED_VALUE | granted | Exact accepted cookie value |

Source for current version: https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py
Reference: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events/
Meta docs endpoints returned HTTP 429 during this review; the official SDK source was accessible.

## Git and Render — manual operations

No commit, push, remote environment change, live CAPI transmission or deployment was executed. Token contents were not accessed. Local schema migrations add tables/fields only; no database resets, fake migrations or data deletion.

Current branch: `main`, origin: `https://github.com/berasasa1990-wq/mojaigracka.git`.

Before push, turn off automatic deploys for the Render web service and worker if currently enabled. Otherwise a push may deploy automatically.

Stage this integration explicitly so the unrelated pre-existing CSS edit is not included accidentally:

```sh
git add .env.example OnlineShopProject/settings.py shop/models.py shop/views.py shop/static/home.js shop/static/meta-pixel.js shop/meta_pixel.py shop/management/commands/send_meta_events.py shop/migrations/0054_meta_tracking_events.py shop/migrations/0055_meta_capi_delivery.py shop/test_meta_pixel.py shop/test_meta_pixel.cjs shop/test_meta_capi.py shop/templates/shop/partials/bera_footer.html META_PIXEL.md
git diff --cached --stat
git diff --cached --check
git commit -m "Complete Meta Pixel and background Conversions API integration"
git push origin main
```

Render web service and Background Worker must share production Django environment and the **same DATABASE_URL**. Required Meta settings on both:

```text
META_PIXEL_ID=1761995418366231
META_CAPI_ENABLED=true
META_CAPI_API_VERSION=v26.0
META_SEND_HASHED_PII=false
```

Keep the existing `META_CAPI_ACCESS_TOKEN`; securely make it available to the worker through Render Environment/Environment Group. Do not paste it into shell history. An existing `META_CAPI_ENABLED=false` must be changed explicitly to true when ready. Configure consent and trusted proxy settings as described above. Neither process sends CAPI with a missing token.

Web Build Command:

```sh
python -m pip install -r requirements.txt && python manage.py collectstatic --noinput
```

Pre-Deploy Command (or Render Shell on the updated release, before traffic/worker):

```sh
python manage.py migrate --noinput
python manage.py check
```

Web Start Command remains:

```sh
python -m gunicorn OnlineShopProject.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --access-logfile - --error-logfile -
```

Create/update a **Background Worker** from the same repo and branch. Build Command: `python -m pip install -r requirements.txt`. Start Command:

```sh
python manage.py send_meta_events --watch
```

Manually choose **Manual Deploy → Deploy latest commit** on the web service. Apply migrations successfully before starting/manually deploying the worker. Alternatively, with the [official Render CLI](https://render.com/docs/cli) installed, the following exact interactive commands authenticate and ask you to select the service (no secret values are printed):

```sh
render login
render deploys create --wait
```

Select the **web service** for the first deploy. Ensure the pre-deploy migration command above is configured. After migrations and the web deploy succeed, run the same command again and select the **Background Worker**:

```sh
render deploys create --wait
```

Do not select an unrelated service. No service ID is guessed, no command above was run by this implementation. Use the dashboard when CLI is not installed.

Optional smoke test in Render Shell (this sends actual queued events when enabled):

```sh
python manage.py send_meta_events --limit 10
```

Verify using Meta Events Manager Test Events / Pixel Helper while logged out of staff accounts. Browser and server copies must share the same event ID; refresh the successful order page and confirm no new Purchase. Use `META_CAPI_TEST_EVENT_CODE` for the test session and remove it after validation. Do not leave production purchases mislabeled as tests.

## Automated tests (no live Meta requests)

```sh
python manage.py test shop.test_meta_pixel shop.test_meta_capi shop.test_checkout_points_preview shop.test_custom_sets shop.test_gift_builder shop.test_bundle_sale --noinput
node --test shop/test_meta_pixel.cjs
node --check shop/static/meta-pixel.js
node --check shop/static/home.js
python manage.py makemigrations --check --dry-run
```

Tests run in a disposable Django test database, never by resetting the webshop database.

Validation result: 63 Django tests and 3 JavaScript tests passed, including retries/leases, failed/cancelled orders, confirmed/unconfirmed cards, refresh deduplication, cart quantities, promotions and consent gating.

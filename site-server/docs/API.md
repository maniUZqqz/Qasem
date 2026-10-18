# UpMarket — API Reference

> **This describes the API as it is actually implemented**, verified end to end
> against a live server by `backend/tools/e2e_api_test.py`. The Phase-0 target
> sketch that used to live here diverged from the built system in several
> places (see §5); this file is now the source of truth.

Base URL: `/api/v1/`. Auth: JWT (`Authorization: Bearer <access>`).
Every store-scoped resource is filtered server-side by the authenticated owner,
so another user's data returns **404**, never someone else's rows.

Interactive schema: `GET /api/schema/` (OpenAPI) and `GET /api/docs/` (Swagger UI,
public in DEBUG, authenticated in production).

---

## 1. Conventions

| Rule | Detail |
|---|---|
| Long work | Never blocks the request. Returns `202 {"job_id": N, "job": {...}}`; poll `GET /jobs/{id}/`. |
| Empty state | An unstarted analysis/script returns `200` with a JSON `null` body — **not** 404. "Not generated yet" is a normal state, and a 404 painted the browser console red on every page load. |
| Errors | `{"error": {"code": "...", "message": "...در فارسی"}}`. Field validation uses standard DRF per-field errors. |
| Pagination | List endpoints are paginated (`count`, `next`, `previous`, `results`), page size 20. |
| Uploads | Type + size checked, and the **bytes** are verified to be a real image — a text file renamed `.png` is rejected. |
| Rate limits | `THROTTLE_ANON` / `THROTTLE_USER` (default 30 and 240 per minute). |

---

## 2. Endpoints

### Auth — `apps/accounts`
```
POST /auth/register/     {username, password, email?}      → 201
POST /auth/login/        {username, password}              → {access, refresh}
POST /auth/refresh/      {refresh}                         → {access}
GET  /auth/me/                                             → {id, username, email}
```

### Stores — `apps/stores`
```
GET|POST                /stores/
GET|PATCH|PUT|DELETE    /stores/{id}/
GET|PUT|PATCH           /stores/{id}/profile/
```
`profile` holds brand voice, tone, shipping/return/refund policies, business
rules and **`payment_info`** — the sales agent may only quote payment details
from this field, never invent them.

### Catalog — `apps/products`
```
GET|POST                /products/            ?store={id}
GET|PATCH|DELETE        /products/{id}/
POST                    /products/{id}/images/        (multipart: image, is_main?, alt_text?)
DELETE                  /products/{id}/images/{image_id}/
POST                    /products/{id}/attributes/    {key, value}
POST                    /products/{id}/variants/      {name, stock_quantity, price_override?}
GET|POST                /categories/          ?store={id}
GET|PATCH|DELETE        /categories/{id}/
```
Products are filtered with `?store=`, not nested under `/stores/{id}/products/`.

### Product & market intelligence — `apps/ai`
```
POST /products/{id}/analyze/                    → 202 (vision per photo → reasoning)
GET  /products/{id}/intelligence/               → object | null
POST /products/{id}/market-analysis/  {research_inputs?}  → 202
GET  /products/{id}/market-analysis/            → object | null
GET  /stores/{id}/embeddings/                   → {enabled, model, products, embedded}
POST /stores/{id}/embeddings/rebuild/           → 202  (400 when EMBEDDINGS_ENABLED=false)
```
`MarketResearch` keeps `observations` (facts from real fetched sources) separate
from `conclusions` (AI reasoning), plus `web_results` recording every source and
fetch time.

### Content — `apps/content`
```
GET  /products/{id}/image-studio/               → generated images
POST /products/{id}/image-studio/  {kind: POSTER|PRODUCT_SHOT|ENHANCED, style?, instructions?, source_image_id?}  → 202
GET  /products/{id}/captions/                   → captions
POST /products/{id}/captions/      {platforms[], tone?, objective?, image_id?, video_script_id?} → 202
GET  /products/{id}/video-script/               → script (scenes + segments) | null
POST /products/{id}/video-script/  {duration?, objective?, language: fa|en}  → 202
POST /video-scripts/{id}/generate/              → 202   (needs the queue; 503 otherwise)
POST /video-scripts/{id}/voice/                 → 202   (400 before a final video exists)
```
- A poster is generated **from the real product photo** (`flux_img_edit@v1`) when
  one exists, falling back to `flux_txt2img@v1` when it does not. Persian text is
  drawn on afterwards **by code**, and the result is reported in `metadata.text_overlay`
  (or `metadata.text_overlay_error` when the overlay failed).
- `image_id` / `video_script_id` tie a caption to the specific content it is about.
- Re-running `generate` never regenerates segments already `DONE`; a second click
  while a run is in flight returns `409 already_running`.

### Sales agent & support — `apps/customers`
```
POST /stores/{id}/chat/            {message, conversation_id?, customer_name?}
GET  /stores/{id}/conversations/
GET  /conversations/{id}/messages/
POST /conversations/{id}/handoff/  {state: AI|HUMAN|RESOLVED}
GET  /stores/{id}/orders/          ?status=
POST /orders/{id}/receipt/         (multipart: image, note?) → AWAITING_APPROVAL
POST /orders/{id}/confirm/ | /reject/ | /cancel/
GET  /stores/{id}/tickets/         ?status=
POST /tickets/{id}/resolve/        {note?}
GET  /notifications/               ?store=&unread=true   (adds `unread_count`)
POST /notifications/{id}/read/  |  /notifications/read-all/
```
Chat answers **synchronously** (one LLM turn) and returns the reply plus any
validated side effects: `action`, `products`, `order`, `payment_request`,
`ticket`, `open_orders`. Prices, stock and payment details come from the
database; an order the model asks for is re-validated in code before it exists.
A conversation in `HUMAN`/`ESCALATED` state returns `message: null` — the AI
stays silent. When the AI cannot answer at all, the response is `503
ai_unavailable` **and** the owner gets an `AI_ERROR` notification.

### Campaigns & publishing — `apps/campaigns`
```
GET|POST                /campaigns/      ?store={id}
GET|PATCH|DELETE        /campaigns/{id}/
POST                    /campaigns/{id}/approve/
POST                    /campaigns/{id}/reject/   {note?}
POST                    /campaigns/{id}/publish/  {platforms[], resend?}  → 202
```
Only content belonging to the campaign's own product may be attached. Publishing
requires `APPROVED`; delivery status per platform lives in the campaign's
`publish_jobs`. A platform already `SENT` is skipped unless `resend: true`.

### Jobs — `apps/jobs`
```
GET  /jobs/        ?active=true&state=&type=&product_id=&script_id=
GET  /jobs/{id}/
POST /jobs/{id}/cancel/
```
Every read **reaps dead rows first**, so a poller always terminates. `?active=true`
is what the UI uses to re-attach to work still in flight after a page refresh.

### Analytics — `apps/analytics`
```
GET /stores/{id}/analytics/                → products, conversations, orders, campaigns,
                                             publishing, content, ai, jobs
GET /stores/{id}/analytics/timeseries/  ?days=14
GET /stores/{id}/analytics/sales/       ?days=30
```
All values are real aggregations; nothing is sampled or fabricated.

### 2.x Content automation, connections, outbound sales

```text
GET   /stores/{id}/content-automation/   → settings + weekday/approval/mode labels,
PATCH /stores/{id}/content-automation/     the store's products, video length rules
GET   /stores/{id}/connections/          → channel status, which keys are missing,
PATCH /stores/{id}/connections/            and this store's inbound webhook URLs
GET   /stores/{id}/prospects/            → the list, what is due, what is held
POST  /stores/{id}/prospects/
PATCH /stores/{id}/prospects/{pk}/
DELETE /stores/{id}/prospects/{pk}/
GET   /stores/{id}/prospects/{pk}/prep/        → what to read before dialling
GET   /stores/{id}/prospects/{pk}/consent/     → permission to record, or null
POST  /stores/{id}/prospects/{pk}/consent/
DELETE /stores/{id}/prospects/{pk}/consent/    → revoke (the row stays)
GET   /stores/{id}/prospects/{pk}/recordings/
POST  /stores/{id}/prospects/{pk}/recordings/  → multipart `audio`; **403 without consent**
```

`PATCH /connections/` never returns the NovinHub token — only `has_token`. A
credential echoed in a response is one that ends up in a log.

`POST /recordings/` answers **403**, not 400, when there is no active consent
row: nothing about the request was malformed. The rule lives in
`Recording.save`, so the admin and the shell cannot get round it either.

### 2.y Inbound webhooks (no user auth)

```text
GET  /webhooks/{instagram|whatsapp}/{secret}/   → Meta's hub.challenge handshake
POST /webhooks/{telegram|instagram|whatsapp}/{secret}/
```

The caller is a platform, not a person, so there is no JWT. Two things stand in
for it: a per-store secret in the path, and the platform's own signature
(`X-Telegram-Bot-Api-Secret-Token`, or `X-Hub-Signature-256` over the raw body).
Either failing is **403**, and the response never says which.

Everything else is **200**, deliberately — duplicates, receipts, reactions,
echoes of our own replies, and payloads we do not recognise. A platform that
gets anything else retries, backs off, and eventually disables the webhook,
losing the messages that *were* understood. The body says what happened:
`{"ok": true, "accepted": <n>}`.

Delivery is idempotent on the platform's message id, so a retry is
`accepted: 0`. A conversation a human has taken over stores the message and
skips the AI reply.

### 2.z Public site content (no auth)

Read-only, unauthenticated; the public site builds from these and falls back to
the copy in its own repo when they cannot be reached.

```text
GET /blog/articles/  ?category= &tag=     GET /blog/articles/{slug}/
GET /blog/categories/                     GET /blog/redirects/
GET /site/settings/     → name, tagline, contact, keywords (both languages)
GET /site/showcase/     → real outputs; **one `video` per work, never a list**
GET /site/faq/          ?home=1
GET /site/pages/        ?kind=solution|use_case|feature|compare &locale=fa|en
GET /site/proof/        → case studies, customers, testimonials (consented only)
GET /site/resources/    ?kind=guides|templates|checklists|ebooks
```

Media URLs are absolute. A relative `/media/…` resolves against the Next.js
host, where nothing is served — a broken image on the page whose job is proving
the output is real.

---

## 3. Job types

`product_analysis`, `market_analysis`, `caption_generation`, `image_generation`,
`video_script_generation`, `video_generation`, `voice_generation`, `publishing`,
`embedding_build`.

States: `QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`, with
`progress_step` / `total_steps` / `current_step_label` for the progress bar.

---

## 4. Queue-dependent behaviour

The backend decides its mode at startup by probing Redis
(`CELERY_TASK_ALWAYS_EAGER=auto`):

| Redis | Mode | Effect |
|---|---|---|
| up | real queue | everything works, including video generation |
| down | synchronous | AI jobs run inside the request; `POST /video-scripts/{id}/generate/` returns `503 queue_unavailable` with instructions, because a Wan 2.2 render cannot fit in one HTTP request |

---

## 5. Deliberate gaps

| Documented in Phase 0 | Status |
|---|---|
| `WS /ws/jobs/{id}/` live progress | **Not implemented.** Progress is polled (`GET /jobs/{id}/` every 2.5s), which was always specified as the fallback. Django Channels would add an ASGI server and a channel layer for a UI that updates a progress bar every few seconds while a GPU renders for minutes — the cost is not currently justified. |
| `/assets/{id}/download/`, `/assets/{id}/regenerate/` | **Not implemented.** There is no generic `Asset` table; each content type (`GeneratedImage`, `Caption`, `VideoScript`, `VideoSegment`) owns its file and is served directly under `/media/`. Regeneration is "run the same endpoint again". |
| `/publishing/{id}/` | **Not implemented as a separate endpoint.** Per-platform delivery status is returned inline in `GET /campaigns/{id}/` → `publish_jobs`. |
| Nested `/stores/{id}/products/`, `/stores/{id}/campaigns/` | Implemented as `?store=` filters on the flat collections instead. |

---

## 6. Verifying the API

```bash
cd backend
python manage.py test                  # 1444 unit/integration tests
python manage.py selftest              # every AI pipeline vs. a misbehaving fake model
python tools/e2e_api_test.py           # the whole API over HTTP, synchronous mode
python tools/e2e_api_test.py --queue   # same, with real Redis + two Celery workers
```
The last two need no Ollama, no ComfyUI and no GPU — they run the real code
against a fake model stack that reproduces how local models actually misbehave.

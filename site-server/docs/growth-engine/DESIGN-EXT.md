# Growth Engine - extension design: contact extraction, compliance, outreach

This is the contract of three modules added after M2. Backend and frontend are built against it, so the
shapes below are fixed. Foundations they build on (already written and tested):

* `apps/growth_engine/core` - permissions (`IsGrowthStaff`), normalisation (`normalization.py`), CSV, `BackgroundJob`
  base model, throttles, pagination, `conf.get(key)`, test helpers (`testing.py`: `NoNetworkMixin`, `make_staff`, `client_for`).
* `apps/growth_engine/integrations/safe_http.py` - `SafeFetcher` (SSRF guard with pinned IP, robots.txt, per-host spacing,
  retries for GET only, size caps, `post_form` that is attempted once). **All outbound HTTP goes through it.**
* `apps/growth_engine/leads` - `Lead`, `ContactPoint` (identifier registry), `BusinessProfile`, `LeadActivity`;
  services `intake`, `editing`, `history.log_activity`, `drafts.normalize_contact`.
* `apps/growth_engine/sources` - `LeadSource`, `provenance` (`extract_ref(run_id)` -> `extract:<id>`).
* `apps/growth_engine/analytics/registry.py` - `register(name, provider)` adds a block under `dashboard.extra[name]`.
* `apps/growth_engine/discovery/signals.py` - `discovery_job_finished` (sender=DiscoveryJob, job=...).

Rules for every module: staff-only API (`IsGrowthStaff`), business logic in `services/`, views thin, own `models.py` /
`serializers.py` / `views.py` / `urls.py` / `tasks.py` / `tests/`, app label `growth_<name>`, tests use mocked HTTP only
(`httpx.MockTransport` through `SafeFetcher(transport=...)`) and `NoNetworkMixin`. Persian user-facing messages.
Never invent data: every extracted value carries its source page, evidence and confidence.

---------------------------------------------------------------------------------------------------

## 1. `extraction` (label `growth_extraction`) - contact data from the lead's OWN website

### Behaviour
For a lead that has a `website`: fetch the home page, then the pages it links to that look like contact / about /
support pages (max `EXTRACT_MAX_PAGES` = 5 pages in total, same host only), parse them with `httpx` + BeautifulSoup
(`html.parser`; no JavaScript, no Playwright), save what the pages show.

* Page choice: links on the home page scored by anchor text and path. Contact: `contact`, `contact-us`, `contactus`, `call`,
  `reach`, `تماس`, `ارتباط`, `تماس با ما`, `ارتباط با ما`. About: `about`, `about-us`, `aboutus`, `درباره`, `درباره ما`. Support:
  `support`, `ticket`, `help`, `پشتیبانی`, `تیکت`. Order: contact, then about, then support. If the home page links to none of them,
  try (as budget allows) `/contact`, `/contact-us`, `/contactus`, `/about`, `/about-us`. A shared-platform host (`SHARED_PLATFORM_DOMAINS`
  in `core.normalization`, e.g. linktr.ee, instagram.com) is fetched as the single given page only.
* What is extracted (ONLY what the HTML shows):
  | field | where | confidence |
  |---|---|---|
  | `phone` | `tel:` link 90; JSON-LD `telephone` 90; text near a contact word («تلفن», «موبایل», «تماس», «phone», «tel») on a contact/about page 75; same on another page 65; bare number in text 50 | via `normalize_phone` (landline + mobile; Persian digits) |
  | `email` | `mailto:` 90; JSON-LD `email` 90; text on a contact page 80; elsewhere 65; `[at]`/`(at)` obfuscation 50 | via `normalize_email`; placeholders (`is_placeholder_email`) and image-like names are dropped |
  | `instagram` `telegram` `whatsapp` `eitaa` `bale` `rubika` `linkedin` | `<a href>` to the platform's profile (not share/intent/post links) 85; JSON-LD `sameAs` 85 | `whatsapp` = `wa.me/<number>` or `api.whatsapp.com/send?phone=`; the number is normalised |
  | `contact_form` | a page whose `<form>` has a `<textarea>` 85 («فرم تماس»); a ticket/support link 70 («تیکت/پشتیبانی»); a contact page with no form found 55 (label «صفحهٔ تماس (فرمی دیده نشد)») | value = the page URL |
  | `address` | JSON-LD `PostalAddress` 90; `<address>` 80; text after «آدرس:» / «نشانی:» / «Address:» 75 | fill-only into `BusinessProfile.address` |
  | `city` | a known Iranian city name inside a found address, 65 | fill-only into `Lead.city` |
  | `business_name` | JSON-LD Organization/LocalBusiness `name` 80; `og:site_name` 75; `<title>` before ` | ` / ` – ` 55 | fill-only into `Lead.business_name` |
  | `description` | `meta description` / `og:description` 60 (max 500 chars) | fill-only into `Lead.description` |
  | `language` | `<html lang>` | fill-only into `BusinessProfile.language` |
* Saving (`services/apply.py`): contacts become `ContactPoint` rows with `source_ref = extract:<run id>`, `source_url` = the page,
  `evidence` (short text: «لینک tel:», «کنار کلمهٔ تماس»...), `confidence`. A value that already exists on THIS lead is not duplicated
  (finding `reason = already_known`); a value owned by ANOTHER lead is not stolen (`owned_by_other_lead`); an invalid value is dropped
  (`invalid`). Lead fields are **fill-only**: existing values are kept (`kept_existing`) and provenance of filled fields is stamped
  `extract:<run id>`. One `LeadSource(provider=contact_extraction, source_ref=extract:<id>, source_url=<home page>)` per run that added something.
  One `LeadActivity(kind=extraction)` per run with a summary and counts.
* Politeness: `SafeFetcher` (robots.txt, 2 s per host, timeouts, GET-only retries, UA `NMarketingBot/1.0 ...`). Every fetch is logged
  in `ExtractionPageLog` (also robots refusals and failures).
* Never: log in, submit anything, run JS, follow off-site redirects, fetch Instagram.

### Models
* `ExtractionJob(BackgroundJob)`: `scope` (`single` | `selected` | `csv_import`), `discovery_job` FK(null, SET_NULL), counters `runs_done`,
  `runs_failed`, `runs_skipped`, `pages_fetched`, `contacts_added`. `params` = `{"lead_ids": [...], "force": bool}` (ordered snapshot of the
  targets). `total_items` = number of leads, `cursor` = index (1-based) of the last lead fully handled (exact resume, like CSV import).
* `ExtractionRun`: `job` FK(null), `lead` FK, `status` (`queued|running|done|failed|skipped`), `reason` (code: `no_website`, `recent`,
  `robots_blocked`, `robots_unavailable`, `fetch_failed`, `no_pages`, `internal_error`, `""`), `started_at`, `finished_at`, `pages_fetched`,
  `robots_state`, `contacts_added`, `findings` JSON (list, shape below). Unique (`job`, `lead`).
* `ExtractionPageLog`: `run` FK, `url`, `kind` (`home|contact|about|support|guess|robots`), `status` (HTTP, 0 if none), `outcome`
  (from `safe_http` outcomes), `elapsed_ms`, `bytes`, `note`, `created_at`.

Finding item: `{"field", "value", "source_url", "evidence", "confidence", "applied": bool, "reason": "added|already_known|fill_empty|kept_existing|owned_by_other_lead|invalid"}`.

### Celery
`apps.growth_engine.extraction.tasks.run_extraction_job(job_id)`; same job semantics as the CSV import (per-lead transaction with counters + cursor,
cancel flag polled between leads, heartbeat, resume from cursor, stalled detection). Leads without a website are `skipped` (`no_website`);
leads with a successful run in the last `EXTRACT_RECENT_DAYS` are `skipped` (`recent`) unless `force`. At most `EXTRACT_MAX_LEADS_PER_JOB` leads per job.
Receiver of `discovery_job_finished`: if `job.params["extract_after"]` and the job completed, create an extraction job (`scope=csv_import`) for the leads
whose `LeadSource.job` is that job and that have a website, and enqueue it.

### API (`/api/v1/growth/extraction/...`)
* `POST jobs/` `{lead_ids?: int[], discovery_job_id?: int, force?: bool}` (exactly one of the first two) -> `202` job. 400 with a Persian message if nothing is eligible.
* `GET jobs/` (paged), `GET jobs/<id>/`, `POST jobs/<id>/cancel/`, `POST jobs/<id>/resume/`.
  Job JSON = `ExtractionJobInfo` in `frontend/src/features/growth/types.ts` plus `runs: [{id, lead_id, lead_name, status, status_label, reason, reason_label, pages_fetched, contacts_added}]` (first 300).
* `GET leads/<lead_id>/extraction/` -> `{"runs": [ExtractionRunInfo, ...]}` (latest 5 runs, newest first, with `findings` and `pages`).
* Dashboard block `extra.extraction` = `{"leads_extracted": n, "runs_total": n, "contacts_found": n, "last_job": {...}|null}` (counts from the DB).

---------------------------------------------------------------------------------------------------

## 2. `compliance` (label `growth_compliance`) - settings, do-not-contact list, limits, audit

### Models
* `GrowthSettings` (singleton, pk=1, `GrowthSettings.load()`): `sending_enabled` (default **False**), `emergency_stop` (False), `sender_name`,
  `sender_company`, `sender_phone`, `sender_email`, `sender_website` (optional), `opt_out_line` (default `اگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو».`),
  `daily_cap` (40, 1..500), `spacing_min_seconds` (60) / `spacing_max_seconds` (120) (min >= 10, max >= min, max <= 3600), `updated_by`, `updated_at`.
  `identity_problems()` -> list of Persian strings for missing name / company / phone / email / opt-out line;
  `readiness()` -> `{"ok": bool, "problems": [..]}` (identity complete, not stopped; `sending_enabled` is reported separately).
* `SuppressionEntry`: `kind` (`phone|email|website|instagram`), `normalized`, `value`, `reason` (`opt_out|asked_not_to_contact|complaint|invalid_contact|other`), `note`,
  `created_by`, `created_at`; UNIQUE(`kind`, `normalized`). No FK to leads (identifiers only).
* `AuditEntry` (append-only like `LeadActivity`): `kind` (`settings_changed|emergency_stop|emergency_resume|suppress_added|suppress_removed|campaign_status|approval|send_attempt`), `actor`, `summary`, `data`, `created_at`.

### Services
`services/settings.py` (`get_settings()`), `services/suppression.py`: `add_entries(identifiers, reason, note, actor)`, `suppress_lead(lead, reason, note, actor)` (every identifier ContactPoint of the lead),
`remove_entry(...)`, `matches_for_lead(lead)` -> list of entries, `suppressed_lead_ids(lead_ids)` -> set (one query), `classify(raw)` (raw text -> (kind, normalized, value) via `normalize_contact`),
`services/limits.py`: `sent_today()` (count of `SendAttempt`-like attempts today in the Asia/Tehran date, supplied by outreach through `limits.register_counter(fn)` to avoid importing outreach),
`cap_remaining()`, `audit.log(kind, actor, summary, data)`.
`Lead` list/detail serializers add `do_not_contact: bool` using `suppressed_lead_ids` for the page.

### API
* `GET/PATCH /growth/settings/` -> `{...fields, "ready": {"ok", "problems"}, "sent_today": n, "cap_remaining": n, "emergency_stop": bool}`. PATCH validates (see ranges); setting `sending_enabled=true` is refused (400) while identity is incomplete.
* `POST /growth/settings/emergency-stop/` `{"stop": true|false}`; `GET /growth/settings/audit/` -> last 100 entries.
* `GET /growth/compliance/suppression/?q=&page=` (paged), `POST` `{"value": "<phone|email|url|@handle>", "reason", "note"}` or `{"lead_id", "reason", "note"}`,
  `DELETE /growth/compliance/suppression/<id>/`. `POST /growth/leads/<id>/do-not-contact/` `{"reason","note"}` and `DELETE` of the same URL un-suppress the lead's identifiers (both log `LeadActivity` suppressed/unsuppressed + an audit entry).
* Dashboard block `extra.compliance` = `{"suppressed": n, "emergency_stop": bool, "sending_enabled": bool}`.

---------------------------------------------------------------------------------------------------

## 3. `outreach` (label `growth_outreach`) - templates, campaigns, approved automated form submission, manual queue

**Decision of the owner (overrides the earlier "human submits" limit): the system may submit plain contact/ticket forms by itself, but only through the
guard rails below. All are mandatory and tested. Sending to anything that is not a plain HTML form is not built.**

### What may be sent automatically (eligibility, `services/form_analysis.py`, pure functions over HTML)
Only a plain HTML `<form>` on a page reachable without login, on a page and action URL that robots.txt allows. The form is **skipped** - the item becomes
`needs_manual` with a reason code and a Persian text - when ANY of these is detected (never bypassed):
| reason code | detected by |
|---|---|
| `captcha` | reCAPTCHA / hCaptcha / Turnstile / ArCaptcha / other CAPTCHA: `g-recaptcha`, `data-sitekey`, `recaptcha`/`hcaptcha`/`turnstile`/`arcaptcha`/`captcha` in script src, iframe src, class, id, input name; an `<img>` with `captcha` in src/alt; a text input labelled «کد امنیتی», «کپچا», «کد تصویر», «حاصل», «security code», «captcha»; a maths question field |
| `honeypot` | an input hidden from people yet not `type=hidden`: inline `display:none`/`visibility:hidden`/off-screen positioning, `hidden` attribute, `aria-hidden`, `tabindex=-1` + `autocomplete=off`, or a name such as `honeypot`, `hp`, `_gotcha`, `bot-field`, `website_url` inside a hidden wrapper |
| `login_required` | a password input in the form, the page redirected to a login URL, HTTP 401/403, «برای ارسال ... وارد شوید» / «please log in» text |
| `otp_required` | an input named or labelled `otp` / «کد تأیید» / «کد پیامکی» with a «ارسال کد» button |
| `js_only` | no `action` or `action="#"`/`javascript:` AND an inline `onsubmit` that cancels the submit; a page body that is an empty app shell (`<div id="root"></div>`, no `<form>`) |
| `challenge_page` | Cloudflare / similar challenge: title «Just a moment», `cf-chl`, `__cf_chl`, `cf-mitigated`, 403/503 with those markers |
| `file_upload_required` | `<input type=file required>` (an optional file input is simply left empty) |
| `required_field_unfillable` | a required field that cannot be filled truthfully from the sender identity / template (e.g. national code, order number, a required select with no default) |
| `required_checkbox` | a required checkbox (terms, consent) - a person has to decide |
| `no_message_field` | no `<textarea>` / no field that can carry the message |
| `no_form_found`, `no_target_url`, `robots_blocked`, `robots_unavailable`, `fetch_failed` | no form on the page; the lead has no contact-form URL; fetch problems |
Field mapping (heuristic by `name`/`id`/`placeholder`/`<label>`/`type`, Persian and English): name <- `sender_name`; company <- `sender_company`; email <- `sender_email`; phone <- `sender_phone`;
website <- `sender_website` (skip if required and empty); subject <- the template's rendered subject (skip if required and empty); message (`textarea`) <- the rendered message; hidden inputs keep their
page-given values (CSRF/nonce); a `select`/radio with a pre-selected default keeps it; optional unknown fields stay empty. Nothing is guessed or invented.

### Message
`MessageTemplate.body` supports `{business_name} {city} {country} {category} {website} {domain} {instagram}` and a fallback `{city|شهر شما}`; an unknown placeholder is a validation error; an empty value with no fallback
renders empty and adds a warning (never invented text). Final text = rendered body + blank line + sender block (`name | company`, `phone · email`) + blank line + `opt_out_line` from Growth Settings. `generator` field
(default `placeholder`) names the strategy in `services/generators.py` (a registry) - the AI writer of a later milestone registers itself there.

### Models
* `MessageTemplate`: `name`, `subject` (optional, same placeholders), `body`, `language` (`fa|en`), `generator` (`placeholder`), `is_active`, `created_by`, timestamps. Deleting a template used by a campaign is refused (archive with `is_active=False`).
* `Campaign`: `name`, `template` FK(PROTECT), `mode` (`auto` = system submits approved forms; `manual` = human queue only), `status` (`draft|active|paused|completed|cancelled`), `created_by`, `started_at`, `finished_at`, timestamps.
* `OutreachItem`: `campaign` FK, `lead` FK, `domain` (identity of the lead's website, "" if none), `target_url` (contact-form page), `rendered_text` (final text incl. sender block + opt-out), `subject`, `plan` JSON (form analysis, see below),
  `plan_checked_at`, `fingerprint` (hash), `status`, `skip_reason`, `skip_reason_text`, `manual_note`, `approved_record` FK(null) -> `ApprovalRecord`, `forced` bool (manual mode only), timestamps.
  Constraints: UNIQUE(`campaign`, `lead`) (one message per business per campaign); UNIQUE(`campaign`, `domain`) where domain != "" (one per domain per campaign).
  `status`: `pending` (added, not analysed), `ready` (eligible form, waiting for approval), `needs_manual` (skipped for a reason), `approved`, `sending`, `sent`, `failed`, `skipped`, `cancelled`, plus manual outcomes `manual_sent`, `no_form`, `needs_login`.
* `ApprovalRecord` (append-only): `item` FK, `approved_by`, `approved_at`, `fingerprint`, `message_sha256`, `target_url`, `action_url`. An approval is valid only while `item.fingerprint == record.fingerprint` AND `item.status == approved`.
  **Fingerprint** = sha256 of JSON `{lead_id, template_id, target_url, action_url, method, enctype, message text, subject, sorted (field name, value) of every non-hidden field, sorted names of hidden fields}` (hidden VALUES are excluded: tokens change). Any change to the message, target, action or field set (e.g. a CAPTCHA appears) changes it, flips `approved` back to `ready` and records an audit entry.
* `SendAttempt` (one per item, ever): `item` FK(unique), `attempted_at`, `url`, `method`, `payload` JSON (the exact fields posted; hidden token values redacted to `"***"` in the stored copy), `status_code`, `response_snippet` (<= `SEND_SNIPPET_CHARS` of visible text), `success_guess` (`likely_success|unclear|likely_failure`), `outcome` (`safe_http` outcome), `error`, `elapsed_ms`.
  Success heuristic: 2xx/3xx and the landing text (or the POST response) contains thank-you markers («ممنون», «با تشکر», «ارسال شد», «دریافت شد», «پیام شما», `thank`, `success`, `received`) = likely_success; error/captcha/validation markers («خطا», «نامعتبر», «captcha», `error`, `invalid`, `required`) or 4xx/5xx = likely_failure; otherwise unclear. Item becomes `sent` for 2xx/3xx (guess recorded) and `failed` otherwise. **No automatic retry, ever** (a timed-out POST may have been delivered).
* `OutreachJob(BackgroundJob)`: `campaign` FK, `kind` (`prepare` = fetch and analyse the forms, `send` = submit approved items). Celery tasks `apps.growth_engine.outreach.tasks.run_prepare_job` and `run_send_job`; same job semantics as the CSV import (counters + cursor, heartbeat, cancel flag, resume, stalled detection). `total_items` = items to prepare / approved items at start.

### The guard (`services/guard.py`): `check_item(item) -> (ok, code, text)`, evaluated at approval time AND again immediately before every send
1 contact eligibility (target URL present, plan verdict eligible) - 2 channel permission (`sending_enabled`, identity complete, `emergency_stop` off, campaign `mode=auto`) - 3 suppression (`compliance.suppression`, by every identifier of the lead) -
4 duplicate communication (no earlier item for the same lead + template with status in `sent|sending|manual_sent|failed` in ANY campaign; no earlier attempt to the same domain in this campaign; the item has no `SendAttempt`) -
5 campaign status (`active`) - 6 human approval (valid `ApprovalRecord`, fingerprint equals the freshly recomputed one).
Limits: global daily cap (`GrowthSettings.daily_cap`, counted per Tehran day over all campaigns), spacing between two sends `random.uniform(min, max)` seconds (randomised only to space them), at most one send per domain. When the cap is reached the job ends `completed` with a note and the campaign stays `active`; pressing «ادامه ارسال» next day starts a new job.

### Send job algorithm
loop: stop at once (job `cancelled`, reason in `error`) if `emergency_stop`, `sending_enabled` off, campaign not `active`, or cancel requested (checked every second, also during spacing). Pick the next `approved` item (lowest id); claim it with a conditional UPDATE `approved -> sending` (at-most-once even if two tasks run). Run the guard; if it fails the item goes to `needs_manual`/`skipped` with the reason and the loop continues without waiting. Re-fetch the form page through `SafeFetcher`, rebuild the plan, recompute the fingerprint: if it differs, the item returns to `ready` (approval invalid) and nothing is sent. Otherwise `post_form` once, write `SendAttempt`, update the item, write a `LeadActivity(kind=queue_outcome)` whose `data` holds `{outcome, message_text, subject, target_url, payload, http_status, success_guess, response_snippet, campaign_id, template_id, item_id}` and an audit entry. Then wait the spacing. Status/progress: `processed_items` = items finished by this job.

### Manual queue (kept for every skipped lead, and for `mode=manual` campaigns)
Item outcome endpoint with `{"outcome": "sent|no_form|needs_login|skipped", "note"}` -> statuses `manual_sent|no_form|needs_login|skipped`; logs `LeadActivity(queue_outcome)` with the exact message text, target URL and note; `manual_sent` advances a lead in `new/researched/qualified/ready_for_outreach` to `contacted` (logged). The rule "same lead + same template at most once" applies to manual too unless `force=true` when adding.
Adding to a campaign (`POST campaigns/<id>/add-leads/`) skips, with reason codes: `already_in_campaign`, `already_contacted` (same lead + template sent/failed before; for manual mode only with `force` the lead is added), `suppressed`, `archived`, `duplicate_domain`, `no_target_url` (auto mode only; manual mode accepts leads without a URL), `limit` (max `SEND_MAX_ITEMS_PER_CAMPAIGN`).

### API (`/api/v1/growth/outreach/...`)
* Templates: `GET|POST templates/`, `GET|PATCH|DELETE templates/<id>/`, `POST templates/preview/` `{body, subject?, lead_id?}` -> `{text, subject, warnings: [...], unknown_placeholders: [...]}`, `GET placeholders/` -> `[{key, label, example_source}]`.
* Campaigns: `GET|POST campaigns/` (create `{name, template_id, mode, lead_ids?: int[], force?: bool}` -> 201 with the campaign), `GET|PATCH campaigns/<id>/` (name only),
  `POST campaigns/<id>/add-leads/` `{lead_ids, force?}` -> `{added: n, skipped: [{lead_id, lead_name, reason, reason_text}]}`, `POST campaigns/<id>/remove-items/` `{item_ids}` (not `sent`/`sending`),
  `POST campaigns/<id>/prepare/` (Celery job `kind=prepare`: for every `pending` item - and `ready`/`needs_manual` ones whose reason was a fetch problem - fetch the form page through `SafeFetcher`, build the plan, set `ready` or `needs_manual`; returns the serialised `OutreachJob`),
  `POST campaigns/<id>/approve/` `{item_ids: [...] | all_ready: true}` (each item is re-checked by the guard; response `{approved: n, refused: [{item_id, code, text}]}`), `POST campaigns/<id>/revoke/` `{item_ids}`,
  `POST campaigns/<id>/start/` (draft/paused -> active, starts a send job if there are approved items; 400 with the guard text if sending is not ready), `POST campaigns/<id>/pause/`, `POST campaigns/<id>/cancel/` (pending/ready/approved items -> `cancelled`),
  `GET campaigns/<id>/status/` -> `{campaign, counts: {status: n}, job: OutreachJob|null, sent_today, daily_cap, cap_remaining, readiness: {...}, emergency_stop}`.
* Items: `GET campaigns/<id>/items/?status=&q=&page=` (paged, with lead summary, `plan` summary, `approval: {valid, by, at}`, `attempt`), `GET|PATCH campaigns/<id>/items/<item_id>/` (PATCH `{rendered_text?, subject?}` -> recompute fingerprint, approval invalidated),
  `POST .../items/<item_id>/rerender/`, `POST .../items/<item_id>/outcome/` `{outcome, note}`, item detail includes the **dry-run**: `plan = {page_url, action_url, method, enctype, verdict, reasons: [{code, text}], fields: [{name, type, label, source, value, hidden}], detected: {...}}`.
* Jobs: `GET jobs/<id>/`, `POST jobs/<id>/cancel/`, `POST jobs/<id>/resume/`.
* Dashboard block `extra.outreach` = `{"sent_today": n, "daily_cap": n, "campaigns_active": n, "items_ready": n, "items_needs_manual": n, "sent_total": n}`.

### Frontend flows (see `frontend/src/features/growth/pages`)
Templates page (list/editor with live preview and placeholder buttons); Outreach page (campaign list + «کمپین تازه» wizard: pick template, mode, leads from the lead table via the bulk bar or `?lead_ids=` hand-off);
Campaign page: counters, readiness banner, «آماده‌سازی» (prepare), items table with status filter, a **review drawer per item** (rendered message editable, target page, exact payload table = dry-run, reasons),
batch select + «تأیید انتخاب‌شده», «شروع/توقف/لغو», progress of the running job, emergency-stop banner; **manual queue view** (keyboard-fast: one lead at a time, `C` copy message, `O` open contact page in a new tab, `S` sent, `N` no form,
`L` needs login, `K` skip, arrows move, auto-advance, a progress counter and a «تماس نگیر» key `D`). Growth Settings page: identity form, opt-out line, cap and spacing, `sending_enabled` switch, red **emergency stop** button, readiness list, audit list.

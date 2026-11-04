# معماریِ «جذب مشتری» (Growth Engine) — بررسیِ مخزن (Milestone 0)

این سند همان «ممیزیِ مخزن» است که مشخصاتِ اصلی (`SPEC.md`، بخش ۲) پیش از نوشتنِ هر کد خواسته بود.
ترتیبِ بخش‌ها همان هشت موردِ مشخصات است. هرچه اینجا آمده از خودِ مخزن و سرورِ زنده دیده شده، نه حدس.

> نام‌ها: «لید» = یک کسب‌وکاری که ممکن است مشتریِ آپ‌مارکت شود. «کشف» = واردکردنِ لید. «استخراج» = خواندنِ راهِ تماس از سایتِ خودِ کسب‌وکار.

---

## ۱. معماریِ فعلی (پیش از این کار)

| بخش | واقعیتی که دیدیم |
|---|---|
| بک‌اند | Django 5.2 + Django REST Framework 3.18 + SimpleJWT. پایتون ۳٫۱۰. کد در `/var/www/NM/upmarket/backend` |
| دیتابیس | **SQLite** با حالتِ WAL، فایلِ زندهٔ `data/db.sqlite3`. یک SQLite دومِ جدا به نامِ `studio` (سایت‌ساز) که `StudioRouter` جدول‌هایش را جدا نگه می‌دارد. Postgres فقط وقتی `DATABASE_URL` تنظیم شود (الان نیست) |
| کارهای پس‌زمینه | Celery 5.6 + Redis. سرویسِ `nm-celery` با `--pool=threads --concurrency=4` و صف‌های `celery,ai,gpu`؛ `nm-celery-beat` برنامه‌ریزِ زمان‌بندی |
| وب | `nm-web` (gunicorn، پورتِ ۸۰۴۱، ۲ worker × ۸ thread). nginx روی پورتِ ۸۰۴۰ همه‌چیز را یکجا می‌دهد: `/panel/` فایل‌های ساخته‌شدهٔ React، `/api/` و `/admin/` به gunicorn، `/` سایتِ عمومی |
| سایتِ عمومی | Next.js در سرویسِ `nm-website` (پورتِ ۳۰۰۱). **این کار دستش نمی‌زند** |
| سرویس‌های دیگر | `nm-up3d-orchestrator` و `nm-up3d-worker` (ویدیوی سه‌بعدی)؛ سایت‌ساز؛ سرورهای پردازشِ GPU (`apps/compute`) |
| فرانت‌اند | React 18 + Vite 5 + TypeScript + Tailwind 4، فونتِ Vazirmatn، پنل زیرِ `/panel/`، راست‌به‌چپ، تمِ تیره و روشن با توکن‌های CSS |
| احرازِ هویت | JWT (SimpleJWT) برای پنل؛ سشنِ جنگو فقط برای ادمین. نقش‌ها: `User.is_staff` + «پرچم‌های پنل» (`apps/panel`: دسته/صفحه/قابلیت که از ادمینِ جنگو روشن و خاموش می‌شوند) |
| هوش مصنوعی | `services/ai/gateway.py` در `apps/*` تنها دروازه است. **به فروشگاه (`store`) بسته است**: بدونِ فروشگاه صدا زده نمی‌شود (سیاستِ دادهٔ هر فروشگاه را می‌سنجد) |
| اپ‌های موجود | `accounts, stores, products, jobs, ai, customers, content, campaigns, analytics, cms, billing, marketing, api_platform, regen, photoedit, shoot, compute, panel, up3d, projects (+code_generation, template_editor, ai_engine, project_importer در دیتابیسِ studio)` |
| نامِ مشترک! | `apps.marketing.models.Lead` همان «لیدِ فرمِ تماسِ سایتِ عمومی» است و در ادمین «لید» نام دارد. لیدِ جذب مشتری مدلِ **جدایی** است (`growth_leads.Lead`، نامِ ادمین «لیدِ جذب مشتری») |
| اجزای مشترکِ UI | `components/ui.tsx` (Button، Card، Badge، Table، Alert، EmptyState، Spinner، Field…)، `components/charts.tsx` (StatTile، StatRow، DailyBarChart)، `components/Icon.tsx` (آیکون‌های دست‌ساز)، کلاس‌های `u-*` و توکن‌هایی مثلِ `var(--text-3)`، `PageGate` برای خاموش‌کردنِ صفحه |
| نبودها | کتابخانهٔ **Recharts نصب نیست** (نمودارها با `charts.tsx` کشیده می‌شوند، پس وابستگیِ تازه نیامد). **BeautifulSoup (bs4) نصب نبود**؛ `httpx` از قبل نصب بود (۰٫۲۸) ولی در `requirements.txt` نبود |

---

## ۲. معماریِ پیشنهادی و اجراشده (ادغام)

**یک مونولیتِ ماژولار** داخلِ همان پروژه؛ نه سرویسِ جدا، نه دیتابیسِ جدا، نه احرازِ هویتِ جدا.

```
backend/apps/growth_engine/
  core/          ← بسته‌ٔ ساده (اپِ جنگو نیست)  مجوز، نرمال‌سازی، CSV، مدلِ پایهٔ کار، تنظیمات
  integrations/  ← بسته‌ٔ ساده  safe_http.py : تنها راهِ رفتن به سایتِ دیگران
  analytics/     ← بسته‌ٔ ساده  داشبورد (+ نقطهٔ توسعه registry)
  sources/       ← اپِ جنگو  growth_sources     LeadSource + provenance
  leads/         ← اپِ جنگو  growth_leads       Lead، ContactPoint، پروفایل، یادداشت، تاریخچه
  discovery/     ← اپِ جنگو  growth_discovery   ثبتِ دستی + ورودِ CSV (کار پس‌زمینه)
  extraction/    ← اپِ جنگو  growth_extraction  خواندنِ راهِ تماس از سایتِ لید
  compliance/    ← اپِ جنگو  growth_compliance  تنظیمات، «تماس نگیر»، سقف، ممیزی
  outreach/      ← اپِ جنگو  growth_outreach    قالب، کمپین، ارسالِ تأییدشدهٔ فرم، صفِ دستی
```

**جهتِ وابستگی** (پیکان = «از … استفاده می‌کند»؛ هیچ چرخه‌ای نیست):

```
integrations ──► core
sources, leads ──► core            (leads از sources استفاده می‌کند؛ ارجاعِ مدلِ sources به leads/discovery فقط با رشته است)
discovery ──► leads, sources, core
analytics ──► discovery, leads     (+ هر ماژول خودش بلوکش را در registry ثبت می‌کند، analytics آن‌ها را نمی‌شناسد)
extraction ──► discovery (فقط DiscoveryJob), leads, sources, integrations, core
compliance ──► leads, core         (leads فقط در view، سرِ تنبل، پرسشِ «تماس نگیر» را از compliance می‌پرسد)
outreach ──► leads, compliance, integrations, core
```

- هر ماژولِ اپ‌دار مدل، serializer، service، view، url، task و تستِ خودش را دارد. **منطق در `services/` است؛ view فقط درخواست را می‌خواند و جواب می‌سازد.**
- ماژول‌های اختیاری (`extraction`، `compliance`، `outreach`) فقط وقتی در `INSTALLED_APPS` باشند به `urls.py` وصل می‌شوند (`apps.is_installed`)؛ برداشتنشان فایلِ مشترکی را نمی‌شکند.
- **نقطه‌های توسعه** بدونِ دانستنِ هم: `analytics.registry.register(name, fn)` (بلوکِ داشبورد)، سیگنالِ `discovery.signals.discovery_job_finished`، `compliance.services.limits.register_counter` (شمارندهٔ سقفِ روزانه)، رجیستریِ `generators` در outreach (جای پیام‌نویسِ هوش مصنوعی).
- **پنل:** بخشِ تازهٔ `growth` («جذب مشتری»، فقط کارکنان) در `apps/panel/registry.py` (با migrate در دیتابیسِ پرچم‌ها کاشته می‌شود و از ادمینِ جنگو خاموش/روشن می‌شود) و همتایش در `frontend/src/features/panel/registry.ts`. مسیرِ فرانت: `/growth/*`، کدِ فرانت: `frontend/src/features/growth/`.
- **فایل‌های مشتری که دست خورد** (همه افزودنی): `config/settings.py` (یک بلوک در انتها: اپ‌ها، نرخِ throttle، `GROWTH_ENGINE`)، `config/urls.py` (یک خط)، `apps/panel/registry.py`، `frontend/src/App.tsx`، `features/panel/registry.ts`، `components/Icon.tsx` (چند آیکون)، `backend/requirements.txt` (`beautifulsoup4`، `httpx`).

### چرا این‌طور و نه جور دیگر
| تصمیم | دلیل |
|---|---|
| **دیتابیس همان SQLite ماند** | مالک خواست؛ سوئیچ به Postgres ریسکِ بی‌دلیل بود. کارهای طولانی با تراکنش‌های کوتاهِ هر ردیف و WAL نویسنده را قفل نمی‌کنند |
| **احرازِ هویتِ تازه نساختیم** | همان JWT و `is_staff`؛ فقط کلاسِ `IsGrowthStaff` (کاربرِ فعال + کارمند) روی همهٔ endpointها |
| **سرویسِ AI تازه نساختیم** | AI در این دورِ کار لازم نبود (M5/M6)؛ دروازهٔ موجود به فروشگاه بسته است و برای ابزارِ داخلی تصمیمی لازم دارد (بخش ۸) |
| **HTTP به بیرون فقط از `safe_http.py`** | یک جا SSRF، robots.txt، فاصله، timeout و ارسالِ یک‌باره را اجرا می‌کند؛ کدِ دیگری حق ندارد مستقیم `requests`/`httpx` بزند |
| **ماژول‌ها اپِ جدا با برچسبِ `growth_*`** | جدول‌ها `growth_<ماژول>_<مدل>` می‌شوند و هرگز با اپ‌های دیگر قاطی نمی‌شوند |

### جای ماژول‌های بعدی (M3 تا M10)
| milestone | کجا وصل می‌شود |
|---|---|
| M3 کشفِ خودکار | `discovery/providers/` (رابطِ مشترکِ provider) + `DiscoveryJob.kind=search`؛ منبعِ جدید در `SourceProvider`؛ از همان `safe_http` و همان جریانِ «تکراری ← ادغام/رد» استفاده می‌کند |
| M4 کاملِ استخراج | Playwright فقط وقتی لازم و مجاز؛ همین پارسر/`apply` |
| M5 تحلیل و امتیاز | ماژولِ `intelligence` و `qualification`؛ امتیاز در تنظیماتِ ادمین؛ بلوکِ داشبورد با `registry` |
| M6/M7 پیام‌نویسِ AI و کمپین | `outreach.services.generators` (رجیستری) و `ai_writer`؛ نیازمندِ تصمیم دربارهٔ دروازهٔ AI |
| M8 ارائه‌دهنده‌های ارسال | `outreach/providers/` با `validate/send/get_status/handle_webhook`؛ نگهبانِ شش‌مرحله‌ای (`guard.py`) از همین حالا همهٔ ارسال‌ها را کنترل می‌کند |
| M9 قیف فروش و تحلیل | `analytics` + وضعیت‌های `Lead.status` که از همین حالا هستند |
| M10 یکپارچه‌سازی و مستندات | روی همین مستندات |

---

## ۳. ساختارِ پوشه‌ها

```
backend/apps/growth_engine/
├── urls.py                  همهٔ endpointها زیرِ /api/v1/growth/ (ماژول‌های اختیاری شرطی)
├── meta.py                  GET /growth/meta/ : واژگان و حدها
├── core/
│   ├── permissions.py       IsGrowthStaff
│   ├── throttles.py         growth_upload / growth_export / growth_bulk
│   ├── pagination.py        صفحه‌بندی (۲۵، حداکثر ۱۰۰)
│   ├── conf.py              پیش‌فرضِ همهٔ حدها (conf.get)
│   ├── models.py            BackgroundJob (انتزاعی)
│   ├── normalization.py     URL، دامنه، اینستاگرام، تلفن، ایمیل، کشور، متن
│   ├── csvio.py             خواندن/نوشتنِ CSV + محافظِ فرمول
│   └── testing.py           NoNetworkMixin، make_staff، TempMediaMixin
├── integrations/safe_http.py   SafeFetcher (GET با retry، post_form یک‌باره)
├── analytics/               services.py (داشبورد)، registry.py، views/urls
├── sources/                 models.py (LeadSource)، provenance.py
├── leads/
│   ├── models.py choices.py serializers.py views.py urls.py admin.py api_utils.py
│   └── services/            drafts intake dedupe editing bulk queries export history tags
├── discovery/
│   ├── models.py views.py urls.py serializers.py tasks.py signals.py admin.py
│   └── services/            csv_upload csv_mapping csv_import manual
├── extraction/
│   ├── models.py views.py urls.py serializers.py tasks.py receivers.py admin.py apps.py
│   ├── services/            parser crawler apply runner dashboard
│   └── tests/fixtures/      صفحه‌های HTMLِ نمونه
├── compliance/
│   ├── models.py views.py urls.py admin.py apps.py
│   └── services/            settings suppression limits audit dashboard
└── outreach/                قالب، کمپین، تحلیلِ فرم، نگهبان، کارِ ارسال (جزئیات: MODULES.md)
    └── services/            form_analysis form_antibot form_mapping form_reasons rendering generators fingerprint guard approval campaigns items preparing targets limits (+ کارِ ارسال)

frontend/src/features/growth/
├── index.tsx (مسیرها) GrowthLayout.tsx MetaContext.tsx api.ts types.ts format.ts
├── components/              Modal، Pagination، bits، dashboard/، discovery/، leads/، extraction/، outreach/
├── outreach/                types.ts labels.ts api.ts
└── pages/                   Dashboard، Discovery، Leads، LeadDetail، Outreach، Campaign، Templates، Suppression، Settings

docs/growth-engine/          README، ARCHITECTURE، MODULES، API، OPERATIONS، SPEC، DESIGN-EXT، modules/*
```

---

## ۴. طرحِ دیتابیس

همهٔ جدول‌ها در دیتابیسِ `default` (همان `db.sqlite3`) هستند. کارها (`*job`) همه از `BackgroundJob` این ستون‌ها را دارند:
`status` (queued/running/completed/failed/cancelled)، `params` (JSON)، `total_items`، `processed_items`، `cursor`، `attempts`، `cancel_requested`، `error`، `celery_task_id`، `created_by`، `queued_at`، `started_at`، `finished_at`، `heartbeat_at`.

### ایدهٔ اصلیِ ضدِ تکرار: «دفترِ شناسه‌ها»
جدولِ `ContactPoint` هم راهِ تماس است و هم **دفترِ شناسه‌ها**. روی `(kind, normalized)` یک **قیدِ یکتایِ جزئی** هست که فقط برای نوع‌های `phone, email, website, instagram` و فقط وقتی `normalized` خالی نیست اعمال می‌شود (`growth_contact_identifier_unique`). یعنی دو لید هرگز نمی‌توانند یک تلفن/ایمیل/سایت/اینستاگرام را داشته باشند، و حتی اگر دو درخواستِ هم‌زمان هم از «بررسی» رد شوند، خودِ دیتابیس دومی را رد می‌کند و کد آن را «تکراری» گزارش می‌دهد (نه خطا).

### `growth_leads` (لیدها)
| جدول | ستون‌های کلیدی | قید / ایندکس |
|---|---|---|
| `growth_leads_lead` | `business_name`، `name_key` (کلیدِ جست‌وجو: بدونِ فاصله/ZWNJ/نشانه)، `website`، `instagram_url`، `category`، `description`، `country` (ISO دوحرفی)، `city`، `status`، `origin`، `is_archived`، `provenance` (JSON: منبعِ هر فیلد)، `created_by`، `created_at/updated_at` | `gl_lead_arch_status_idx` (is_archived,status,-created_at) · `gl_lead_arch_created_idx` · `gl_lead_place_idx` (country,city) · `gl_lead_category_idx` · `gl_lead_origin_idx` · `gl_lead_updated_idx` · ایندکسِ `name_key` |
| `growth_leads_contactpoint` | `lead`، `kind` (phone/email/website/instagram/whatsapp/telegram/eitaa/bale/rubika/linkedin/contact_form/other)، `value`، `normalized`، `label`، `is_primary`، `source_ref`، `source_url`، `evidence`، `confidence` (۰ تا ۱۰۰) | **یکتای جزئیِ `(kind, normalized)`** برای ۴ نوعِ شناسه · `gl_contact_kind_norm_idx` · `gl_contact_lead_kind_idx` |
| `growth_leads_businessprofile` | یک‌به‌یک با لید: `language`، `business_type`، `product_categories` (JSON)، `product_names` (JSON)، `address`، `provenance` | — |
| `growth_leads_leadtag` + جدولِ M2M `growth_leads_lead_tags` | `name`، `name_key` (یکتا؛ «کمپین ۱» = «کمپین‌۱»)، `color` | یکتایِ `name_key` |
| `growth_leads_leadnote` | `lead`، `author`، `body` | — |
| `growth_leads_leadactivity` | `lead`، `kind`، `actor`، `summary`، `data` (JSON)، `source_ref`، `created_at` — **فقط‌افزودنی** (ویرایش خطا می‌دهد) | `gl_activity_lead_idx` (lead,-created_at) · `gl_activity_kind_idx` |

### `growth_sources`
| جدول | ستون‌ها | ایندکس |
|---|---|---|
| `growth_sources_leadsource` | `lead`، `provider` (manual/website_url/instagram_url/business_name/csv_import/contact_extraction)، `source_ref` (`manual` / `csv:<فایل>:<ردیف>` / `extract:<اجرا>`)، `source_url`، `discovered_at`، `job` (کارِ کشف)، `created_by`، `raw_data` (ورودیِ خامِ بدونِ دست‌کاری) | `gs_source_lead_idx` · `gs_source_provider_idx` · `gs_source_job_idx` |

### `growth_discovery`
| جدول | ستون‌ها | قید / ایندکس |
|---|---|---|
| `growth_discovery_discoveryjob` | کارِ پایه + `kind` (csv_import)، `file_name`، `stored_name` (پس از پایانِ کار پاک می‌شود)، `encoding`، شمارنده‌ها `created_count/merged_count/skipped_count/duplicate_count/error_count` | `gd_job_status_idx` |
| `growth_discovery_discoveryjobrow` | ردیف‌هایی که لیدِ ساده نشدند: `job`، `row_number` (شمارهٔ ردیفِ اکسل؛ عنوان = ۱)، `status` (error/duplicate/merged/skipped/created)، `raw`، `payload`، `errors`، `matches`، `matched_lead`، `resolved_by/at` | یکتای `(job,row_number)` · `gd_row_job_status_idx` |

### `growth_extraction`
| جدول | ستون‌ها | قید / ایندکس |
|---|---|---|
| `growth_extraction_extractionjob` | کارِ پایه + `scope` (single/selected/csv_import)، `discovery_job`، `runs_done/runs_failed/runs_skipped`، `pages_fetched`، `contacts_added`؛ `params` = `{lead_ids, force}` | `ge_job_status_idx` |
| `growth_extraction_extractionrun` | `job`، `lead`، `status` (queued/running/done/failed/skipped)، `reason`، `started_at/finished_at`، `pages_fetched`، `robots_state`، `contacts_added`، `findings` (JSON) | یکتای `(job,lead)` · `ge_run_lead_idx` · `ge_run_lead_status_idx` |
| `growth_extraction_extractionpagelog` | `run`، `url`، `kind` (home/contact/about/support/guess/robots)، `status` (HTTP)، `outcome`، `elapsed_ms`، `bytes`، `note` | `ge_page_run_idx` |

### `growth_compliance`
| جدول | ستون‌ها | قید / ایندکس |
|---|---|---|
| `growth_compliance_growthsettings` | **تک‌ردیفی (pk=1)**: `sending_enabled` (پیش‌فرض **خاموش**)، `emergency_stop`، `sender_name/company/phone/email/website`، `opt_out_line`، `daily_cap` (۴۰)، `spacing_min_seconds` (۶۰)، `spacing_max_seconds` (۱۲۰)، `updated_by/at` | singleton در `save()` |
| `growth_compliance_suppressionentry` | `kind` (phone/email/website/instagram)، `normalized`، `value`، `reason`، `note`، `created_by/at` — بدونِ ارتباط با لید؛ خودِ شناسه مسدود است | یکتای `(kind,normalized)` · `gc_suppress_lookup_idx` |
| `growth_compliance_auditentry` | `kind`، `actor`، `summary`، `data`، `created_at` — **فقط‌افزودنی** | `gc_audit_kind_idx` |

### `growth_outreach` (از `outreach/models.py`؛ منطقِ سرویس‌ها طبقِ `DESIGN-EXT.md` بخش ۳ است)
| جدول | ستون‌های کلیدی | قید / ایندکس |
|---|---|---|
| `growth_outreach_messagetemplate` | `name`، `subject`، `body`، `language` (fa/en)، `generator` (`placeholder`)، `is_active`، `created_by` | — (قالبِ استفاده‌شده حذف نمی‌شود: کمپین `PROTECT` دارد؛ بایگانی کنید) |
| `growth_outreach_campaign` | `name`، `template` (PROTECT)، `mode` (auto/manual)، `status` (draft/active/paused/completed/cancelled)، `started_at/finished_at` | `go_campaign_status_idx` |
| `growth_outreach_outreachitem` | `campaign`، `lead` (CASCADE)، `domain`، `target_url`، `subject`، `rendered_text`، `text_edited`، `plan` (JSON تحلیلِ فرم = dry-run)، `plan_checked_at`، `fingerprint`، `status`، `skip_reason`/`skip_reason_text`، `manual_note`، `approved_record`، `forced` | یکتای `(campaign, lead)` = `growth_item_one_per_lead_per_campaign` · یکتای `(campaign, domain)` برای دامنهٔ غیرخالی = `growth_item_one_per_domain_per_campaign` · `go_item_campaign_status_idx` · `go_item_lead_status_idx` |
| `growth_outreach_approvalrecord` | `item`، `approved_by`، `approved_at`، `fingerprint`، `message_sha256`، `target_url`، `action_url` — **فقط‌افزودنی** (ویرایش خطا می‌دهد) | — |
| `growth_outreach_sendattempt` | `item` (**یک‌به‌یک**: هر آیتم حداکثر یک تلاشِ ارسال، تا ابد)، `attempted_at`، `url`، `method`، `payload` (لیستِ `{name,value}`؛ مقدارِ فیلدهای پنهانِ صفحه `***`)، `status_code`، `response_snippet`، `success_guess`، `outcome`، `error`، `elapsed_ms` | `go_attempt_time_idx` (برای شمارشِ سقفِ روزانه) |
| `growth_outreach_outreachjob` | کارِ پایه + `campaign`، `kind` (prepare/send)، `items_sent/items_failed/items_blocked`، `note` («سقفِ روزانه پر شد») | `go_job_campaign_idx` |

وضعیتِ آیتم: `pending, ready, needs_manual, approved, sending, sent, failed, skipped, cancelled, manual_sent, no_form, needs_login`.

---

## ۵. مشخصاتِ API (خلاصه)

پایه: `/api/v1/growth/` — همه با JWT و فقط `is_staff`. جزئیاتِ کاملِ هر endpoint (بدنه، پاسخ، خطا) در `API.md`.

| گروه | endpointها |
|---|---|
| واژگان و داشبورد | `GET meta/` · `GET dashboard/` |
| لیدها | `GET leads/` · `GET/PATCH/DELETE leads/<id>/` · `GET leads/<id>/activity/` · `GET/POST leads/<id>/notes/` · `PATCH/DELETE leads/<id>/notes/<nid>/` · `POST leads/<id>/contacts/` · `PATCH/DELETE leads/<id>/contacts/<cid>/` · `POST leads/bulk/` · `GET leads/export/` · `GET tags/` |
| کشف | `POST discovery/manual/check/` · `POST discovery/manual/` · `POST discovery/csv/upload/` · `POST discovery/csv/check/` · `POST discovery/csv/import/` · `GET discovery/jobs/` · `GET discovery/jobs/<id>/` · `GET discovery/jobs/<id>/rows/` · `GET discovery/jobs/<id>/errors.csv` · `POST discovery/jobs/<id>/{cancel,resume,resolve}/` |
| استخراج | `POST/GET extraction/jobs/` · `GET extraction/jobs/<id>/` · `POST extraction/jobs/<id>/{cancel,resume}/` · `GET leads/<id>/extraction/` |
| رعایتِ قواعد | `GET/PATCH settings/` · `POST settings/emergency-stop/` · `GET settings/audit/` · `GET/POST compliance/suppression/` · `DELETE compliance/suppression/<id>/` · `POST/DELETE leads/<id>/do-not-contact/` |
| پیام‌رسانی | قالب‌ها `outreach/templates/…` · کمپین‌ها `outreach/campaigns/…` (add-leads، prepare، approve، revoke، start، pause، cancel، status، items) · آیتم‌ها (ویرایش، rerender، outcome) · کارها `outreach/jobs/…` |

کدهای خطا: `400 {code:"validation", detail, errors:[{field,code,message}]}` · `409 {code:"duplicate", detail, duplicates:[…]}` · `401/403` برای غیرِ کارمند · `404` · `429` برای throttle.

---

## ۶. مراحلِ توسعه و وضعیتِ راستینِ هرکدام

| مرحله | وضعیت | توضیح |
|---|---|---|
| **M0** ممیزی و معماری | **انجام شد** | همین سند |
| **M1** مدل‌ها، ساختارِ API، منو و داشبورد | **انجام شد** | بخشِ «جذب مشتری» در منو، داشبوردِ با عددِ واقعی؛ هیچ عددِ ساختگی نیست |
| **M2** کشفِ دستی، CSV و مدیریتِ لید | **انجام شد** | ثبتِ دستی (آدرس سایت، پیج اینستاگرام، نام، فرمِ کامل)، CSV با نگاشتِ ستون و پیش‌نمایش و گزارشِ خطای ردیفی، ضدِ تکرار با ادغام/ردِ دستی، جست‌وجو/فیلتر/مرتب‌سازی/صفحه‌بندی/انتخابِ گروهی/ویرایش/تاریخچه، خروجیِ CSV |
| M3 چارچوبِ کشفِ خودکار | **شروع نشده** | منتظرِ پاسخِ مالک دربارهٔ APIها/دایرکتوری‌های مجاز و کلیدها |
| **M4 (محدود)** استخراجِ راهِ تماس | **انجام شد — به‌عنوانِ گسترشِ دامنه** | فقط راهِ تماس از سایتِ خودِ لید (HTML ساده؛ بدونِ Playwright). استخراجِ محصول/قیمت و تحلیلِ عمیق انجام نشده |
| M5 تحلیلِ کسب‌وکار و امتیازدهی | **شروع نشده** | |
| M6 پژوهشگرِ فروشِ AI و پایگاهِ دانشِ محصول | **شروع نشده** | |
| **M7 (محدود)** قالبِ پیام و کمپین | **انجام شد — به‌عنوانِ گسترشِ دامنه** | قالبِ دستی با جاگذار؛ **بدونِ پیام‌نویسِ AI** (فقط جایش در `generators` هست) |
| **M8 (محدود)** رعایتِ قواعد و ارسال | **انجام شد — به‌عنوانِ گسترشِ دامنه** | فقط ارسالِ تأییدشدهٔ فرمِ تماسِ ساده + صفِ دستی؛ ایمیل/واتساپ/اینستاگرام/تلفن به‌عنوانِ ارائه‌دهنده ساخته نشده |
| M9 قیفِ فروش و تحلیل | **شروع نشده** | فقط فیلدِ `Lead.status` و تاریخچه هست |
| M10 تستِ یکپارچه، بهینه‌سازی، مستنداتِ استقرار | **جزئی** | تستِ هر ماژول و این مستندات هست؛ تستِ بار و بهینه‌سازیِ کلی نه |

نکته: اگر بخشی در این جدول «انجام شد» نیست، در پنل هم کامل نیست؛ داشبورد فهرستِ «به‌زودی» را صادقانه نشان می‌دهد.

---

## ۷. کدِ موجودی که استفاده شد (یا می‌شود)

| کدِ موجود | وضعیت |
|---|---|
| احرازِ هویت: JWT، `is_staff`، `IsAdminUser` | **استفاده شد** (`IsGrowthStaff` از همان بنا شده) |
| رجیستریِ پنل (`apps/panel`) و `PageGate` | **استفاده شد** (بخشِ `growth`، خاموش/روشن از ادمین) |
| `apps.common.models.TimeStampedModel` و رندرِ JSON | **استفاده شد** |
| پیکربندیِ Celery، `shared_task`، صف‌ها، رفتارِ eager در تست (`IS_TEST`) | **استفاده شد** (کارها در صفِ پیش‌فرض `celery`) |
| الگوی «کارِ قابلِ ادامه» (`apps/jobs`، `apps/compute`: heartbeat، لغوِ نرم) | **الگو گرفته شد** در `BackgroundJob` |
| ادمینِ فارسی (`name_en` و `description` برای هر مدل) | **استفاده شد** |
| طراحیِ UI، `charts.tsx`، `Icon.tsx` (چند آیکون افزوده شد)، توکن‌های رنگ، Vazirmatn | **استفاده شد** |
| `services/research/shop_crawler.py` (robots.txt، sitemap، JSON-LD) | **عمداً استفاده نشد**: برای قیمتِ محصولِ رقیب نوشته شده؛ پارسرِ استخراجِ تماس جدا و کوچک است و SSRF/ارسال را ندارد. می‌شود بعداً در M4 کامل، بخشِ sitemap را از آن قرض گرفت |
| `services/ai/*` (دروازه، مسیریابی، ارائه‌دهنده‌ها) | **برای M5/M6**: به `store` بسته است؛ باید یا یک «فروشگاهِ داخلیِ آپ‌مارکت» تعریف شود یا دروازه برای کاربردِ داخلی باز شود (تصمیمِ مالک/معمار) |
| `services/publishing/channels.py` (آداپتر برای هر کانال) | **برای M8**: الگوی خوبی برای ارائه‌دهنده‌های ارسال (`can_send`, `requires`, `note`) |
| `apps/customers` (بازاریابیِ تلفنی، تیکت، گفتگو) و `apps/marketing` (لیدِ فرمِ سایت، CRM) | **قاطی نشد**؛ می‌توان بعداً لیدِ برنده را به مشتریِ CRM پیوند داد (M9) |

---

## ۸. ریسک‌ها (به ترتیبِ شدت)

1. **کلیدِ JWTِ سایتِ زنده همان کلیدِ توسعهٔ عمومی است (جدی‌ترین).**
   `settings.py` مقدارِ `DJANGO_SECRET_KEY` را می‌خواند، ولی `backend/.env` کلیدی به نامِ `SECRET_KEY` دارد؛ پس کلیدِ جنگو برابر با `dev-insecure-key-change-on-main-system` است (راستی‌آزمایی شد: `settings.SECRET_KEY == "dev-insecure-key-change-on-main-system"`).
   به همین دلیل `DEBUG` هم **روشن** است (`.env` می‌گوید `DEBUG=false` ولی کد `DJANGO_DEBUG` را می‌خواند) و `ALLOWED_HOSTS=['*']`.
   **نتیجه:** هر کس که کدِ پروژه را دیده باشد می‌تواند توکنِ کارمند جعل کند و وارد پنل—و این ابزار—شود. این ابزار داده‌های تماسِ آدم‌ها را نگه می‌دارد و می‌تواند (وقتی روشن شود) پیام بفرستد.
   **راهِ درست:** در `backend/.env` سه مقدار بگذارید: `DJANGO_SECRET_KEY` (رشتهٔ تصادفیِ بلند)، `DJANGO_DEBUG=false`، `DJANGO_ALLOWED_HOSTS=<دامنه/آی‌پی‌ها>`؛ سپس `nm-web` و `nm-celery` را ری‌استارت کنید. اثرِ جانبی: همهٔ کاربران یک بار از پنل بیرون می‌افتند.
   **این کار انجام نشد** (تغییرِ تنظیماتِ مشترکِ کلِ سایت و تصمیمِ مالک است). تا آن موقع «فقط کارکنان» در عمل به رازِ آن کلید بسته است.
2. **ارسالِ خودکارِ فرم از نظرِ حقوقی و اعتباری حساس است.**
   خودِ مشخصات (`SPEC.md` بخش ۱۳) صریحاً «ارسالِ انبوهِ ناخواستهٔ خودکار از فرمِ تماس» را ممنوع کرده بود؛ مالک بعداً تصمیمِ دیگری گرفت. نگهبان‌ها (تأییدِ انسانی به ازای هر آیتم و هر پیام، هویتِ راستینِ فرستنده، جملهٔ لغو، فهرستِ «تماس نگیر»، سقفِ روزانه، فاصله، توقفِ اضطراری، ردِ هر فرمِ دارای کپچا/ورود) کاهندهٔ ریسک‌اند، نه حذف‌کنندهٔ آن. قوانینِ تجارتِ الکترونیکِ ایران دربارهٔ پیامِ تبلیغاتیِ ناخواسته و پیامدِ شکایتِ گیرنده باید بررسی شود. **پیش‌فرض: ارسال خاموش است.**
3. **آی‌پیِ سرور ممکن است در فهرستِ اسپم بیفتد.** همهٔ ارسال‌ها از `87.107.160.17` می‌روند؛ همین سرور میزبانِ سایت‌های دیگر (چغر، تموز) هم هست. افتادن در بلک‌لیست به آن‌ها هم آسیب می‌زند. به همین دلیل: سقفِ روزانهٔ ۴۰، فاصلهٔ ۶۰ تا ۱۲۰ ثانیه، حداکثر یک پیام به هر دامنه در هر کمپین، هیچ تکرارِ خودکار، جملهٔ لغو. اولین دسته را کوچک بفرستید.
4. **داده‌هایِ شخصی (PII).** شماره/ایمیلِ آدم‌ها (صاحبانِ کسب‌وکار) نگه‌داری می‌شود. دسترسی فقط کارکنان؛ همهٔ تغییرها در تاریخچهٔ لید و ممیزی ثبت می‌شود؛ خروجیِ CSV لاگ می‌شود؛ حذفِ یک لید همهٔ دادهٔ او را می‌برد (`OPERATIONS.md`).
5. **تشخیصِ کپچا و ضدرباتْ حدسی (heuristic) است.** اگر کپچایی نادیده بماند، ارسال فقط **ناموفق** می‌شود؛ هرگز دور زده نمی‌شود، و آیتمِ ناموفق دوباره امتحان نمی‌شود. فرمی که به‌درستی کپچا دارد ولی تشخیص داده نشود، یک تلاشِ بی‌نتیجه می‌سوزاند و از سقف کم می‌کند.
6. **SSRF، DNS rebinding و رفتار با سایتِ دیگران.** آدرسِ لید ورودیِ غیرقابلِ‌اعتماد است. `safe_http` همهٔ آدرس‌های داخلی را می‌بندد، به همان آی‌پیِ بررسی‌شده وصل می‌شود (نه دوباره به نام)، فقط پورت‌های ۸۰/۴۴۳/۸۰۸۰/۸۴۴۳، فقط ریدایرکتِ همان سایت، robots.txt را (۵xx یا ناخوانا = ممنوع) رعایت می‌کند، فاصلهٔ ۲ ثانیه برای هر سایت، و **تأییدِ گواهیِ TLS را هرگز خاموش نمی‌کند** و به http پایین نمی‌آید. خطرِ باقی‌مانده: خطای ناشناخته در خودِ کتابخانه‌ها (httpx/httpcore)؛ بقیهٔ مسیرها با تست پوشش داده شده‌اند.
7. **SQLite با یک نویسنده.** کارهای طولانی (CSV، استخراج، ارسال) با تراکنشِ کوتاهِ هر ردیف/لید و WAL می‌نویسند تا درخواست‌های دیگر منتظر نمانند. **در آزمونِ زنده یک بار «database is locked» دیده شد** (تعارضِ snapshot که `busy_timeout` جلویش را نمی‌گیرد: ردیفِ اولِ یک ورودِ CSV با نوشتنِ هم‌زمانِ پردازهٔ وب برخورد کرد). درمان در همین کار انجام شد: `core/dispatch.py` (شناسهٔ Celery پیش از ارسال نوشته می‌شود) و `core/dbretry.py` (هر گامِ کوتاهِ کارها تا چند بار دوباره اجرا می‌شود). درمانِ ریشه‌ایِ کلِ پروژه، `OPTIONS: {"transaction_mode": "IMMEDIATE"}` برای دیتابیسِ `default` در `settings.py`، **عمداً اعمال نشد** چون رفتارِ همهٔ بخش‌های دیگرِ سایت را عوض می‌کند و تصمیمِ مالک است؛ API‌های وب هنوز در برابرِ این خطای نادر محافظت نشده‌اند (کاربر دوباره تلاش می‌کند).
8. **Celery با thread و ری‌استارت.** کارِ ارسال یک thread از چهارتای worker را مدتِ طولانی نگه می‌دارد (فاصلهٔ بینِ ارسال‌ها). ری‌استارتِ `nm-celery` کار را قطع می‌کند؛ همهٔ کارها با `cursor` قابلِ ادامه‌اند. **نگاشتِ beat اضافه نشد** (طبقِ دستور، beat ری‌استارت نمی‌شد)، پس بازیابیِ خودکارِ کارِ گیرکرده نیست و دکمهٔ «ادامه» باید زده شود. پس از رسیدن به سقفِ روزانه هم کار تمام می‌شود و فردا باید دستی «ادامهٔ ارسال» زد.
9. **حدسِ استخراج دقیق نیست.** شماره/ایمیل ممکن است اشتباه بیاید یا نیاید؛ برای همین هر یافته صفحهٔ منبع، مدرک و «اطمینان» دارد و چیزِ دیگری جز آنچه صفحه نشان می‌دهد ساخته نمی‌شود. جاافتاده‌ها (سایتِ فقط‌جاوااسکریپتی، چالشِ Cloudflare) صریحاً «ناموفق با دلیل» ثبت می‌شوند.
10. **هم‌نامیِ دو «لید».** `marketing.Lead` (فرمِ تماسِ سایتِ عمومی، در «ادمین ← CRM») با لیدِ جذب مشتری یکی نیست. در پنل زیرِ «جذب مشتری» و در ادمین با نامِ «لیدِ جذب مشتری» دیده می‌شود تا قاطی نشود.
11. **دروازهٔ AI به فروشگاه بسته است.** برای M5/M6 باید تصمیم گرفت (فروشگاهِ داخلی یا بازکردنِ دروازه). در این دور هیچ AI ای صدا زده نمی‌شود و هیچ اعتباری مصرف نشد.
12. **جای دیسک کم است** (حدود ۲٫۵ گیگابایت آزاد). بکاپ‌ها کوچک نگه داشته شده‌اند؛ فایل‌های CSV آپلودی پس از پایانِ کار پاک می‌شوند و بقیه پس از ۲۴ ساعت.

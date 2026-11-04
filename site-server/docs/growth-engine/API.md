# مرجعِ API «جذب مشتری»

پایه: `/api/v1/growth/` · احراز: `Authorization: Bearer <access>` (JWT از `POST /api/v1/auth/login/`) · **فقط کاربرِ `is_staff` و فعال** (ناشناس ← `401`، کاربرِ عادی ← `403`).
بدنه‌ها JSON‌اند (جز آپلودِ CSV که `multipart/form-data` است). تاریخ‌ها ISO-8601. شمارهٔ صفحه از ۱.

```bash
TOKEN=$(curl -s -X POST http://87.107.160.17:8040/api/v1/auth/login/ -H 'Content-Type: application/json' \
  -d '{"username":"…","password":"…"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access"])')
curl -s -H "Authorization: Bearer $TOKEN" http://87.107.160.17:8040/api/v1/growth/dashboard/
```

## قراردادِ خطاها

| کد | شکل | چه وقت |
|---|---|---|
| `400` | `{"code":"validation","detail":"<نخستین پیام>","errors":[{"field","code","message"}]}` | ورودیِ نامعتبر؛ `message`ها فارسی‌اند. (خطای نوعِ ساده‌ای مثلِ فیلدِ اجباریِ نفرستاده را DRF با شکلِ استانداردش می‌دهد: `{"فیلد":["…"]}`) |
| `409` | `{"code":"duplicate","detail":"…","duplicates":[{"lead":<ردیفِ لید>,"matched_on":[{"kind","value","normalized"}],"merge_preview":<…>}]}` | شناسه‌ای که مالکِ دیگری دارد. **هیچ‌چیز نوشته نشده** |
| `401` / `403` | `{"detail":"…"}` | ناشناس / غیرِ کارمند |
| `404` | `{"detail":"…"}` | یافت نشد |
| `429` | `{"detail":"Request was throttled…"}` | سهمیه: آپلود/ورود ۳۰ در ساعت، خروجی ۳۰ در ساعت، گروهی ۶۰ در دقیقه (+ سهمیهٔ عمومیِ ۲۴۰ در دقیقه) |

`merge_preview` (پیش‌نمایشِ ادغام): `{"fields":[{"field","label","existing","incoming","state":"fill|same|conflict"}],"contacts_new":[{kind,value}],"contacts_known":[…],"contacts_elsewhere":[{kind,value,lead_id}],"tags_new":["…"]}`.

---

## ۱. واژگان و داشبورد

### `GET meta/`
واژگانِ یک‌جا: `statuses`، `origins`، `contact_kinds`، `business_types`، `activity_kinds` (هرکدام `[{value,label}]`)، `countries` (`[{code,name}]`)، `csv` (`{max_bytes,max_rows,targets:[{key,label,multi}],default_country}`)، `limits` (`{bulk_max_ids,export_max_rows}`).

### `GET dashboard/`
```json
{ "generated_at": "…",
  "totals": {"leads":0,"new_7d":0,"with_website":0,"with_instagram":0,"archived":0,"with_phone":0,"with_email":0,"with_contact_form":0},
  "by_status": [{"status":"new","label":"جدید","count":0}],
  "by_origin": [{"origin":"manual","label":"ثبت دستی","count":0}],
  "top_cities": [{"city":"تهران","count":0}],
  "daily": [{"date":"2026-11-01","value":0}],
  "pending_duplicates": 0,
  "recent_jobs": [{"id","file_name","status","status_label","progress","created_count","duplicate_count","error_count","total_items","queued_at","created_by_name"}],
  "recent_activity": [{"id","lead_id","lead_name","kind","kind_label","summary","actor_name","created_at"}],
  "extra": {"extraction":{…},"compliance":{…},"outreach":{…}},
  "coming_soon": [{"key","title","milestone"}] }
```
همه شمارشِ مستقیم‌اند (بدونِ بایگانی‌شده‌ها جز `archived`). `extra.<ماژول>` فقط وقتی ماژول نصب است.

---

## ۲. لیدها (`leads`)

### `GET leads/`
پارامترها: `page`, `page_size` (≤۱۰۰)، `q` (جست‌وجو؛ هر کلمه جداگانه و همه باید جایی بخورند: نام بدونِ ZWNJ/فاصله، سایت، اینستاگرام، شهر، دسته، توضیحات، راه‌های تماس، شماره با هر فرمت)، `status` (چندتا با ویرگول)، `origin`، `country` (کد)، `city`، `category`، `tag` (نام یا شناسه؛ چندتا ← همه)، `has` (`website,instagram,phone,email`)، `source_job` (شناسهٔ ورودِ CSV)، `created_from`/`created_to` (`YYYY-MM-DD`)، `archived` (`0` پیش‌فرض، `1` فقط بایگانی، `all`)، `ordering` (`created_at, updated_at, business_name, status, city, category` با/بدونِ `-`؛ نامعتبر ← پیش‌فرض `-created_at`).
پاسخِ صفحه‌بندی‌شده `{count,next,previous,results:[…]}`؛ هر ردیف:
`id, display_name, business_name, website, instagram_url, category, city, country, country_name, status, status_label, origin, origin_label, is_archived, tags:[{id,name,color}], phone, email, created_at, updated_at, do_not_contact`.
(تعدادِ کوئری ثابت است: شمارش + صفحه + برچسب‌ها + تماس‌ها [+ «تماس نگیر»].)

### `GET leads/<id>/` ← ردیفِ بالا +
`description`, `provenance` (`{فیلد:{source,at,by}}`), `profile` (`{language,business_type,business_type_label,product_categories,product_names,address,provenance}`), `contacts:[{id,kind,kind_label,value,label,is_primary,source_ref,source:{kind,file,row,run},source_url,evidence,confidence,created_at}]`, `sources:[{id,provider,provider_label,source_ref,source,source_url,discovered_at,job_id,created_by}]`, `created_by_name`, `notes_count`.

### `PATCH leads/<id>/`
بدنه (همه اختیاری): `business_name, website, instagram_url, category, description, country, city, status, is_archived, tags:[نام…]` (جایگزینِ کل)، `profile:{language,business_type,address,product_categories,product_names}`. پاسخ: لیدِ تازه + `"changed":["city","status",…]`. `400` با خطای هر فیلد؛ `409` اگر `website`/`instagram_url` مالکِ دیگری دارد. هر فیلدِ تغییرکرده «منبع = manual» می‌گیرد و در تاریخچه (قدیم ← جدید) ثبت می‌شود.

### `DELETE leads/<id>/?confirm=1`
`204`؛ بدونِ `confirm=1` ← `400`. همراهِ لید راه‌های تماس، یادداشت‌ها و تاریخچه‌اش هم پاک می‌شوند.

### `GET leads/<id>/activity/?kind=&page=`
`[{id,kind,kind_label,actor,actor_name,summary,data,source_ref,source,created_at}]` (جدیدترین اول؛ صفحه‌بندی). فقط‌خواندنی (تاریخچه ویرایش‌پذیر نیست).

### یادداشت‌ها
`GET leads/<id>/notes/` · `POST leads/<id>/notes/ {"body"}` (`201`) · `PATCH leads/<id>/notes/<nid>/ {"body"}` · `DELETE leads/<id>/notes/<nid>/` (`204`). شکل: `{id,body,author,author_name,created_at,updated_at}`.

### راه‌های تماس
`POST leads/<id>/contacts/ {"kind","value","label?"}` (`201`؛ `400` نامعتبر/تکراریِ همین لید؛ `409` مالکِ دیگر) · `PATCH leads/<id>/contacts/<cid>/ {"value?","label?","is_primary?"}` · `DELETE …` (`204`). `kind` یکی از `phone,email,website,instagram,whatsapp,telegram,eitaa,bale,rubika,linkedin,contact_form,other`.

### `POST leads/bulk/` (سهمیهٔ `growth_bulk`)
```json
{"ids":[1,2,3],"action":"set_status","status":"qualified"}
```
`action`: `set_status` (با `status`)، `add_tag` / `remove_tag` (با `tag`)، `archive`، `unarchive`، `delete` (با `"confirm":true`). حداکثر ۵۰۰ شناسه. پاسخ: `{"affected":n,"skipped":n,"missing":n}`.

### `GET leads/export/` (سهمیهٔ `growth_export`)
همان فیلترهای فهرست، یا `?ids=1,2,3`. پاسخ: `text/csv` (UTF-8 با BOM، پخشِ جریانی، `Content-Disposition: attachment; filename="growth-leads-<تاریخ>.csv"`). فرمت و محافظِ فرمول: `MODULES.md`.

### `GET tags/`
`[{id,name,color,lead_count}]`.

---

## ۳. کشف (`discovery`)

### ثبتِ دستی
`POST discovery/manual/check/` و `POST discovery/manual/` — بدنهٔ مشترک:
```json
{"mode":"manual","business_name":"…","website":"…","instagram":"@x","phone":"…","email":"…","whatsapp":"","telegram":"",
 "category":"","description":"","country":"ایران","city":"","note":"","tags":["…"],"language":"","business_type":"","address":"",
 "resolution":{"action":"merge","target_lead":12,"overwrite_fields":["city"]}}
```
`mode`: `website_url` (سایت لازم) · `instagram_url` (اینستاگرام لازم؛ **هرگز دریافت نمی‌شود**) · `business_name` (نام لازم) · `manual` (دست‌کم یکی از نام/سایت/اینستاگرام/تلفن/ایمیل). `resolution` فقط در `POST` و فقط برای تکراری.
- **check** ← `200 {"valid":true,"errors":[],"duplicates":[{lead,matched_on,merge_preview}],"similar":[ردیفِ لیدِ هم‌نام…]}`؛ نامعتبر ← `{"valid":false,"errors":[…]}`. چیزی نوشته نمی‌شود.
- **submit** ← `201 {"result":"created","lead":{…}}` · تکراریِ بدونِ تصمیم ← `409` · `resolution.merge` ← `200 {"result":"merged","lead","filled":[…],"overwritten":[…],"conflicts":[{field,label,existing,incoming}],"contacts_added":[…],"contacts_skipped":[{kind,value,reason,lead_id?}]}` · `resolution.skip` ← `200 {"result":"skipped"}` · نامعتبر ← `400`.
ادغام هرگز خودکار رونویسی نمی‌کند: فقط فیلدِ خالی پر می‌شود و `overwrite_fields` (نامِ فیلدهای مجاز: `business_name, category, description, country, city, website, instagram_url, language, business_type, address`) فقط وقتی کاربر بخواهد.

### CSV
1. `POST discovery/csv/upload/` — `multipart` با فیلدِ `file` (سهمیهٔ `growth_upload`) ← `201`:
   `{upload_id,file_name,size,encoding,delimiter,total_rows,headers,sample_rows:[{row,cells}],suggested_mapping:{ستون:مقصد|""},targets:[{key,label,multi}]}`.
   خطاها `400`: پسوندِ نامجاز، خالی/باینری، بدونِ ردیفِ داده، بیش از حجم/ردیف.
2. `POST discovery/csv/check/ {"upload_id","mapping":{ستون:مقصد},"default_country?","default_city?"}` ← `{total_rows,valid_rows,error_rows,errors:[{row,errors:[…]}] (۲۰ تای اول),sample:[{row,ok,errors,summary:{business_name,website,instagram,phones,emails,city,country,category,tags}}],mapping}`. به دیتابیس چیزی نمی‌نویسد.
3. `POST discovery/csv/import/ {"upload_id","mapping","default_country?","default_city?","tags?":[…],"extract_after?":false}` ← `202` + کار. `upload_id` فقط برای همان کاربر معتبر است.

### کارها
- `GET discovery/jobs/` (صفحه‌بندی) · `GET discovery/jobs/<id>/` ← `{id,kind,kind_label,status,status_label,file_name,encoding,total_items,processed_items,progress,created_count,merged_count,skipped_count,duplicate_count,error_count,error,stalled,can_resume,cancel_requested,attempts,queued_at,started_at,finished_at,created_by_name,params}`. `status`: `queued|running|completed|failed|cancelled`.
- `GET discovery/jobs/<id>/rows/?status=error,duplicate,merged,skipped,created&with_merge_preview=1&page=` — گزارشِ ردیفی (۵۰ در صفحه): `{id,row_number,status,status_label,raw,errors,matches:[{lead_id,name,matched_on}],matched_lead_id,resolved_at,merge_preview?}`. `row_number` = شمارهٔ ردیفِ اکسل.
- `GET discovery/jobs/<id>/errors.csv` — ردیف‌های خطا با ستون‌های «ردیف در فایل» و «خطا».
- `POST discovery/jobs/<id>/cancel/` ← کار (صف‌شده فوراً `cancelled`؛ در حالِ اجرا در چند ردیفِ بعد؛ ردیف‌های ثبت‌شده می‌مانند).
- `POST discovery/jobs/<id>/resume/` ← `202` (فقط کارِ `failed` یا گیرکرده که فایلش هنوز هست؛ وگرنه `400`). از ردیفِ بعدِ `cursor` ادامه می‌دهد.
- `POST discovery/jobs/<id>/resolve/ {"action":"merge|skip","rows":[ids]|"all":true,"target_lead?":id,"overwrite_fields?":[…]}` ← `{"resolved":n,"merged":n,"skipped":n,"created":n,"remaining":n}`. در هر فراخوانی حداکثر ۵۰۰ ردیف؛ تا `remaining=0` تکرار کنید.

---

## ۴. استخراج (`extraction`)

| endpoint | کار |
|---|---|
| `POST extraction/jobs/ {"lead_ids":[…]}` یا `{"discovery_job_id":N}` (دقیقاً یکی) + `"force?":true` | `202` + کار. لید بدونِ وب‌سایت و لیدِ استخراج‌شده در ۳۰ روزِ گذشته ردِ آشکار می‌شود (مگر `force`). اگر هیچ‌چیز قابلِ خواندن نباشد `400` با شرح. بیش از ۵۰۰ لیدِ یک ورودیِ CSV به چند کار شکسته می‌شود: `"extra_job_ids":[…]`؛ انتخابِ دستیِ بیشتر از ۵۰۰ ← `400` |
| `GET extraction/jobs/` | فهرست |
| `GET extraction/jobs/<id>/` | کار + `runs:[{id,lead_id,lead_name,status,status_label,reason,reason_label,pages_fetched,contacts_added}]` (۳۰۰ تا) |
| `POST extraction/jobs/<id>/cancel/` · `…/resume/` | مثلِ کارهای کشف |
| `GET leads/<id>/extraction/` | `{"runs":[…]}` ۵ اجرای آخر |

کار: `{id,status,status_label,scope,scope_label,discovery_job_id,progress,total_items,processed_items,runs_done,runs_failed,runs_skipped,pages_fetched,contacts_added,error,stalled,can_resume,cancel_requested,attempts,queued_at,started_at,finished_at,created_by_name}`.
اجرا: `{id,job_id,status,status_label,reason,reason_label,started_at,finished_at,pages_fetched,robots_state,contacts_added,findings:[{field,value,source_url,evidence,confidence,applied,reason}],pages:[{url,kind,status,outcome,outcome_label,elapsed_ms,bytes,note}]}`.
`reason` یافته: `added | already_known | fill_empty | kept_existing | owned_by_other_lead | invalid`.

---

## ۵. تنظیمات، «تماس نگیر» و ممیزی (`compliance`)

- `GET settings/` ← `{sending_enabled,emergency_stop,sender_name,sender_company,sender_phone,sender_email,sender_website,opt_out_line,daily_cap,spacing_min_seconds,spacing_max_seconds,updated_at,ready:{ok,problems:[…]},sent_today,cap_remaining}`.
- `PATCH settings/` (جزئی) ← همان شکل. `400` با خطای هر فیلد: سقف ۱ تا ۵۰۰؛ فاصله ۱۰ تا ۳۶۰۰ و حداکثر ≥ حداقل؛ تلفن/ایمیل/سایت معتبر؛ جملهٔ لغو خالی نباشد؛ **روشن‌کردنِ `sending_enabled` تا هویت (نام، شرکت، تلفن، ایمیل، جملهٔ لغو) کامل نیست `400`** (در `errors[0].code`: `identity_incomplete`).
- `POST settings/emergency-stop/ {"stop":true|false}` ← تنظیماتِ تازه. فعال‌بودنِ توقف `ready.ok` را `false` می‌کند و هر کارِ ارسالِ در حالِ اجرا را می‌ایستاند.
- `GET settings/audit/` ← ۱۰۰ ردِ ممیزیِ آخر `[{id,kind,kind_label,summary,data,actor_name,created_at}]`.
- `GET compliance/suppression/?q=&page=` ← صفحه‌بندی `[{id,kind,kind_label,value,reason,reason_label,note,created_by_name,created_at}]`.
- `POST compliance/suppression/ {"value":"<تلفن|ایمیل|آدرسِ سایت|@اینستاگرام>","reason?","note?"}` یا `{"lead_id":N,…}` (همهٔ شناسه‌های لید) ← `201 {"added":n,"entries":[…]}`؛ موردِ تکراری/نامعتبر ← `400`. `reason`: `opt_out, asked_not_to_contact, complaint, invalid_contact, other`.
- `DELETE compliance/suppression/<id>/` ← `204`.
- `POST leads/<id>/do-not-contact/ {"reason?","note?"}` ← `201 {"do_not_contact":true,"added":n}` (لیدِ بی‌شناسه ← `400`) · `DELETE leads/<id>/do-not-contact/` ← `{"do_not_contact":bool,"removed":n}`. هر دو در تاریخچهٔ لید و ممیزی ثبت می‌شوند.

---

## ۶. پیام‌رسانی (`outreach`)

> این بخش با اجرای زنده روی سرور (Celery و Redis واقعی، فقط به فروشگاه‌های آزمایشیِ خودمان) تطبیق داده شد: ساختِ قالب و کمپین، add-leads (با دلیل‌ها)، prepare، approve (با `refused`)، ویرایش و باطل‌شدنِ تأیید، start، ارسال، سقفِ روزانه، توقفِ اضطراری، outcomeهای دستی و تاریخچه.

**قالب‌ها:** `GET|POST outreach/templates/` · `GET|PATCH|DELETE outreach/templates/<id>/` (حذفِ قالبِ استفاده‌شده رد می‌شود؛ بایگانی با `is_active:false`) · `POST outreach/templates/preview/ {"body","subject?","lead_id?"}` ← `{text,subject,warnings,unknown_placeholders}` · `GET outreach/placeholders/` ← `[{key,label,example_source}]`.

**کمپین‌ها:**
- `GET|POST outreach/campaigns/` (`{name,template_id,mode:"auto|manual",lead_ids?,force?}` ← `201`) · `GET|PATCH outreach/campaigns/<id>/` (فقط نام).
- `POST …/<id>/add-leads/ {"lead_ids","force?"}` ← `{"added":n,"skipped":[{lead_id,lead_name,reason,reason_text}]}`؛ دلیل‌ها: `already_in_campaign, already_contacted, suppressed, archived, duplicate_domain, no_target_url, limit`.
- `POST …/<id>/remove-items/ {"item_ids"}` (نه `sent`/`sending`).
- `POST …/<id>/prepare/` ← کارِ `kind=prepare`: صفحهٔ فرمِ هر آیتم از `safe_http` گرفته و تحلیل می‌شود (`ready` یا `needs_manual` با دلیل).
- `POST …/<id>/approve/ {"item_ids":[…]|"all_ready":true}` ← `{"approved":n,"refused":[{item_id,code,text}]}`؛ `POST …/<id>/revoke/ {"item_ids"}`.
- `POST …/<id>/start/` (draft/paused ← active و شروعِ کارِ ارسال اگر آیتمِ تأییدشده هست؛ اگر ارسال آماده نیست `400` با متنِ نگهبان) · `…/pause/` · `…/cancel/`.
- `GET …/<id>/status/` ← `{campaign,counts:{وضعیت:n},job,sent_today,daily_cap,cap_remaining,readiness:{…},emergency_stop}`.

**آیتم‌ها:** `GET …/<id>/items/?status=&q=&page=` (لید، خلاصهٔ طرح، `approval:{valid,by,at}`، `attempt`) · `GET|PATCH …/<id>/items/<item>/` (`PATCH {"rendered_text?","subject?"}` ← اثرانگشت دوباره محاسبه و **تأیید باطل می‌شود**) · `POST …/items/<item>/rerender/` · `POST …/items/<item>/outcome/ {"outcome":"sent|no_form|needs_login|skipped","note?"}` (صفِ دستی؛ متنِ دقیق در تاریخچهٔ لید).
جزئیاتِ آیتم شاملِ **dry-run**: `plan={page_url,action_url,method,enctype,verdict,reasons:[{code,text}],fields:[{name,type,label,source,value,hidden}],detected}`؛ مقدارِ فیلدهای `hidden` در UI «مقدارِ مخفیِ صفحه» نشان داده می‌شود و در نسخهٔ ذخیره‌شدهٔ payload به `"***"` تبدیل می‌شود.
**کارها:** `GET outreach/jobs/<id>/` · `POST outreach/jobs/<id>/cancel/` · `POST outreach/jobs/<id>/resume/`.

وضعیتِ آیتم: `pending, ready, needs_manual, approved, sending, sent, failed, skipped, cancelled, manual_sent, no_form, needs_login`.
**فقط آیتمِ `approved` با تأییدِ معتبر ارسال می‌شود؛ ارسال‌نشده‌ها هرگز خودکار دوباره امتحان نمی‌شوند.**

## ۷. دورِ دوم (M3 تا M5)

> همهٔ endpointها `IsGrowthStaff`. هیچ کلید یا رمزی در هیچ پاسخی نیست: فقط `{"is_set": true}`.

### کشفِ خودکار
- `GET discovery/providers/` ← `{"providers":[{key,label,description,kind:"map|search",needs_key,enabled,ready,not_ready_reason,attribution,attribution_url,license_note,max_results_limit,categories:[{key,label,tags}],settings_schema,settings,secrets:{نام:{label,is_set}},source_provider,usage_today?,daily_cap?}]}`.
- `GET|PATCH discovery/providers/<osm|brave|google_cse>/` — `PATCH {"enabled?","settings?":{overpass_endpoints,nominatim_url,daily_cap},"secrets?":{api_key,cx},"clear_secrets?":[…]}`. کلید ۸ تا ۳۰۰ نویسهٔ ASCII؛ روشن‌کردنِ منبعِ کلیددارِ بدونِ کلید `400`؛ ناشناخته `404`.
- `POST discovery/search/check/` (سهمیهٔ `growth_upload`) `{"provider","category","city","country?","max_results?","require_contact?","extract_after?","tags?"}` ← `{"ok","summary","attribution","place":{name,cached,osm_url}|null,"notes":[…]}` (شهر را حل می‌کند، چیزی نمی‌نویسد).
- `POST discovery/search/` (همان بدنه) ← `202` + کارِ `kind=search` (`attribution` و پارامترها در `params`). خطا: `400` با `errors[{field,code,message}]`. کار با همان `GET discovery/jobs/<id>/`، `rows/`، `cancel/`، `resume/`، `resolve/` دنبال می‌شود (`resume` برای `search` به فایلِ ذخیره‌شده نیاز ندارد).

### کانال‌ها
- `GET outreach/channels/` ← `{"channels":[{key,label,kind:"auto|manual",description,hint,enabled,priority,daily_cap,spacing_min_seconds,spacing_max_seconds,default_template,ready,not_ready_reason,config_schema,config:{set,in_force?,from_server?,password_from_server?},secrets:{smtp_password:{label,is_set,server_default}},sent_today,cap_remaining,needs_app}]}` به ترتیبِ اولویت.
- `GET|PATCH outreach/channels/<key>/` — `PATCH {"enabled?","priority?","daily_cap?"(null=فقط سراسری),"spacing_min_seconds?","spacing_max_seconds?"(هر دو یا هیچ),"default_template_id?","config?":{host,port,security,username,from_email,from_name,reply_to,timeout | max_parts},"secrets?":{smtp_password},"clear_secrets?":["smtp_password"]}`. ایمیل/پیامکِ ناآماده روشن نمی‌شود (`400 not_ready`).
- `POST outreach/channels/reorder/ {"order":[کلیدها]}` ← کانال‌ها · `POST outreach/channels/email/verify/` ← `{"ok","message"}` (وارد می‌شود، **ایمیلی نمی‌فرستد**).
- قالب: فیلدِ `channel` (`any|<کانال>`)؛ `POST outreach/templates/preview/` فیلدِ `channel?` و برای پیامک `sms:{parts,length,encoding,max_parts,fits}`. کمپین: `channel` (`auto|<کانال>`؛ کانالِ دستی فقط با `mode=manual`). آیتم: `channel, channel_label, recipient, template, manual:{link,link_kind,label,steps,copy_text,recipient,note}|null, sms|null`؛ `GET …/items/?channel=`. `POST …/items/<item>/outcome/` نتیجهٔ تازهٔ `unreachable`. `GET …/status/` فیلدِ `channels:{کانال:{label,enabled,sent_today,cap_remaining,ready,not_ready_reason}}` و وضعیتِ پیامک‌ها را از گوشی به‌روز می‌کند.
- وضعیت‌های تازهٔ آیتم: `handed_off` (به صفِ گوشی داده شد؛ برای قاعده‌های تکرار «تماس‌گرفته»)، `unreachable`. دلیل‌های کنارِ زدنِ لید در `add-leads`: `no_email, no_mobile, no_whatsapp, no_telegram, no_eitaa, no_bale, no_rubika, no_phone, no_channel` (و دلیل‌های قبلی). کدهای نگهبانِ تازه: `no_recipient, channel_not_ready, channel_disabled, manual_channel, channel_opted_out`.

### دانشِ محصول
- `GET knowledge/` ← `{"sections":[{key,label}],"items":[{id,section,section_label,title,body,url,sort_order,is_active,note,is_default,seed_key,needs_value,needs_value_hint,updated_at}],"summary":{total,active,prices_missing,defaults_missing}}` · `POST knowledge/` · `PATCH|DELETE knowledge/<id>/` · `POST knowledge/<id>/reset/` (فقط موردِ پیش‌فرض) · `POST knowledge/restore-defaults/` ← `{"knowledge":n,"templates":m}` · `GET knowledge/writer-status/` (بهترین‌تلاش؛ هیچ درخواستی به AI نمی‌فرستد).

### نویسندهٔ هوشمند (روی یک آیتم)
- `POST outreach/campaigns/<id>/items/<item>/ai/ {"instructions?"}` ← `202` + نسخه `{id,version,status:"generating|proposed|approved|superseded|rejected|failed",subject,body,text,personalization_reason,evidence:[{ref,label,text}],warnings:[{code,text,blocking}],blocking_warnings,route:{via,model,attempts},error,sms,same_as_current,…,created:bool}` (اگر نسخه‌ای در حالِ نوشتن باشد همان برمی‌گردد). `POST outreach/campaigns/<id>/ai-write/ {"item_ids"(≤۳۰),"instructions?"}` ← `{"started":[…],"refused":[{item_id,text}]}`.
- `GET …/items/<item>/versions/` ← `{"versions":[…],"current_text","current_subject"}` · `GET …/versions/compare/?a=<نسخه|current>&b=<نسخه|current>` ← `{a:{label,text},b:{…},ops:[{op:"equal|delete|insert",a,b}]}` · `POST …/versions/<v>/approve/ {"acknowledge_warnings?"}` (هشدارِ جدیِ بدونِ تأیید `400`؛ متنِ آیتم عوض و تأییدِ ارسال باطل می‌شود) · `POST …/versions/<v>/reject/`.

### لیدها
`reach` در ردیفِ لید و جزئیات: `{"value":0-100,"level":"high|medium|low","label":"بالا|متوسط|کم","reasons":[{text,points}]}`.

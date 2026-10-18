# UpMarket Backend

Django + DRF + Celery. یک پروژه‌ی واحد؛ همه‌ی APIها زیر `‎/api/v1/`.

> مرجع کامل توسعه و فازها: [`../ROADMAP.md`](../ROADMAP.md) ·
> معماری: [`../docs/`](../docs/)

## چه چیزی کجاست

| مسیر | چیست |
|---|---|
| `apps/accounts` | JWT، ثبت‌نام/ورود/رفرش/me، بازیابی رمز |
| `apps/stores` | Store، پروفایل برند، عضویت و نقش‌ها — **مرز مستأجر** |
| `apps/products` | دسته، محصول، تنوع، ویژگی، تصویر |
| `apps/ai` | ModelProvider، سیاست داده‌ی فروشگاه، هوش محصول، تحلیل بازار، بردارها |
| `apps/content` | کپشن، تصویر تولیدی، سناریو، صحنه، قطعه، برش، ویدیوی آپلودی |
| `apps/customers` | مشتری، گفتگو، ایجنت فروش، سفارش، رسید، تیکت، اعلان |
| `apps/campaigns` | کمپین، تخته‌ی کار، زمان‌بندی انتشار، یادگیری از نتیجه |
| `apps/billing` | پلن، اشتراک، پرداخت، مصرف، فاکتور |
| `apps/marketing` | لید، رویداد، انتساب، معرفی، پاداش، CRM |
| `apps/analytics` | تجمیع واقعی — بدون داده‌ی ساختگی |
| `apps/api_platform` | API عمومی + کلید + لاگ فراخوانی |
| `apps/cms` | محتوای سایت عمومی: مقاله، تنظیمات سایت، سؤالات متداول، نمونه‌کار، صفحه‌های سئو، مطالعات موردی، مشتریان، نظرات، منابع، ریدایرکت |
| `apps/jobs` | رکورد کار، ماشین حالت، پیشرفت، SSE |
| `apps/common` | مدل و ابزار مشترک |
| `services/` | لایه‌ی سرویس — ai، comfyui، video، audio، imaging، editing، research، publishing |

> **هیچ منطق کسب‌وکاری در ویوها نیست.** ویو اعتبارسنجی و اجازه می‌دهد؛ کار را
> `services/` می‌کند. هر فراخوانی AI از `services/ai/gateway.py` رد می‌شود که
> سیاست داده‌ی همان فروشگاه را قبلش چک می‌کند.

## Setup (both systems)

> **Easiest path:** run `..\start.bat` — it creates `.env`, installs packages,
> migrates, creates the admin user (admin/admin1234), launches everything and
> health-checks each service. The manual steps below are the equivalent.

```powershell
cd backend
pip install -r requirements.txt
copy .env.example .env      # then edit values
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

- Swagger UI: http://localhost:8000/api/docs/
- Admin: http://localhost:8000/admin/

### محتوای سایت عمومی — یک بار

سایت عمومی محتوایش را از همین بک‌اند می‌خواند و همه‌اش از جنگو ادمین قابل
ویرایش است. این دو دستور آن را راه می‌اندازند:

```powershell
python manage.py seed_site_content   # تنظیمات سایت، سؤالات متداول، نمونه‌کارها
python manage.py stitch_showcase     # قطعه‌های ۵ ثانیه‌ای → یک ویدیو (ffmpeg لازم است)
```

`seed_site_content` idempotent است و چیزی را که در ادمین عوض کرده‌ای دست نمی‌زند.
بعد از آن، `/admin/cms/` جای ویرایش همه‌چیز است: مقاله، تنظیمات سایت، سؤالات
متداول، نمونه‌کار، و صفحه‌های سئو (راه‌حل، مورد استفاده، قابلیت، مقایسه).

> اگر بک‌اند موقع بیلد سایت در دسترس نباشد، سایت از نسخه‌ی داخل ریپو رندر
> می‌شود — کهنه‌تر، ولی کامل. این عمدی است: بلاگ و صفحات سئو سطح سئوی ما
> هستند و صفحه‌ی خالی بدتر از صفحه‌ی کمی قدیمی است.

### دریافت پیام از تلگرام و اینستاگرام

صندوق پیام تا امروز فقط می‌فرستاد. حالا وب‌هوک ورودی هم دارد — آدرسش برای هر
فروشگاه جداست و در پنل، صفحه‌ی «اتصال شبکه‌ها» نوشته شده:

```
POST /api/v1/webhooks/<telegram|instagram|whatsapp>/<secret>/
```

**تلگرام** — توکن ربات را در `.env` بگذار و آدرس را به خود تلگرام بده:

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."     # از @BotFather
# آدرس و همان secret را به تلگرام معرفی کن:
#   https://api.telegram.org/bot<TOKEN>/setWebhook
#     ?url=<آدرس وب‌هوک>&secret_token=<همان secret داخل آدرس>
```

**اینستاگرام / واتس‌اپ** — بعد از تأیید اپ در Meta:

```powershell
$env:META_APP_SECRET   = "..."   # هر تحویل با این امضا می‌شود
$env:META_VERIFY_TOKEN = "..."   # همان که در دست‌دادن اولیه اکو می‌شود
```

> آدرس وب‌هوک مثل رمز است: هرکس داشته باشد می‌تواند پیامی بفرستد که ایجنت
> فروش را به کار بیندازد. فقط در تنظیمات همان پلتفرم بگذار.

## Dev machine (no AI models installed)

Works out of the box with SQLite. AI endpoints return honest errors if Ollama
is unreachable. Run the test suite (all AI calls mocked, ffmpeg tests real):

```powershell
python manage.py test
```

## Main system (models installed)

1. Edit `.env`: set `OLLAMA_BASE_URL` and `COMFYUI_BASE_URL`. (Database is SQLite — nothing to configure.)
2. Start infra: `ollama serve`, ComfyUI, Redis.
3. Start the worker (Windows needs `--pool=solo`):
   ```powershell
   celery -A config worker -l info -Q celery,ai,gpu --pool=solo
   ```
   (No Redis? Set `CELERY_TASK_ALWAYS_EAGER=true` in `.env` for synchronous dev runs.)
4. Start Django: `python manage.py runserver 0.0.0.0:8000`

### Smoke test on the main system (real integration)

Easiest path: run `..\start.bat`, open http://localhost:5173 and walk the UI:

1. ثبت‌نام → ساخت فروشگاه → افزودن محصول → آپلود حداقل یک عکس
2. صفحه محصول → **تحلیل با هوش مصنوعی** (فاز ۵ — qwen3-vl + qwq)
3. **تحلیل بازار و رقبا** با چند خط اطلاعات واقعی رقبا (فاز ۶)
4. **استودیوی تصویر** (فاز ۹ — FLUX): پوستر تبلیغاتی / عکس اینستاگرامی / بهبود عکس
5. **تولید کپشن** برای سه پلتفرم (فاز ۱۰)
6. **استودیوی ویدیو** → تولید سناریو (فاز ۱۱) → 🎥 تولید ویدیو (فاز ۱۲ — Wan 2.2 واقعی،
   قطعه‌به‌قطعه با پیوستگی فریم آخر؛ پیشرفت قطعه i/N را نشان می‌دهد و آخرش پلیر ویدیو)
   → 🔊 صداگذاری (فاز ۱۳ — edge-tts با صدای `fa-IR-FaridNeural`؛ gTTS فقط
   جایگزین اضطراری است و فارسی ندارد. اینترنت لازم دارد.)
7. صفحه فروشگاه → **💬 چت فروش** (فاز ۷): سؤال محصول، موجودی، «می‌خوامش» → سفارش
   پیش‌نویس، و «شکایت دارم» → ارجاع به انسان
8. صفحه فروشگاه → **📣 کمپین‌ها** (فاز ۱۴/۱۵): ساخت کمپین از محتوای تولیدشده →
   تأیید → 🚀 انتشار با n8n (نیازمند `N8N_WEBHOOK_URL` در `.env` و اجرای n8n)
9. صفحه فروشگاه → **📈 آمار** (فاز ۱۶): KPIها و روند ۱۴ روزه — همه از داده واقعی

## Production notes (Phase 17)

- Set `DJANGO_DEBUG=false` + a long random `DJANGO_SECRET_KEY` + explicit
  `DJANGO_ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
- Rate limits via `THROTTLE_ANON` / `THROTTLE_USER`; upload cap via `MAX_UPLOAD_MB`.
- Behind HTTPS enable `SECURE_SSL_REDIRECT` / `SESSION_COOKIE_SECURE` /
  `CSRF_COOKIE_SECURE` / `SECURE_HSTS_SECONDS` (see `.env.example`).
- Verify with: `python manage.py check --deploy` (remaining warnings are the
  SSL flags above — intentional on plain-HTTP LAN deployments).

> اگر ComfyUI روی گراف‌های FLUX خطای validation داد، راهنمای
> `services/comfyui/workflows/ui_reference/README.md` را ببین (خروجی API-format از خود ComfyUI).

API-level equivalent:

```powershell
# auth:    POST /api/v1/auth/register/  →  POST /api/v1/auth/login/
# store:   POST /api/v1/stores/          product: POST /api/v1/products/
# image:   POST /api/v1/products/{id}/images/        (multipart, field: image)
# AI:      POST /api/v1/products/{id}/analyze/        → GET /api/v1/jobs/{job_id}/
#          GET  /api/v1/products/{id}/intelligence/
# market:  POST /api/v1/products/{id}/market-analysis/ {research_inputs}
# image:   POST /api/v1/products/{id}/image-studio/ {kind: POSTER|PRODUCT_SHOT|ENHANCED}
# caption: POST /api/v1/products/{id}/captions/ {platforms, tone}
# script:  POST /api/v1/products/{id}/video-script/ {duration}
# video:   POST /api/v1/video-scripts/{id}/generate/   (needs ComfyUI + wan22 models)
# voice:   POST /api/v1/video-scripts/{id}/voice/      (after final video; needs internet — edge-tts)
# chat:    POST /api/v1/stores/{id}/chat/ {message}
# campaign: POST /api/v1/campaigns/ → /approve/ → /publish/ {platforms:["instagram"]}
```

### ComfyUI workflows

- `services/comfyui/workflows/wan22_i2v_v1.json` — **proven** Wan 2.2 I2V graph
  (from the old Flask prototype). Patch inputs by name via
  `services.comfyui.workflows.load_workflow / patch_workflow`.
- `flux_txt2img_v1.json` و `flux_img_edit_v1.json` — هر دو **در قالب API** و
  آماده‌ی ارسال. نسخه‌ی UI-format اصلی‌شان در `ui_reference/` نگه داشته شده
  تا اگر ComfyUI گراف را رد کرد بشود دوباره از خود ComfyUI صادر کرد.

Quick real ComfyUI check (Django shell on the main system):

```python
from services.comfyui.client import ComfyUIClient
from services.comfyui.workflows import load_workflow, patch_workflow
client = ComfyUIClient()
name = client.upload_image("path/to/test.jpg")
graph, manifest = load_workflow("wan22_i2v", "v1")
graph = patch_workflow(graph, manifest, image=name,
                       positive="cinematic natural movement", negative="blurry",
                       filename_prefix="upmarket/smoke")
print(client.generate(graph, "media/generated"))   # → local mp4 path
```

## Frontend

The React dashboard lives in `../frontend/` (see its README). In dev it proxies
`/api` and `/media` to this backend at `http://localhost:8000`.

## آنچه روی این دستگاه ثابت نمی‌شود

مدل‌ها روی **سیستم اصلی** هستند، نه اینجا. پس:

- اجرای واقعی Ollama و ComfyUI فقط آنجا قابل تأیید است. اینجا تست‌ها با
  شبیه‌ساز اجرا می‌شوند — و شبیه‌ساز عمداً همان‌طور خراب‌کاری می‌کند که
  مدل محلی می‌کند (نشت `<think>`، بلوک ```json، کامای جاافتاده، خروجی
  قطع‌شده، ۵۰۰ کمبود VRAM).
- کیفیت خروجی — اینکه پوستر و ویدیو روی محصول واقعی **قابل فروش** باشند —
  با هیچ تستی معلوم نمی‌شود. راهنمایش: [`../test.md`](../test.md).
- داکر روی این دستگاه نیست، پس چیدمان production
  ([`../deploy/`](../deploy/)) نوشته شده ولی روی سرور واقعی اجرا نشده.

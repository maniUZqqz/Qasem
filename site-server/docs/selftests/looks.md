# خودآزمونِ «سبک تصویر › تصویرِ نمونه» (برای آزمونِ پذیرشِ خودکارِ سرورِ پردازش)

قراردادِ آزمون در کدِ آماده (`backend/apps/looks/selftest.py`: `spec(caps)` و `check(job)`) است. آزمونِ پذیرشِ مرکزی (`apps/compute/selftests/looks.py`)
همین دو تابع را می‌گیرد و زیرِ کلیدِ `looks_sample` ثبت می‌کند؛ نیازی به بلوکِ json در این فایل نیست (و گذاشتنش آزمونِ تکراری می‌سازد).

## چه چیزی آزموده می‌شود

ComfyUI روی گره بالا می‌آید، مدلِ FLUX dev (چک‌پوینتِ fp8 یا UNET + CLIP + VAE) بارگذاری می‌شود و **یک تصویرِ ۵۱۲×۵۱۲** از یک بطریِ ساده با سبکِ «سینمایی» می‌سازد.
همان مسیری است که تصویرهای نمونهٔ ۱۱۶ سبک و پس‌زمینهٔ سبک‌دارِ تامنیل به کار می‌برند (کارِ عمومیِ `comfy.graph`)؛ قبول‌شدنش یعنی این ویژگی کار می‌کند.
هیچ بسته یا مدلِ تازه‌ای لازم نیست؛ مدل‌های خودِ مالک (ComfyUI_windows_portable) به کار می‌روند.

## کار

* نوعِ کار: `comfy.graph`  ·  `origin`: `selftest-looks`  ·  مهلت: ۹۰۰ ثانیه  ·  بدونِ فایلِ ورودی
* بار (payload): `{"graph": <گرافِ API ِ ComfyUI>, "uploads": [], "x_looksample": {"selftest": true, "key": "cinematic_realistic", "seed": 4321, "size": [512, 512]}}`

```python
from apps.looks import selftest
s = selftest.spec()          # یا selftest.spec(node.capabilities)
# s["kind"], s["payload"], s["origin"], s["timeout_s"], s["expect"] = {"size": [512, 512], "min_bytes": 10000, "min_std": 6.0}
job = compute.enqueue_durable(s["kind"], s["payload"], {}, origin=s["origin"], timeout_s=s["timeout_s"])
```

`spec()` اگر روی گره مدلِ FLUX dev نباشد `GraphError` (پیامِ فارسی) می‌دهد ⇒ آزمون «ناموفق: مدل نصب نیست» ثبت شود.

## شرطِ قبولی (`selftest.check(job)` ⇒ `(ok, پیامِ فارسی)`)

1. وضعیتِ کار `COMPLETED` و دست‌کم یک خروجیِ تصویری (`meta.primary` یا اولین تصویر).
2. فایل **PNG** و دقیقاً ۵۱۲×۵۱۲ است.
3. تصویر **یک‌رنگ نیست**: انحرافِ معیارِ روشناییِ پیکسل‌ها ≥ ۶.
4. اندازهٔ فایل **بزرگ‌تر از ۱۰ کیلوبایت** است (تصویرِ واقعی؛ نه یک گرادیانِ خالی).

## اجرای خودکار (همین حالا فعال است)

* آزمونِ مرکزی با نسخهٔ تازهٔ عامل، هر شب و با دکمهٔ «آزمونِ کامل» اجرا می‌شود.
* beat ِ `looks-samples` (هر ۵ دقیقه، `apps.looks.tasks.step`) هم `selftest.auto_step()` را صدا می‌زند: کارِ آزمون را (اگر آزمونِ بازی نیست و نوبتش رسیده) در صفِ ماندگار می‌گذارد،
  نتیجهٔ کارِ تمام‌شده را با `check` می‌سنجد و در `ComputeJob.result["selftest"]` می‌نویسد؛ `selftest.status()` همان را برای پنل می‌خواند (در `/api/v1/looks/samples/`).
  قبول‌شده هفته‌ای یک بار و ردشده هر ۶ ساعت دوباره آزموده می‌شود.
* گره که روشن شد، همین beat (`apps.looks.samples.auto_step`) دستهٔ ۱۲تاییِ تصویرهای نمونه را هم در صف می‌گذارد؛ پس هیچ کاری دستی نیست.

# جداسازیِ پس‌زمینهٔ عکس روی سرورِ پردازش (سه مدل)

خواستهٔ مالک: «سه راه هم باشه بشه همه رو تست کرد، ولی باید اول دانلود بشه توی سرور پردازش.» هر سه مدل **فقط روی سرورِ پردازش (کامپیوترِ GPU)** اجرا می‌شوند؛ روی سرورِ سایت هیچ مدلی نصب یا اجرا نمی‌شود. نرم‌افزارِ گره از نسخهٔ **۲٫۷** این را بلد است.

## مدل‌ها

| کلید | مدل | حجم | مجوز | فایل روی گره | منبع (اول آینهٔ خودِ سایت) |
|---|---|---|---|---|---|
| `u2netp` | U²-Net سبک | ۴٫۶ مگ | Apache-2.0 | `models\photo-matting\u2netp.onnx` | سایت ← github.com/danielgatis/rembg v0.0.0 |
| `isnet` | IS-Net همه‌کاره (isnet-general-use) | ۱۷۹ مگ (۱۷۰ مبی‌بایت) | Apache-2.0 | `models\photo-matting\isnet-general-use.onnx` | سایت ← همان رِلیز |
| `birefnet-lite` | BiRefNet سبک | ۲۲۴ مگ | MIT | `tools\PersianAiKit\Photo\models\background\birefnet-lite.onnx` (فایلِ خودِ ادیتورِ عکس؛ دوباره دانلود نمی‌شود) | سایت ← hf-mirror ← huggingface (onnx-community/BiRefNet_lite-ONNX) |

* sha256 و اندازهٔ دقیق هر فایل در `processing/downloads/matting.json` (و `photo.json` برای BiRefNet) است؛ دانلودکننده هر فایل را با sha256 وارسی می‌کند، دانلود ازسرگیر است (`nm_fetch`).
* آینه‌ها روی سایت: `http://87.107.160.17:8040/3d/files/downloads/{u2netp,isnet-general-use,birefnet-lite}.onnx` (از ایران سریع‌تر از گیت‌هاب).
* هر سه بسته «اختیاری» هستند: با هر START.bat خودکار دانلود نمی‌شوند؛ با دکمهٔ دانلود (یا دستورِ پایین) و طبقِ **زمان‌بندیِ دانلود** (پیش‌فرض: بازهٔ شبانهٔ ۰۲:۰۰ تا ۰۷:۰۰ به وقتِ تهران، اگر در «زمان‌بندیِ دانلود» روشن باشد) گرفته می‌شوند.

## نصب روی سرورِ پردازش (دستورها)

روی کامپیوترِ گرافیکی، در پوشهٔ `processing` (کنارِ START.bat):

1. **یک بار** `Update.bat` را اجرا کنید تا نرم‌افزارِ گره ۲٫۷ شود.
2. `Install-Matting.bat` را اجرا کنید. این فایل:
   * اگر هیچ پایتونی روی این کامپیوتر `onnxruntime` ندارد، یک محیطِ کوچکِ خودش می‌سازد (`onnxruntime-directml` + `numpy` + `Pillow`، حدود ۶۰ مگ؛ با DirectML روی کارت گرافیک اجرا می‌شود و CUDA لازم نیست)؛ اگر پایتونی که `onnxruntime` دارد (مثلاً محیطِ صدا) هست، **همان را به‌کار می‌برد و چیزی دوباره نصب نمی‌کند** (محیطی که GPU دارد بر محیطِ فقط‑CPU می‌چربد)؛
   * بعد `matting-u2netp`، `matting-isnet` و `photo-background` (BiRefNet) را می‌گیرد.
3. `Test-Matting.bat` را اجرا کنید: هر مدلِ نصب‌شده را روی یک عکسِ آزمایشی می‌سنجد و می‌گوید زمانِ بارگذاری و اجرا، دستگاه (`dml`/`cuda`/`cpu`) و «معقول بودنِ برش» چیست. فقط یک مدل: `Test-Matting.bat --model isnet`.

از پنل: «ابزارها ← سرورهای پردازش»؛ دکمهٔ دانلودِ مدل‌های جداسازی (ادیتورِ عکس) همان بسته‌ها را با انتخابِ «الان / در ساعتِ … / در بازهٔ شبانه» می‌فرستد؛ دکمهٔ «تست» یک کارِ `photo.matting` با `bench` می‌فرستد که تا نصب شدنِ مدل در صف می‌ماند.

دستورهای دستی (همه در پوشهٔ processing):

```
python photo_matting.py status                       # چه چیزی نصب است و کدام پایتون اجرایش می‌کند (JSON)
python photo_matting.py test [--model isnet]         # همان Test-Matting.bat
python photo_matting.py bench --model all --runs 3   # سنجش در همین پایتون (باید onnxruntime داشته باشد)
python photo_matting.py run --model u2netp --model-file F --image in.jpg --out-dir out [--feather 4] [--no-keep-size]
Download-Models.bat --only matting-runtime           # فقط محیطِ اجرا
Download-Models.bat --only matting-isnet             # فقط یک مدل
```

متغیرهای محیطی: `NM_MATTING=0` (خاموش)، `NM_MATTING_PROVIDER=cpu|dml|cuda`، `NM_MATTING_PYTHON=<python.exe>`، `NM_MATTING_TIMEOUT_S`.

## قرارداد با ادیتورِ عکس

* کار: `photo.matting`، توانایی `photo_matting` (نه `photo`: به سرویسِ .NET وابسته نیست). ثبت: `compute.enqueue_durable("photo.matting", payload, files, store=..., origin="photomatting", priority=60)` یا ساده‌تر `apps.compute.matting.request(model, path, ...)`.
* ورودی: `{"image": "<نامِ فایل>", "model": "u2netp"|"isnet"|"birefnet-lite", "feather": 0, "keep_size": true}`؛ `keep_size=false` ضلعِ بلند را به ۱۶۰۰ می‌رساند.
* خروجی: `cutout.png` (RGBA، همان اندازه؛ `meta.primary`)، `mask.png` (۸بیتی، همان آلفا)، `photo-matting.json` `{"model","seconds","size","device"}`. خواندن: `job.outputs()` و `compute.output_path(job, name)` یا `matting.result(job)`.
* گزارشِ گره (heartbeat): `caps["photo_matting"]=True`، `caps["matting_models"][key] = {state: installed|downloading|queued|missing|failed, size_mb, progress?, error?}`، `caps["matting_runtime"] = {ok, providers, message?}`.
* مدلی که نصب نیست **کار را ناموفق نمی‌کند**: سایت (`services.claim`) کار را تا نصب شدنِ مدل و آماده بودنِ محیطِ اجرا به گره نمی‌دهد؛ کار در صف می‌ماند با پیامِ «منتظرِ دانلودِ مدل …». فایلِ خراب، پس از گرفته شدنِ کار، خطای عادی (بدونِ تکرار) با پیامِ «فایلِ مدل خراب است؛ دوباره دانلودش کنید» می‌دهد.
* سمتِ سایت برای پنل: `apps.compute.matting.status()` (وضعیتِ هر مدل، `ready_now`، `installed_on`)، `start_download(models, node=None, when=None)`، `start_test(model)`؛ و برای کارکنان `GET /api/v1/compute/matting/`، `POST .../matting/download/ {models, node?, when?}`، `POST .../matting/test/ {model, node?}`.

## حافظه و سرعت

* `u2netp` ورودیِ ۳۲۰ پیکسل؛ `isnet` و `birefnet-lite` ورودیِ ۱۰۲۴ پیکسل.
* روی CPU (آزمونِ سرورِ سایت، فقط برای راستی‌آزمایی): `u2netp` حدود ۰٫۵ ثانیه، `isnet` حدود ۵ ثانیه برای یک عکس.
* `birefnet-lite` روی CPU حدود **۶٫۵ گیگابایت رمِ آزاد** می‌خواهد؛ روی GPU با DirectML/CUDA (کارت ۱۲ گیگی) مشکلی ندارد. اگر GPU حافظه کم آورد، همان عکس خودکار روی CPU تمام می‌شود.
* روی سرورِ سایت (رمِ ۴ گیگ) این مدل‌ها اجرا **نمی‌شوند** (قصد هم همین است).

## آزمون‌ها

`processing/tests/test_photo_matting.py` (۲۰ آزمون: جدولِ مدل‌ها با مانیفست، وضعیت‌ها، پیدا کردنِ پایتون، اجرای واقعیِ مدل روی CPU با کارِ جعلی، فایلِ خراب، لغو، سقفِ زمان، benchmark، CLI) و `apps/compute/tests_matting.py` (توانایی، نگه‌داشتنِ کار تا نصبِ مدل، وضعیت، دانلودِ زمان‌بندی‌شده، API).

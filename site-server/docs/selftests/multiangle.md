# آزمونِ خودکارِ سرورِ پردازش: «چندزاویه»

آزمونِ پذیرشِ گره (`backend/apps/compute/selftests/multiangle.py`، گروهِ «ویدیو») همین کار را در «آزمونِ کاملِ سرورِ پردازش» اجرا و گزارش می‌کند؛ ویژگیِ چندزاویه هم یک آزمونِ خودکارِ جدا دارد که از همان لحظهٔ روشن‌شدنِ گره و بدونِ دخالتِ کسی اجرا می‌شود:

* سایت: `apps.multiangle.services.autocheck()` (کارِ beat با نام `multiangle-autocheck`، هر ۲ دقیقه). برای هر گرهٔ روشنی که `caps.multiangle` دارد: اگر `caps.multiangle_ready` کامل نیست ⇐ نصب را درخواست می‌کند؛ اگر کامل است و آزمونی نیست (یا نسخهٔ گره عوض شده، یا آخرین آزمون ناموفق بوده و ۶ ساعت گذشته) ⇐ `request_selftest(node)`.
* دستی: `POST /api/v1/stores/<id>/multiangle/selftest/` (کارکنان) یا دکمهٔ «آزمونِ خودکار» در کارتِ سرورِ پردازشِ صفحهٔ چندزاویه.
* نتیجه: یک `MultiAngleRun(mode="selftest")` با `checks` (فهرستِ زیر) و `state=READY` فقط اگر همه گذشته باشند؛ در صفحه «گذشت» یا دلیلِ شکست دیده می‌شود.

## وصل‌شده به پوشهٔ selftests
ماژولِ `selftests/multiangle.py` نوعِ `multiangle.selftest` را با `{"selftest": true}` می‌فرستد و `selftest.json` را می‌سنجد؛ اگر عاملِ گره این نوع را اعلام نکرده باشد (نسخهٔ قدیمی) «اجرا نشد» ثبت می‌شود نه «رد». `services.request_selftest` و `services.ingest` (شاخهٔ SELFTEST) مسیرِ جدای خودِ ویژگی‌اند.

## کارِ آزمون
`multiangle.selftest` با payload `{"selftest": true}` و بدونِ ورودی (ورودی‌ها را موتور خودش با ffmpeg می‌سازد: یک کلیپِ ۸ ثانیه‌ایِ مصنوعیِ ۱۲۸۰×۷۲۰ با صدایی که هر ۲٫۶ ثانیه مکث می‌کند، و یک عکسِ مصنوعی؛ هیچ آدمِ واقعی‌ای در آزمون نیست).
۱. `multiangle.virtual` روی کلیپ (wide, medium, close، ۳۶۰p) ⇐ ۲. `multiangle.move` (truck_right) روی عکس.

خروجی: `selftest.json` = `{"ok": bool, "checks": [{"name", "ok", "detail"}]}`

## شرطِ قبولی (همه باید ok باشند)
| نام | معنی |
|---|---|
| `runtime` | numpy + OpenCV + onnxruntime در Pythonِ موتور هست |
| `models` | هر سه مدل نصب‌اند |
| `virtual.angles` | دست‌کم دو زاویه ساخته شد و فایل‌ها هستند |
| `virtual.synced` | تعدادِ فریمِ خروجی = ۸ ثانیه × ۲۵ (±۲): زاویه‌ها هم‌گام‌اند |
| `virtual.cuts` | دست‌کم دو نما در مولتی‌کم و فایلِ `multicam.mp4` |
| `virtual.on_sound` | دست‌کم یک برش روی مکث/ضرب افتاد |
| `virtual.models_ran` | دست‌کم یک مدل واقعاً اجرا شد (دستگاهش در `plan.device`) |
| `move.frames` | دست‌کم ۴۵ فریم (۲ ثانیه × ۲۵ = ۵۰) |
| `move.parallax` | فریمِ آخر با فریمِ اول فرقِ واقعی دارد (دوربین واقعاً حرکت کرده) |
| `move.depth` | `depth.png` ساخته شد |

اجرای دستی روی گره: `python multiangle_engine.py selftest --out-dir OUT --models <data>\models\multiangle --ffmpeg ffmpeg` (با Pythonِ `<data>\venvs\multiangle`).

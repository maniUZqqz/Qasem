# آزمونِ خودکارِ سرورِ پردازش — استودیوی موشن

این فایل را «آزمونِ خودکارِ سرورِ پردازش» (`backend/apps/compute/selftests/docs_loader.py`) می‌خواند و برای هر گره یک کارِ واقعیِ کوچک می‌فرستد.
ماژولِ کدیِ `backend/apps/compute/selftests/motion.py` همین آزمون را با کلیدِ `motion_studio` ثبت می‌کند و سنجشِ عمیق‌تری دارد
(ffprobe: ۹۰ فریم، ۵۴۰×۹۶۰)؛ این بلوک قرارداد و پشتیبان است (اگر آن ماژول بار نشود، `docs_loader.py` همین بلوک را ثبت می‌کند).
همان کار و سنجش در `backend/apps/motion/selftest.py` (`enqueue()` / `check()`) هم هست.

## چه می‌سنجد
یک رندرِ قالبیِ ۳ ثانیه‌ای (۵۴۰×۹۶۰، سبکِ «وکتورِ تخت»، متنِ فارسی) با `motion.render` روی کارتِ گرافیکِ گره:

- گره باید `motion.render` را اعلام کرده باشد و ابزارِ موشن نصب (`caps.motion.state == "ready"`) — تا نصبِ خودکار تمام نشود کار در صف می‌ماند.
- خروجی `out.mp4` (بیش از ۵ کیلوبایت) و `motion-render.json` با `frames`، `width`، `height`، `device`.
- `device` نباید `cpu` باشد: یعنی Chromium روی کارتِ گرافیک (ANGLE/D3D11) رسم کرده است. (کدگذاریِ H.264 در Remotion روی ویندوز CPU است و عمداً «رد» حساب نمی‌شود.)
- (در `selftest.py` سنجشِ عمیق‌تر هم هست: ۹۰ فریم و ابعادِ ۵۴۰×۹۶۰ با ffprobe.)

```json
{
  "key": "motion_studio",
  "label": "رندرِ موشن‌گرافیک (استودیوی موشن)",
  "group": "video",
  "kind": "motion.render",
  "payload": {
    "composition": "Template",
    "props": {
      "spec": {
        "version": 1,
        "style": "flat-vector",
        "aspect": "9:16",
        "fps": 30,
        "lang": "fa",
        "digits": "auto",
        "brand": {"use_brand_colors": true, "show_logo": false, "colors": ["#126F85", "#163F75"]},
        "scenes": [
          {"type": "title", "duration": 3, "kicker": "آزمونِ موشن", "title": "سلام، چغر!", "subtitle": "رندرِ ۳ ثانیه‌ای با متنِ فارسی"}
        ]
      }
    },
    "scale": 0.5,
    "crf": 23,
    "max_seconds": 10,
    "title": "motion selftest",
    "style": "flat-vector",
    "mode": "template",
    "selftest": true
  },
  "timeout_s": 900,
  "gpu_required": true,
  "requires": {"kinds": ["motion.render"], "caps": ["motion_render"]},
  "check": {
    "outputs_min": 1,
    "output_ext": [".mp4"],
    "min_bytes": 5000,
    "json_file": "motion-render.json",
    "json_has": ["frames", "width", "height", "device"],
    "forbid_device": ["cpu"]
  },
  "requeue_kinds": ["motion.render"],
  "order": 160,
  "describe": "رندرِ ۳ ثانیه‌ای موشن روی کارتِ گرافیک؛ نصبِ ابزارِ موشن خودکار است"
}
```

## اگر رد شد
- «این سرور قابلیتِ motion_render را ندارد» ⇐ عاملِ گره هنوز نسخهٔ جدید را نگرفته (به‌روزرسانی کنید).
- کار در صف می‌ماند ⇐ نصبِ خودکار در جریان است؛ وضعیت در صفحهٔ «استودیوی موشن» (بنر) و در پنل ⇐ سرورهای پردازش دیده می‌شود.
- «روی دستگاهِ نامجاز (cpu)» ⇐ Chromium نتوانست از کارتِ گرافیک استفاده کند؛ `device_note` علت را می‌گوید (درایور؟ کارتِ مجزا نیست؟).

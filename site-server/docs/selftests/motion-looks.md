# آزمونِ خودکارِ سرورِ پردازش — سبک‌هایِ تازهٔ موشن (از InstAI)

این فایل را «آزمونِ خودکارِ سرورِ پردازش» (`backend/apps/compute/selftests/docs_loader.py`) می‌خواند. ماژولِ کدیِ `backend/apps/compute/selftests/motion_looks.py` همین آزمون را با کلیدِ
`studio_motion_looks` ثبت می‌کند و سنجشِ عمیق‌تری دارد (پیکسل)؛ این بلوک قرارداد و پشتیبان است (اگر آن ماژول بار نشود، `docs_loader.py` همین بلوک را ثبت می‌کند).
نوعِ کارِ تازه یا نصبِ تازه‌ای روی گره نیست: همان `motion.render`.

## چه می‌سنجد
یک رندرِ ۳ ثانیه‌ای (۵۴۰×۹۶۰) با سبکِ «موزاییک و کاشی» (`mosaic-tiles`) که از نوعِ تازهٔ پس‌زمینهٔ `mosaic` استفاده می‌کند.
گرهٔ ویندوزی موتور را از «بستهٔ موشنِ» سایت می‌گیرد؛ اگر بسته قدیمی بماند نوعِ تازه را نمی‌شناسد و بی‌سروصدا زمینهٔ ساده می‌کشد (رندر «موفق» است ولی سبک غلط).
ماژولِ کدی سه چیز را می‌سنجد: ویدیو (۹۰ فریمِ ۵۴۰×۹۶۰ با ffprobe و `device` غیرِ cpu)، اینکه نسخهٔ بسته‌ای که گره با آن رندر کرده (`meta.pack`) همان نسخهٔ آخرین بستهٔ سایت (`nm-motion-pack.json`) است، و اینکه bundleِ سایت موتورِ تازه را دارد (نشانهٔ `nm-seigaiha`). این بلوکِ بدونِ کد فقط خودِ رندر را می‌سنجد (خروجیِ mp4 و `device` غیرِ cpu).

```json
{
  "key": "studio_motion_looks",
  "label": "استودیوی موشن: سبک‌هایِ تازه (موزاییک و کاشی)",
  "group": "video",
  "kind": "motion.render",
  "payload": {
    "composition": "Template",
    "props": {
      "spec": {
        "version": 1,
        "style": "mosaic-tiles",
        "aspect": "9:16",
        "fps": 30,
        "lang": "fa",
        "digits": "auto",
        "brand": {"use_brand_colors": false, "show_logo": false},
        "scenes": [
          {"type": "title", "duration": 3, "kicker": "سبکِ تازه", "title": "با چغر چغر تر شو", "subtitle": "آزمونِ سبک‌هایِ تازهٔ موشن"}
        ]
      }
    },
    "scale": 0.5,
    "crf": 23,
    "max_seconds": 10,
    "title": "motion looks selftest",
    "style": "mosaic-tiles",
    "mode": "template",
    "selftest": true
  },
  "timeout_s": 1200,
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
  "order": 162,
  "describe": "رندرِ ۳ ثانیه‌ایِ سبکِ «موزاییک و کاشی»؛ قبول = ویدیو با موتورِ تازه کشیده شد"
}
```

## اگر رد شد
- «بستهٔ رندرِ خودِ سایت موتورِ تازه را ندارد» ⇐ روی سایت `manage.py motion_build` را اجرا کنید (bundle، بسته و `nm-motion-pack.json` تازه می‌شود)؛ گره در به‌روزرسانیِ بعدی آن را می‌گیرد.
- «گره با بستهٔ موشنِ قدیمی رندر کرد» ⇐ ابزارِ موشنِ گره هر ۳۰ دقیقه manifest را می‌خواند و بستهٔ تازه را خودش نصب می‌کند؛ کمی صبر کنید و دوباره بسنجید.
- «این سرور قابلیتِ motion_render را ندارد» ⇐ عاملِ گره هنوز نسخهٔ جدید را نگرفته (به‌روزرسانی کنید).

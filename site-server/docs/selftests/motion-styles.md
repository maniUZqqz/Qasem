# آزمونِ خودکارِ سرورِ پردازش — «سبکِ تازه‌ی» موشن (سبکِ شخصیِ کاربر)

این فایل را «آزمونِ خودکارِ سرورِ پردازش» (`backend/apps/compute/selftests/docs_loader.py`) می‌خواند. ماژولِ کدیِ `backend/apps/compute/selftests/motion_styles.py` همین آزمون را با کلیدِ
`studio_motion_styles` ثبت می‌کند و سنجشِ عمیق‌تری دارد (پیکسلِ ویدیو)؛ این بلوک قرارداد و پشتیبان است (اگر آن ماژول بار نشود، `docs_loader.py` همین بلوک را ثبت می‌کند).
نوعِ کارِ تازه یا نصبِ تازه‌ای روی گره نیست: همان `motion.render`.

## چه می‌سنجد
سبکِ شخصی (ساختهٔ ویرایشگرِ «سبکِ تازه») در کاتالوگِ گره نیست؛ همراهِ خودِ طرح می‌رود (`props.spec.style_def`) و موتورِ Remotion در بستهٔ موشنِ گره آن را می‌کشد.
اگر بستهٔ گره قدیمی باشد، موتور `style_def` را نمی‌شناسد و **بی‌سروصدا سبکِ پیش‌فرض** را می‌کشد (رندر «موفق» است ولی سبک غلط است). این آزمون یک رندرِ ۳ ثانیه‌ای (۵۴۰×۹۶۰)
با یک سبکِ ساختگیِ **بنفشِ تک‌رنگ** (`#6a1b9a`؛ هیچ سبکِ کاتالوگ چنین زمینه‌ای ندارد) می‌فرستد و ماژولِ کدی چهار چیز را می‌سنجد:

1. ویدیو ۹۰ فریمِ ۵۴۰×۹۶۰، ۳ ثانیه و `device` غیرِ cpu؛
2. **پیکسلِ گوشهٔ ویدیو بنفش است** (همان رنگِ زمینهٔ سبک) ⇒ گره سبکِ شخصی را واقعاً کشیده؛
3. `meta.pack` همان نسخهٔ آخرین بستهٔ سایت (`nm-motion-pack.json`) است و `meta.pack_features` شاملِ `style_def` است؛
4. bundleِ خودِ سایت نشانهٔ `data-nm-style-def` را دارد (موتورِ تازه).

بلوکِ بدونِ کد (زیر) فقط خودِ رندر را می‌سنجد (خروجیِ mp4 و `device` غیرِ cpu)؛ سنجشِ پیکسل و بسته فقط در ماژولِ کدی است.

```json
{
  "key": "studio_motion_styles",
  "label": "استودیوی موشن: سبکِ تازهٔ شخصی (style_def)",
  "group": "video",
  "kind": "motion.render",
  "payload": {
    "composition": "Template",
    "props": {
      "spec": {
        "version": 2,
        "style": "u0-selftest",
        "style_def": {
          "id": "u0-selftest", "name_fa": "آزمون", "name_en": "Selftest", "inspired": null, "group": "custom", "about": "",
          "palette": {"bg": "#6a1b9a", "bg2": "#4a148c", "ink": "#ffffff", "paper": "#ffffff", "accent": "#ffd54f", "accent2": "#80deea", "accent3": "#ff8a80", "muted": "#e1bee7"},
          "font": {"latin": "vazirmatn", "fa": "vazirmatn", "weight": 700, "body_latin": null, "body_fa": null, "case": "none", "track": 0, "lh": 1.3},
          "bg": {"kind": "solid", "c": "bg"}, "bg2": null, "tex": [], "decor": [], "text": {"fx": "plain"},
          "shape": {"radius": 16, "border": 0, "shadow": "none", "fill": "paper"},
          "motion": {"enter": "fade", "spring": [30, 120, 1.0], "stagger": 6, "stepFps": null, "wobble": 0, "cam": null, "ease": "out-expo"},
          "trans": {"kind": "fade", "frames": 12}, "fx": {}
        },
        "aspect": "9:16",
        "fps": 30,
        "lang": "fa",
        "digits": "auto",
        "brand": {"use_brand_colors": false, "show_logo": false},
        "scenes": [
          {"type": "title", "duration": 3, "kicker": "سبکِ شخصی", "title": "با چغر چغر تر شو", "subtitle": "آزمونِ سبکِ تازه"}
        ]
      }
    },
    "scale": 0.5,
    "crf": 23,
    "max_seconds": 10,
    "title": "motion style selftest",
    "style": "u0-selftest",
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
  "order": 163,
  "describe": "رندرِ ۳ ثانیه‌ایِ یک سبکِ ساختگیِ بنفش که همراهِ طرح می‌رود؛ قبول = ویدیو ساخته شد"
}
```

## اگر رد شد
- «موتورِ گره سبکِ شخصی (style_def) را نکشیده» ⇐ بستهٔ موشنِ گره قدیمی است. روی سایت `manage.py motion_build` را اجرا کنید (bundle، بستهٔ گره با فایلِ `FEATURES` و `nm-motion-pack.json` تازه می‌شود)؛ گره هر ۳۰ دقیقه manifest را می‌خواند و بستهٔ تازه را خودش می‌گیرد؛ کارِ سبکِ شخصیِ منتظر هم خودش بستهٔ تازه را می‌گیرد (`processing/motion_jobs.py: _refresh_pack`).
- «بستهٔ رندرِ خودِ سایت سبکِ شخصی را نمی‌شناسد» ⇐ همان `motion_build` روی سایت.

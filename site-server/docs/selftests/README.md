# آزمونِ خودکارِ سرورِ پردازش — افزودنِ آزمونِ یک ویژگی

هر ویژگی که روی سرورِ پردازش کاری (kind) اضافه می‌کند، می‌تواند با **یک فایل** در این پوشه (`docs/selftests/<ویژگی>.md`) یک آزمونِ خودکار هم اعلام کند. این فایل‌ها را
`backend/apps/compute/selftests/docs_loader.py` می‌خواند؛ بلوکِ خراب فقط خودش کنار گذاشته می‌شود و بقیه کار می‌کنند. اگر کارتان به منطقِ پایتون نیاز دارد
(مثلاً ساختنِ گراف) به‌جای این‌جا یک ماژولِ `backend/apps/compute/selftests/<ویژگی>.py` بگذارید (مثال: `thumbnails.py`، `chagher_content.py`).

در فایل یک یا چند بلوکِ <code>```json</code> بگذارید. هر بلوک یک شیء (یا فهرستی از شیءها) است:

```json
{"key": "motion_render", "label": "رندرِ موشن‌گرافیک", "group": "video", "kind": "motion.render",
 "payload": {"template": "title-card", "text": "با چغر چغرتر شو"},
 "files_b64": {"in.png": "<base64 اختیاری>"},
 "timeout_s": 900, "optional": false, "deep": false, "gpu_required": true, "order": 150,
 "requires": {"kinds": ["motion.render"], "caps": ["node_js"]},
 "check": {"outputs_min": 1, "output_ext": [".mp4"], "min_bytes": 5000, "json_file": "result.json", "json_has": ["frames"],
           "text_contains": ["ok"], "forbid_device": ["cpu"]},
 "requeue_kinds": ["motion.render"],
 "describe": "یک کارت عنوانِ دو ثانیه‌ای"}
```

- `requires.kinds`: عاملِ گره باید این نوع‌ها را در `caps["kinds"]` اعلام کرده باشد، وگرنه آزمون «اجرا نشد» (نه «رد») ثبت می‌شود. `requires.caps`: پرچم‌های `capabilities` که باید درست باشند.
- `check`: همهٔ شرط‌ها با «و»: دست‌کم `outputs_min` خروجی با پسوندِ `output_ext` و حداقل `min_bytes`؛ در `json_file` کلیدهای `json_has`؛ متن‌های `text_contains` در خروجی‌های متنی؛ `forbid_device`: دستگاه‌هایی که نباید باشند (مثلاً `cpu`).
- محتوای آزمون را از واقعیت‌های برندِ چغر بردارید (`docs/chagher/brand-facts-fa.md`): شعار «با چغر چغرتر شو»؛ **قیمت و آمار نسازید**.
- اگر آزمون به نصبِ چیزی روی گره نیاز دارد، آن را در `processing/requirements.d/<ویژگی>.json` اعلام کنید و `kinds` را همان‌جا بگذارید؛ آزمون تا پایانِ نصب «منتظرِ نصب» می‌ماند.
- آزمونِ سنگین (چند دقیقه) را `"deep": true` و `"optional": true` کنید؛ فقط با دکمهٔ «آزمونِ عمیق» اجرا می‌شود.
- پس از قبولیِ آزمون، کارهای قبلاً ناموفق/لغوشدهٔ `requeue_kinds` که علتشان سرورِ پردازش بوده (نه خطای خودِ کار یا لغوِ کاربر) دوباره به صف می‌روند (هر کار حداکثر ۲ بار).

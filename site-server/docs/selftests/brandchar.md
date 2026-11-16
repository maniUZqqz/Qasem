# آزمونِ خودکارِ «شخصیتِ برند»

ثبت‌شده در `backend/apps/compute/selftests/brandchar.py` (و منطقش در `backend/apps/brandchar/selftest.py`). دو آزمون:

| کلید | نوع | چه می‌سنجد |
|---|---|---|
| `brandchar_engine` | بی‌گره (CPU) | ۴ سبکِ کشیدن × ژست‌های نمونه × ۴ اندازه؛ شخصیت دیده می‌شود و همهٔ رنگ‌های امضا (کلیدِ رنگ) در تصویرند |
| `brandchar_render` | روی گره (GPU) | کارِ `brandchar.render` |

## کارِ نمونه (`brandchar_render`)

```
kind: brandchar.render
payload: {"prompt": "<توصیفِ انگلیسیِ شخصیتِ آزمون>, polished 2D digital illustration ...", "negative_prompt": "...", "mode": "illustrated",
          "reference": "reference.png", "width": 512, "height": 512, "steps": 4, "guidance": 3.5, "denoise": 0.55, "seed": 7, "palette": ["#126f85", ...]}
files: {"reference.png": <استیکرِ شخصیتِ «مربیِ چغر» با رنگ‌های برندِ چغر، روی زمینهٔ ساده، ۱۰۲۴>}
```

قبولی: خروجی یک تصویرِ سالم (≥ ۲۵۶ پیکسل، یک‌رنگ نباشد، > ۴ کیلوبایت) و سنجشِ ثبات (`apps.brandchar.ai_render.consistency`) روی آن اجرا شود
(نتیجهٔ رنگ و سیلوئت در متنِ آزمون می‌آید؛ ردِ رنگ «هشدار» است نه شکست، چون مدلِ تصویرساز ممکن است رنگ را کمی عوض کند).
شرط‌ها: گره `brandchar.render` را در `caps.kinds` اعلام کرده باشد (عاملِ قدیمی ⇐ «ردشده»، نه «رد»؛ بعد از به‌روزرسانی خودکار اجرا می‌شود) و ویژگیِ `brandchar` (requirements.d) نصب باشد؛ آزمون اختیاری است (در نتیجهٔ کلی نمی‌آید).

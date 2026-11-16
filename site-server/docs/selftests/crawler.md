# آزمونِ خودکارِ «مشتری‌یاب»

این قابلیت چون به منطقِ پایتون نیاز دارد (تشخیصِ «منتظرِ نصبِ مرورگر») با ماژولِ `backend/apps/compute/selftests/crawler.py` ثبت شده، نه با بلوکِ JSON.

- کار: `crawl.selftest` با `{"selftest": true}` و بدونِ ورودی؛ گره روی 127.0.0.1 یک سایتِ ساده و یک سایتِ فقط‌جاوااسکریپت بالا می‌آورد.
- گذر: `selftest.json` = `{"ok": true, "checks": [ssrf_guard, static_site, browser_ready, javascript_site_rendered]}`.
- اگر `browser_ready` نیست: «منتظرِ نصب» (نه رد)؛ نصبِ خودکار در `processing/requirements.d/crawl.json`.
- پس از قبول: کارهای قبلاً ناموفقِ `crawl.run` / `crawl.render` که علتشان سرورِ پردازش بود دوباره به صف می‌روند.
- پیش‌نیاز: عاملی که `crawl.selftest` را در `caps["kinds"]` یا `caps["crawl"]` اعلام کرده باشد.

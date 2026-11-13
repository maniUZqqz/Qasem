# بسته‌های آینه‌شدهٔ آباگرام روی سایت

گره (ویندوز، Python 3.11) برای نصبِ خودکارِ آباگرام این‌ها را از سایت می‌گیرد؛ از ایران به pypi.org / CDNها همیشه نمی‌شود تکیه کرد.
هر دو در پوشهٔ دانلودهای سایت (`data/up3d/downloads/` ⇐ `{سایت}/3d/files/downloads/`) می‌نشینند و گره آن‌ها را با Range و sha256 (از `/api/v1/compute/downloads/?name=`) می‌گیرد.

| فایل | حجم | لازم؟ | چیست |
|---|---|---|---|
| `abagram-wheels-cp311-win_amd64.zip` | ≈ ۴۰ مگابایت | توصیه می‌شود | همهٔ چرخ‌های `processing/abagram/requirements-node.lock.txt` برای CPython 3.11 / win_amd64 (PyPI، نسخه‌های قفل‌شده؛ Playwright مجوزِ Apache-2.0، FastAPI/Starlette/httpx/uvicorn/pydantic BSD/MIT، greenlet MIT، …) |
| `abagram-chromium-win64.zip` | ≈ ۱۷۳ مگابایت | فقط اگر Edge/Chrome نباشد | Chromium ۱۴۵ از Playwright 1.58.0 (پوشهٔ chromium-1208؛ بدونِ دادهٔ شخصی، بدونِ debug.log؛ مجوزِ BSD-3 و مجوزهای اجزایش در خودِ Chromium)، پوشهٔ chrome-win64 با chrome.exe. ساخته و آماده است؛ ویندوز ۱۱ همیشه Edge دارد، پس معمولاً هرگز گرفته نمی‌شود |

ساختنِ دوبارهٔ بستهٔ چرخ‌ها (روی سرور، بدونِ ویندوز):

```
python -m pip download --dest wheels --only-binary=:all: --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 \
       -r processing/abagram/requirements-node.lock.txt
python -m pip download --dest wheels --only-binary=:all: --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 colorama==0.4.6 --no-deps
cd wheels && zip -0 ../abagram-wheels-cp311-win_amd64.zip *.whl
```

(colorama جدا گرفته می‌شود چون شرطش `sys_platform == "win32"` است و روی لینوکس رد می‌شود.)
اگر `requirements-node.lock.txt` عوض شود گره بسته را دوباره می‌گیرد؛ اگر بستهٔ سایت با قفل نخواند، گره خودکار به آینه‌های PyPI می‌رود.

هشِ بستهٔ ساخته‌شده روی سرور: `sha256 a8d254aebed7680ddf8178d3cf7d64c31f2aead7d00751cf2ea45a6e3f498411` (۴۰٬۶۰۰٬۹۷۴ بایت) — فایل در `/root/stage/trends-artifacts/`.
هشِ بستهٔ Chromium: `sha256 10c2bac69b43d8078e6742daa3328b9fbd53fea445f737802eca17584c8ab6f6` (۱۸۱٬۱۹۶٬۶۶۳ بایت) — فایل در `/root/stage/trends-artifacts/`.

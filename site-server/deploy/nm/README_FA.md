# NMarketing (UpMarket) — نصب و بازگردانی روی سرورِ سایت

این بستهٔ کد، نسخهٔ یکپارچهٔ UpMarket است: پروژهٔ مادر + **سایت‌ساز** (`backend/apps/projects, code_generation, template_editor, ai_engine, project_importer` + صفحه‌های `frontend/src/features/tools/studio`) + **ویدیوی سه‌بعدی** (`backend/apps/up3d` + `frontend/src/features/tools/up3d`) + **سرورهای پردازش** (`backend/apps/compute` + `frontend/src/features/tools/compute`) که تولیدِ تصویر/ویدیو را به کامپیوترهای گرافیکیِ بی‌IP می‌سپارد (`services/comfyui/remote.py`، `COMFYUI_BASE_URL=agent://any`).

نسخهٔ هم‌خوانِ سرورِ پردازش: `UpMarket-Processing.zip` (کنارِ همین فایل ساخته شده؛ پروتکلِ `/api/v1/compute/` در هر دو یکی است).

## چیدمان روی سرور (نصبِ فعلی: 87.107.160.17، پورت 8040)

```
/var/www/NM/upmarket/
├─ backend/        جنگو (gunicorn 127.0.0.1:8041)      .env از deploy/nm/env.production ساخته می‌شود
├─ frontend/       پنلِ React (dist/ زیرِ /panel/)
├─ website/        سایتِ عمومی Next.js (127.0.0.1:3001)
├─ up3d-engine/    هستهٔ سه‌بعدی: up3d/ engine/ assets/ vendor/(Blender)
├─ data/           db.sqlite3، studio.sqlite3، up3d/ (کارها، آپلودها)، توکن‌ها، رمزِ admin
├─ venv/           پایتون
└─ deploy/nm/      install.sh · nm.sh · nginx-port_8040.conf · nm-*.service · env.production · retire-old.sh
```

## نصبِ تازه روی سرورِ دیگر (اوبونتو 22.04 + aaPanel/nginx)

1. پیش‌نیاز: `python3 -m venv` کار کند، Node 20 در `/usr/local/bin/node`، Redis روشن (`apt install redis-server`)، ffmpeg.
2. کد را در `/var/www/NM/upmarket/` باز کنید. هستهٔ سه‌بعدی (`up3d-engine/`: up3d، engine، assets و Blender در vendor) را از سرورِ فعلی یا بستهٔ UpMarket3D بیاورید.
3. `deploy/nm/ai.env` را با کلیدِ Metis بسازید (`AI_API_BASE_URL`, `AI_API_KEY`). اگر IP فرق دارد: `NM_HOST_IP=1.2.3.4 bash deploy/nm/install.sh`.
4. `bash deploy/nm/install.sh` — venv، .env، مهاجرت‌ها، کاربرِ admin (رمز در `data/admin-password.txt`)، گره‌های gpu-1/gpu-2 (توکن در `data/compute-nodes.txt`)، ساختِ پنل و سایت، سرویس‌ها، nginx، فایروال.
5. برای برگرداندنِ داده‌های قبلی: پوشهٔ `server-state/` ِ همین بسته (db.sqlite3، studio.sqlite3، .env، توکن‌ها) را **قبل از** اجرای install در جای خودش بگذارید.

مدیریت: `bash deploy/nm/nm.sh status|restart|logs [web|celery|beat|website|3d]|update`.

## نشانی‌ها

| چه | کجا |
|---|---|
| سایتِ عمومی | `/` |
| پنل | `/panel/` ⇐ ابزارها: سایت‌ساز `/panel/tools/studio`، سه‌بعدی `/panel/tools/3d`، سرورهای پردازش `/panel/tools/compute` |
| ادمینِ جنگو | `/admin/` (از پنل با پلِ سشن باز می‌شود) |
| API | `/api/v1/…` ، `/api/v1/studio/`, `/api/v1/up3d/`, `/api/v1/compute/` |
| کارگرِ رندرِ سه‌بعدی و فایل‌ها | `/3d/api/worker/…`, `/3d/files/…` |

## سرورهای پردازش

در پنل ⇐ سرورهای پردازش ⇐ «فایلِ راه‌اندازی» هر گره را بگیرید و کنارِ `START.bat` ِ بستهٔ UpMarket-Processing روی کامپیوترِ گرافیکی اجرا کنید. گره خودش وصل می‌شود؛ هیچ پورتی لازم نیست باز شود. دو گره هم‌زمان: هر کار فقط به یکی می‌رسد و کارِ یکسان دوباره ساخته نمی‌شود.

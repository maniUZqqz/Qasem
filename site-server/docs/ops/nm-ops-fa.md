# عملیاتِ سرورِ NMarketing — بکاپ، نگهبان، لاگ، ری‌لود، آزمون‌ها

این سند نتیجهٔ ممیزیِ کیفیتِ ۱۴۰۵/۰۸/۲۳ (دستهٔ `nm_ops`) است. همهٔ ابزارها در `deploy/nm/ops/` هستند و با
`bash deploy/nm/ops/install-ops.sh` نصب می‌شوند (idempotent؛ چیزی را ری‌استارت نمی‌کند؛ `--check` فقط می‌گوید چه عوض می‌شود).

| ابزار | کجا نصب می‌شود | کی اجرا می‌شود | کارش |
|---|---|---|---|
| `nm-backup` | `/usr/local/bin` | هر شب ۰۳:۵۰ UTC (۰۷:۲۰ تهران) | بکاپِ دیتابیس‌ها و داده‌ها، آزمونِ بازیابی، `status.json` برای پنل |
| `nm-watchdog` | `/usr/local/bin` | هر ۲ دقیقه | `/healthz` ؛ بعد از ۳ شکستِ پشتِ‌هم `nm-web` را ری‌استارت می‌کند |
| `nm-reload` | `/usr/local/bin` | دستی (استقرار) | ری‌لودِ بی‌وقفهٔ وب‌سرور (به‌جای `restart`) |
| `nm-tmp-sweep` | `/usr/local/bin` | هر شب ۰۴:۲۰ UTC | پاک‌کردنِ `nm-*`، `acestep-fake*`، `pip-unpack*` ِ بیش از یک روز در `/tmp` |
| `nm-nightly-tests` | `/usr/local/bin` | هر شب ۲۳:۳۰ UTC (۰۳:۰۰ تهران) | آزمونِ هر اپ جدا و پشتِ‌هم (nice 10، زیرِ قفلِ سنگین) ⇒ صفحهٔ «خودآزمایی» |
| `nm-logrotate.conf` | `/etc/logrotate.d/nm` | روزانه (logrotate) | لاگ‌های NM: ۱۴ نسخه، فشرده، `copytruncate` |
| `nm-ops.cron` | `/etc/cron.d/nm-ops` | — | زمان‌بندیِ بالا (نه در crontab ِ root که مالِ چغر/aaPanel است) |

زمان‌ها به وقتِ سرور (UTC)؛ تهران = UTC + ۳:۳۰.

## ۱) آزمون‌ها باید پس از خود پاک کنند

* هیچ آزمونی نباید `tempfile.mkdtemp()` را **در لحظهٔ import** (بالای فایل) بزند و پاک نکند. اگر پوشهٔ موقت می‌خواهید، در
  `setUp` / `setUpClass` بسازید و با `self.addCleanup(shutil.rmtree, path, ignore_errors=True)` یا `addClassCleanup`
  پاکش کنید؛ یا `tempfile.TemporaryDirectory()`.
* **تورِ ایمنی**: `config/test_runner.py` (`TEST_RUNNER` در settings) برای هر اجرا یک پوشهٔ `nm-testrun-<pid>-…` می‌سازد،
  `tempfile.tempdir` و `TMPDIR` را پیش از import ِ آزمون‌ها روی آن می‌گذارد و آخرِ اجرا (و با `atexit` اگر اجرا وسط بمیرد)
  همه‌اش را پاک می‌کند. پس حتی `mkdtemp()` ِ سطحِ ماژول هم دیگر در `/tmp` چیزی جا نمی‌گذارد. اجراهایی که با `kill -9` مردند را
  اجرای بعدیِ آزمون و `nm-tmp-sweep` ِ شبانه پاک می‌کنند. برای عیب‌یابی: `NM_KEEP_TEST_TMP=1`.
* آزمون‌ها بسته (hermetic) اجرا می‌شوند: زیرِ `manage.py test` فایل‌های `.env` / `.env.local` خوانده نمی‌شوند و
  `PUBLIC_BASE_URL`، `EMAIL_*` و `AI_API_*` مقدارِ ثابت دارند (هرگز تماسِ واقعی با Metis) و Redis هرگز سنجیده نمی‌شود
  (`CELERY_MODE_SOURCE = "test"`). `NM_DATA_DIR` و `MEDIA_ROOT` اگر صادر نشده باشند در پوشهٔ موقتِ اجرا می‌افتند؛ هیچ آزمونی دادهٔ زنده را نمی‌نویسد.

## ۲) بکاپ

`nm-backup` (از `/etc/cron.d/nm-ops`) در `/root/backups/nm-daily` می‌نویسد:

```
daily/<تاریخ-ساعت>/   ۷ نسخه: db.sqlite3  studio.sqlite3  studio-workspaces__<نام>__db.sqlite3   (با sqlite3 .backup)
                      data.tar.gz (audio_library, voice_clone, studio-workspaces, photoedit, mobile, up3d/uploads, up3d/asset-packs …)
                      config.tar.gz (backend/.env و deploy/nm/ai.env — راز؛ پوشه 700)   manifest.json
weekly/<سال-Wهفته>/   ۴ نسخه (یکشنبه‌ها؛ hard-link از daily)
media/<تاریخ>/        ۴ عکسِ لحظه‌ایِ backend/media (rsync --link-dest؛ بدونِ کش‌ها؛ فقط تغییرها فضا می‌گیرند)
status.json           «آخرین بکاپ» در صفحهٔ گزارشِ پنل (ابزارها ⇒ سرورِ پردازش ⇒ گزارش)
```

* بعد از هر بکاپ **آزمونِ بازیابی** انجام می‌شود: هر دیتابیس روی یک رونوشت باز می‌شود، `PRAGMA integrity_check` باید `ok` باشد
  و جدول‌ها هم باید باشند. فقط نسخهٔ سالم نگه داشته می‌شود. دستی: `nm-backup --verify [پوشه]`.
* اگر فضای آزادِ دیسک کمتر از ۱٫۵ گیگ باشد، مدیا رد می‌شود (دیتابیس‌ها همیشه گرفته می‌شوند).
* **بازگرداندن**: سرویس‌ها را متوقف کنید (`systemctl stop nm-web nm-celery nm-celery-node nm-celery-beat`)، فایلِ
  `daily/<…>/db.sqlite3` را به‌جای `data/db.sqlite3` بگذارید (فایل‌های `-wal` و `-shm` ِ قدیمی را پاک کنید)، سپس سرویس‌ها را بالا بیاورید.
* ⚠ **نسخهٔ بیرونی** (کپی روی کامپیوترِ دفتر) تصمیمِ مالک است و پیکربندی نشده؛ این بکاپ‌ها روی همان دیسکِ سرورند.

## ۳) نگهبان

`nm-watchdog` هر دو دقیقه `http://127.0.0.1:8041/healthz` را می‌سنجد؛ فقط بعد از **سه** شکستِ پشتِ‌هم `systemctl restart nm-web`
می‌زند (اگر `/root/nm-deploy.lock` در دستِ یک استقرار باشد آستانه ۶ است). فقط `nm-web` را لمس می‌کند؛ nginx (مشترک با چغر) و هیچ
سرویسِ دیگری را نه. لاگ: `/var/log/nm-watchdog.log`.

## ۴) استقرار: reload، نه restart

`systemctl restart nm-web` یعنی ۴ تا ۱۳ ثانیه 502/503 برای همهٔ کاربران (در سه روز ۲۸ بار؛ ۹۰ از ۱۰۶ خطای 502/503 در ۴۵ ثانیهٔ بعد از یک restart بودند).
`nm-web.service` حالا `ExecReload=/bin/kill -s HUP $MAINPID` دارد؛ gunicorn با preload اجرا نمی‌شود، پس HUP کارگرهای تازه (با کدِ تازه) را
بالا می‌آورد و قدیمی‌ها کارِ در دست را تمام می‌کنند:

```
nm-reload            # = systemctl reload nm-web + منتظرِ دو ۲۰۰ ِ پشتِ‌هم از /healthz
nm-reload --restart  # اگر reload جواب نداد، آخرین چاره restart
```

* **فقط کدِ پایتون/تنظیمات/URL عوض شد ⇒ `nm-reload`.**
* restart فقط وقتی لازم است که فایلِ unit یا نسخهٔ پایتون/venv عوض شده باشد.
* **به صاحبانِ اسکریپت‌های `/root/integrate-*.sh`:** در «Go live» به‌جای `systemctl restart nm-web nm-celery nm-celery-node` بنویسید
  `nm-reload; systemctl restart nm-celery nm-celery-node` (celery صفِ کارها را می‌کشد و کسی منتظرش نیست؛ restart اشکالی ندارد).
* ۴۰۴ ِ مسیرهای `/api/…` همیشه JSON فارسی است (`config/urls.py` ⇒ `api_not_found`)، چه `DEBUG` روشن باشد چه نه.
  ⚠ `.env` ِ سرور `DEBUG=false` دارد ولی `settings.py` متغیرِ `DJANGO_DEBUG` را می‌خواند (پیش‌فرض True)؛ **آن را روشن/خاموش نکنید**:
  با DEBUG=false باید `DJANGO_ALLOWED_HOSTS` هم تنظیم باشد وگرنه جنگو بالا نمی‌آید و سایت می‌خوابد.

## ۵) لاگ‌ها

* **چرخش**: `/etc/logrotate.d/nm` — `logs/celery.log`، `celery-node.log`، `beat.log`، `web-access.log`، `web-error.log` و
  `/www/wwwlogs/nm-8040.log` و `nm-8040.error.log`؛ روزانه، ۱۴ نسخه، فشرده، `copytruncate`. (لاگ‌های چغر دست نمی‌خورد.)
* **نویز**: خط‌های INFO ِ «Task … received/succeeded» برای تسک‌های هر‌چند‌دقیقه‌یک‌بار (از `CELERY_BEAT_SCHEDULE` با بازهٔ ≤ ۳۰ دقیقه) و
  پولرها (`poll_*`) حذف می‌شوند؛ WARNING و بالاتر و تسک‌های واقعی می‌مانند. `nm-celery-beat` با `--loglevel=WARNING` اجرا می‌شود.
* **خطاها دیرپا**: WARNING به بالا (با نشانی و شناسهٔ کاربر) در `logs/django-errors.log` (RotatingFileHandler، ۱۰ مگ × ۵) هم نوشته می‌شود؛
  ردِ خطاهای ۵۰۰ دیگر با journal ِ مشترک نمی‌پرد.
* **یک منطقهٔ زمانی**: لاگ‌های پایتون (django، celery) UTC با «Z» هستند؛ لاگ‌های nginx و journal هم UTC‌اند؛ `web-access.log` ِ gunicorn
  offset ِ خودش (`+0330`) را در هر خط می‌نویسد، پس هیچ خطی بی‌نشانه نیست.

## ۶) فایل‌های `*.bak*`

فایل‌های پشتیبانِ کنارِ کد (`*.bak-2026…`) نه به GitHub می‌روند و نه در درختِ زنده می‌مانند: `git-autopush.sh` آن‌ها و `frontend/dist.prev*` را
نمی‌فرستد، `.gitignore` هم دارد؛ تاریخچه در `/root/backups` است. فایل‌های `*.bak*` ِ بیش از یک روز از درختِ زنده پاک می‌شوند
(جوان‌تر از یک روز نه: ممکن است استقرارِ دیگری وسطِ کار باشد).

## ۷) آزمون‌های شبانه

`nm-nightly-tests` هر اپ را جدا (`manage.py test apps.<اپ>`) و پشتِ‌هم اجرا می‌کند؛ برای هر اپ جدا زیرِ `/root/nm-heavy.lock` با `nice -n 10`
(تا استقرارِ دیگران بینِ اپ‌ها گیر نکند). نتیجه در `data/test-report.json`؛ صفحهٔ «خودآزمایی» ِ پنل کارتِ «آزمون‌های شبانهٔ سایت» را
با فهرستِ آزمون‌های قرمز نشان می‌دهد. دستی: `NM_NIGHTLY_APPS="jobs customers" nm-nightly-tests`.

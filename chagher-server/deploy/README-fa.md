# چغر روی سرورِ مشترک (87.107.160.17، کنارِ ارکا و آپ‌مارکت)

| فایل | جایش روی سرور |
|---|---|
| `zz-chagher.conf` | `/www/server/panel/vhost/nginx/` (nginx ِ aaPanel؛ پیشوندِ zz تا tamouz پیش‌فرضِ 443 بماند) |
| `chagher-proxy.conf` | `/www/server/nginx/conf/` |
| `cheghar.service` | `/etc/systemd/system/` — gunicorn روی 127.0.0.1:8001، کاربر www |
| `chagher-watchdog.sh`, `chagher-backup.sh` | `/usr/local/bin/` — cron ِ root: هر ۲ دقیقه / هر شب ۳:۳۰ |

کد: `/www/wwwroot/Cheghar` (این پوشه). venv با پایتون 3.12 (`/opt/uv/python`) و `pip install -r` از نسخه‌های ثبت‌شده.
در گیت نیست: `db.sqlite3`، `media/` و `private_media/`، لاگ‌ها، `/etc/cheghar/cheghar.env` (رمزها)، `/etc/letsencrypt` (گواهی‌ها) — این‌ها در `/root/backups` ِ سرورند.
گواهی‌ها با certbot (webroot = /var/www/html) خودکار تمدید می‌شوند.

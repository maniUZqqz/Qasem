#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  بکاپِ شبانهٔ چغر — هر شب ۳:۳۰، هفت نسخهٔ آخر نگه داشته می‌شود.
#
#  مدیا (عکسِ حرکت‌ها، ۴۶۷ مگ) هر شب گرفته نمی‌شود چون تقریباً ثابت است؛
#  نسخهٔ کاملش یک‌بار گرفته شده. اگر خواستید دوباره:
#      tar -cf /root/backups/media-$(date +%F).tar -C /www/wwwroot/Cheghar/backend/gym media
#
#  برگرداندن: README-fa.txt داخلِ هر پوشهٔ بکاپ.
#  گزارش: /var/log/chagher-backup.log
# ═══════════════════════════════════════════════════════════════════════════
set -u
G=/www/wwwroot/Cheghar
LOG=/var/log/chagher-backup.log
KEEP=7
TS=$(date +%Y%m%d-%H%M)
B=/root/backups/chagher-$TS
say(){ echo "$(date '+%F %T') $*" >> $LOG; }

mkdir -p $B
say "──── شروع: $B"

# دیتابیس — روشِ امنِ sqlite، نه کپیِ خام (سایت در حالِ نوشتن است)
TMP=/tmp/chagher-bk-$$
mkdir -p $TMP && chmod 777 $TMP
if sudo -u www $G/backend/gym/venv/bin/python - "$TMP/db.sqlite3" <<'PY' >> $LOG 2>&1
import sqlite3, sys
s = sqlite3.connect('file:/www/wwwroot/Cheghar/backend/gym/db.sqlite3?mode=ro', uri=True)
d = sqlite3.connect(sys.argv[1])
with d: s.backup(d)
d.close(); s.close()
c = sqlite3.connect(sys.argv[1])
assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'integrity'
c.close()
PY
then
  mv $TMP/db.sqlite3 $B/db.sqlite3 && say "دیتابیس: ok ($(du -h $B/db.sqlite3 | cut -f1))"
else
  say "✗ دیتابیس گرفته نشد"
fi
rm -rf $TMP

tar -czf $B/code.tar.gz --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='media' --exclude='db.sqlite3*' -C $G backend/gym frontend/web 2>/dev/null \
  && say "کد: ok ($(du -h $B/code.tar.gz | cut -f1))"

tar -czf $B/config.tar.gz /www/server/panel/vhost/nginx/zz-chagher.conf \
    /www/server/nginx/conf/chagher-proxy.conf /etc/systemd/system/cheghar.service /etc/cheghar \
    /usr/local/bin/chagher-*.sh 2>/dev/null \
  && say "تنظیمات: ok"
crontab -l > $B/crontab.txt 2>/dev/null

cp -f /root/backups/README-fa.txt $B/ 2>/dev/null

# فقط KEEP نسخهٔ آخر بماند
ls -dt /root/backups/chagher-* 2>/dev/null | tail -n +$((KEEP+1)) | while read old; do
  rm -rf "$old"; say "پاک شد: $(basename $old)"
done

say "پایان — جمعِ بکاپ‌ها: $(du -sh /root/backups 2>/dev/null | cut -f1)"
[ -f $LOG ] && [ $(stat -c%s $LOG) -gt 1000000 ] && tail -300 $LOG > $LOG.t && mv $LOG.t $LOG
exit 0

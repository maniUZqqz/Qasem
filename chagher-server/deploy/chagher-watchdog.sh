#!/bin/bash
# نگهبانِ چغر — هر دو دقیقه سلامتِ بک‌اند را می‌سنجد و اگر پایین بود ری‌استارت می‌کند.
# روی سرورِ مشترک (ارکا + آپ‌مارکت + چغر): nginx ِ aaPanel است و systemd آن را «inactive» نشان می‌دهد،
# پس این‌جا nginx فقط وقتی بالا آورده می‌شود که اصلاً پروسه‌اش نباشد — هیچ‌وقت ری‌استارتِ بی‌دلیل (سایت‌های دیگر هم پشتِ همین nginx‌اند).
LOG=/var/log/chagher-watchdog.log
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:8001/ 2>/dev/null)
if [ "$CODE" != "200" ] && [ "$CODE" != "301" ] && [ "$CODE" != "302" ]; then
  echo "$(date '+%F %T') بک‌اند پاسخ نداد (کد $CODE) — ری‌استارت" >> $LOG
  systemctl restart cheghar.service
  sleep 8
  NEW=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:8001/ 2>/dev/null)
  echo "$(date '+%F %T') پس از ری‌استارت: $NEW" >> $LOG
fi
if ! pgrep -f "nginx: master" >/dev/null; then
  echo "$(date '+%F %T') nginx خوابیده بود — start" >> $LOG
  /etc/init.d/nginx start >> $LOG 2>&1
fi
[ -f $LOG ] && [ $(stat -c%s $LOG) -gt 2000000 ] && tail -500 $LOG > $LOG.tmp && mv $LOG.tmp $LOG
exit 0

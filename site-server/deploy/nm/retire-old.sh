#!/usr/bin/env bash
# بازنشستگیِ نسخه‌های مستقلِ قدیمی (سایت‌سازِ solo روی 8010/8020 و پنلِ 3D روی 8030)
# فقط بعد از این‌که سایتِ یکپارچه روی 8040 وارسی شد. ARKA (80/443/8000) دست نمی‌خورد.
set -u
RET=/var/www/NM/_retired
mkdir -p "$RET"
echo "== توقف و غیرفعال‌کردنِ سرویس‌های قدیمی"
for u in solo-main solo-studio up3d-web up3d-orchestrator up3d-worker; do
  systemctl stop $u 2>/dev/null; systemctl disable $u 2>/dev/null
  [ -f /etc/systemd/system/$u.service ] && mv /etc/systemd/system/$u.service "$RET/$u.service"
done
systemctl daemon-reload
echo "== nginx: حذفِ 8010/8020/8030"
for p in 8010 8020 8030; do
  f=/www/server/panel/vhost/nginx/port_$p.conf
  [ -f "$f" ] && mv "$f" "$RET/port_$p.conf"
done
/www/server/nginx/sbin/nginx -t 2>&1 | tail -1 && /www/server/nginx/sbin/nginx -s reload
echo "== پوشه‌ها ⇐ $RET"
[ -d /var/www/NM/solo ] && mv /var/www/NM/solo "$RET/solo"
[ -d /var/www/NM/3D ] && mv /var/www/NM/3D "$RET/3D"
[ -d /var/www/NM/3D-pack ] && mv /var/www/NM/3D-pack "$RET/3D-pack"
echo "== فایروال"
for p in 8010 8020 8030; do ufw delete allow $p/tcp >/dev/null 2>&1 || true; done
ufw status | grep -E "8010|8020|8030|8040|8601" || true
echo "تمام. پورت‌های 8601:8650 (پیش‌نمایشِ سایت‌ساز) باز مانده‌اند."

#!/usr/bin/env bash
# مدیریتِ UpMarket 3D روی سرور.   ./up3d.sh <فرمان>
#   install     venv، وابستگی‌ها، مهاجرت، فایل‌های ثابت، سرویس‌ها، nginx (پورت 8030)، فایروال
#   start|stop|restart|status
#   logs [web|orchestrator|worker]
#   admin <user> <pass>      ساخت/تغییرِ رمزِ مدیر
#   test                     آزمون‌های خودکار (هسته + API + یک رندرِ کوتاه)
#   bundle                   بستهٔ کارگرِ GPU (برای ویندوز/لینوکسِ دیگر) در data/bundle/
#   backup                   پشتیبانِ داده‌ها (دیتابیس + خروجی‌ها) در data/backups/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/venv"
DATA="$ROOT/data"
SERVICES="up3d-web up3d-orchestrator up3d-worker"
NGINX_VHOST_DIR="${NGINX_VHOST_DIR:-/www/server/panel/vhost/nginx}"
NGINX_BIN="${NGINX_BIN:-$( [ -x /www/server/nginx/sbin/nginx ] && echo /www/server/nginx/sbin/nginx || command -v nginx )}"
export UP3D_ROOT="$ROOT" UP3D_DATA="$DATA" PYTHONIOENCODING=utf-8
say() { echo -e "\n\033[1;33m== $*\033[0m"; }
manage() { (cd "$ROOT/web" && sudo -E -u www HOME="$DATA/home" "$VENV/bin/python" manage.py "$@"); }

cmd="${1:-help}"; shift || true
case "$cmd" in
install)
  say "۱) پایتون و وابستگی‌ها"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$ROOT/requirements.txt"
  say "۲) پوشه‌ها و مالکیت"
  mkdir -p "$DATA/home" "$DATA/jobs" "$DATA/uploads" "$DATA/cache" "$DATA/bundle" "$DATA/backups"
  chown -R www:www "$ROOT/data" "$ROOT/assets" "$ROOT/web" "$ROOT/vendor/blender-user"
  say "۳) فایل‌های ثابت (فونت، three.js)"
  ST="$ROOT/web/studio/static"
  mkdir -p "$ST/studio/fonts" "$ST/vendor/three/addons/loaders" "$ST/vendor/three/addons/controls" "$ST/vendor/three/addons/utils" "$ST/vendor/three/addons/environments"
  cp -f "$ROOT"/assets/fonts/Vazirmatn-*.ttf "$ST/studio/fonts/"
  T=https://cdn.jsdelivr.net/npm/three@0.160.0
  for f in build/three.module.js:three.module.js examples/jsm/loaders/GLTFLoader.js:addons/loaders/GLTFLoader.js \
           examples/jsm/controls/OrbitControls.js:addons/controls/OrbitControls.js \
           examples/jsm/utils/BufferGeometryUtils.js:addons/utils/BufferGeometryUtils.js \
           examples/jsm/environments/RoomEnvironment.js:addons/environments/RoomEnvironment.js; do
    src="${f%%:*}"; dst="$ST/vendor/three/${f##*:}"
    [ -s "$dst" ] || curl -sSL -m 120 -o "$dst" "$T/$src"
  done
  chown -R www:www "$ROOT/web"
  say "۴) دیتابیس و راه‌اندازیِ اولیه"
  manage migrate --noinput
  manage collectstatic --noinput -v 0
  manage ensure_setup
  say "۵) سرویس‌ها"
  for s in $SERVICES; do cp -f "$ROOT/deploy/$s.service" /etc/systemd/system/; done
  systemctl daemon-reload
  systemctl enable $SERVICES >/dev/null
  systemctl restart up3d-web up3d-orchestrator
  sleep 2
  systemctl restart up3d-worker
  say "۶) nginx (پورت 8030)"
  if [ -d "$NGINX_VHOST_DIR" ]; then
    cp -f "$ROOT/deploy/nginx-port_8030.conf" "$NGINX_VHOST_DIR/port_8030.conf"
    "$NGINX_BIN" -t && "$NGINX_BIN" -s reload
  else
    echo "پوشهٔ vhost ِ nginx نیست؛ deploy/nginx-port_8030.conf را دستی بگذارید."
  fi
  say "۷) فایروال"
  if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 8030/tcp >/dev/null; fi
  "$0" status
  ;;
start)   systemctl start $SERVICES ;;
stop)    systemctl stop $SERVICES ;;
restart) systemctl restart up3d-web up3d-orchestrator; sleep 1; systemctl restart up3d-worker ;;
status)
  for s in $SERVICES; do printf '%-22s %s\n' "$s" "$(systemctl is-active $s)"; done
  printf '%-22s %s\n' "http :8030" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8030/login/)"
  ;;
logs)    journalctl -u "up3d-${1:-web}" -n "${2:-80}" --no-pager ;;
admin)   manage ensure_setup --admin-user "$1" --admin-pass "$2" ;;
test)
  say "آزمون‌های هسته"
  (cd "$ROOT" && "$VENV/bin/python" -m unittest discover -s tests -p 'test_*.py' -v)
  ;;
bundle)
  say "بستهٔ کارگر"
  out="$DATA/bundle/up3d-worker-bundle.zip"
  rm -f "$out"
  (cd "$ROOT" && nice -n 19 zip -qr -1 "$out" up3d engine assets worker-windows requirements-worker.txt README.md \
      vendor/blender-user -x '*/__pycache__/*' -x 'assets/*/thumbnail.jpg' -x 'assets/*/preview.mp4')
  chown www:www "$out"
  ls -la "$out"
  ;;
backup)
  f="$DATA/backups/up3d-data-$(date +%Y%m%d-%H%M).tgz"
  (cd "$ROOT" && sqlite3 "$DATA/up3d.sqlite3" ".backup '$DATA/backups/db.sqlite3'" 2>/dev/null || cp "$DATA/up3d.sqlite3" "$DATA/backups/db.sqlite3")
  tar -czf "$f" -C "$ROOT" data/backups/db.sqlite3 data/uploads data/jobs --exclude='data/jobs/*/frames' --exclude='data/jobs/*/package.zip'
  ls -la "$f"
  ;;
*) sed -n '2,11p' "$0" ;;
esac

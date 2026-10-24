#!/usr/bin/env bash
# نصب/به‌روزرسانیِ NMarketing (UpMarket) روی سرورِ سایت — /var/www/NM/upmarket
# اجرا: bash deploy/nm/install.sh   (از ریشهٔ همین پوشه، به‌عنوانِ root)
# ایده‌مپوتنت: دوباره اجرا کردنش فقط چیزهای تازه را عوض می‌کند.
set -u
ROOT=/var/www/NM/upmarket
BE=$ROOT/backend
DATA=$ROOT/data
VENV=$ROOT/venv
PY=$VENV/bin/python
HOST_IP=${NM_HOST_IP:-87.107.160.17}
PORT=8040
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 NODE_OPTIONS=--max-old-space-size=2048

step() { echo; echo "==== $*"; }
die() { echo "!! $*" >&2; exit 1; }

cd "$ROOT" || die "پوشهٔ $ROOT نیست"

step "swap (۲ گیگ) برای ساختِ فرانت و سایت"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon --show

step "python venv + وابستگی‌ها"
[ -x "$PY" ] || python3 -m venv "$VENV"
"$PY" -m pip install -q --upgrade pip wheel >/dev/null
"$PY" -m pip install -q -r "$BE/requirements.txt" gunicorn >/dev/null || die "pip install"
# بسته‌های سایت‌ساز و سه‌بعدی (روی requirements اصلی)
"$PY" -m pip install -q openai pillow arabic-reshaper python-bidi requests >/dev/null || true
"$PY" -c "import django, rest_framework, celery, openai; print('django', django.get_version())"

step "موتورِ سه‌بعدی (up3d/engine/assets/vendor) ⇐ up3d-engine"
if [ ! -d "$ROOT/up3d-engine/up3d" ]; then
  mkdir -p "$ROOT/up3d-engine"
  SRC3D=/var/www/NM/3D
  [ -d /var/www/NM/_retired/3D ] && SRC3D=/var/www/NM/_retired/3D
  for d in up3d engine assets vendor worker-windows windows docs requirements-worker.txt README.md up3d.sh; do
    if [ -e "$SRC3D/$d" ]; then
      systemctl stop up3d-worker up3d-orchestrator 2>/dev/null
      mv "$SRC3D/$d" "$ROOT/up3d-engine/$d"
    fi
  done
fi
ls "$ROOT/up3d-engine" | tr '
' ' '; echo
# SDK ِ هسته: REST حالا زیرِ /api/v1/up3d/ است (پروتکلِ کارگر دست نمی‌خورد)
sed -i "s#'/api/v1/scenes/'#'/api/v1/up3d/scenes/'#; s#'/api/v1/scenes/%s/render/'#'/api/v1/up3d/scenes/%s/render/'#; s#'/api/v1/jobs/%s/'#'/api/v1/up3d/jobs/%s/'#" "$ROOT/up3d-engine/up3d/client.py"

step "ffmpeg (نسخهٔ ۶ به بالا با drawtext لازم است؛ اوبونتو ۴٫۴ می‌دهد)"
FFOK=$(/usr/local/bin/ffmpeg -hide_banner -filters 2>/dev/null | grep -c " drawtext ")
FFV=$(/usr/local/bin/ffmpeg -version 2>/dev/null | head -1 | grep -oE "version (N-|n?[0-9]+)" | grep -oE "N-|[0-9]+")
# stable n8.1 only: the BtbN "master" (N-...) build's AAC encoder loops forever on 44.1k mono m4a (1404/07/27)
if [ "${FFOK:-0}" -lt 1 ] || [ "$FFV" = "N-" ] || ! [ "${FFV:-0}" -ge 6 ] 2>/dev/null; then
  echo "  دانلودِ ffmpeg ایستای پایدار (BtbN n8.1، با drawtext) ..."
  if curl -sSL -m 900 -o /root/ff.tar.xz https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz \
     && mkdir -p /opt/ffmpeg-btbn-n8.1 && tar xJf /root/ff.tar.xz -C /opt/ffmpeg-btbn-n8.1 --strip-components=1; then
    ln -sf /opt/ffmpeg-btbn-n8.1/bin/ffmpeg /usr/local/bin/ffmpeg; ln -sf /opt/ffmpeg-btbn-n8.1/bin/ffprobe /usr/local/bin/ffprobe
  else
    echo "  !! دانلود از GitHub نشد؛ تلاش با johnvansickle 6.1"
    curl -sSL -m 900 -o /root/ff.tar.xz https://johnvansickle.com/ffmpeg/old-releases/ffmpeg-6.1-amd64-static.tar.xz \
      && mkdir -p /opt/ffmpeg-61 && tar xJf /root/ff.tar.xz -C /opt/ffmpeg-61 --strip-components=1 \
      && ln -sf /opt/ffmpeg-61/ffmpeg /usr/local/bin/ffmpeg && ln -sf /opt/ffmpeg-61/ffprobe /usr/local/bin/ffprobe \
      || echo "  !! ffmpeg ایستا نصب نشد؛ ویدیو ممکن است خطا بدهد"
  fi
  rm -f /root/ff.tar.xz
fi
/usr/local/bin/ffmpeg -version 2>/dev/null | head -1 || ffmpeg -version | head -1

step "پوشه‌های داده"
mkdir -p "$DATA/up3d" "$DATA/studio-workspaces" "$BE/media" "$BE/staticfiles" "$ROOT/logs"

step ".env تولید"
if [ ! -f "$BE/.env" ]; then
  SECRET=$("$PY" -c "from django.core.management.utils import get_random_secret_key as g; print(g())")
  REVAL=$("$PY" -c "import secrets; print(secrets.token_urlsafe(24))")
  sed -e "s|__SECRET_KEY__|$SECRET|" -e "s|__REVALIDATE__|$REVAL|" -e "s|__HOST__|$HOST_IP|g" \
      "$ROOT/deploy/nm/env.production" > "$BE/.env"
  chmod 600 "$BE/.env"
  echo "  .env ساخته شد"
else
  echo "  .env از قبل هست (دست نخورد)"
fi
# کلیدِ AI (Metis) از فایلِ جدا، اگر باشد
if [ -f "$ROOT/deploy/nm/ai.env" ] && ! grep -q '^AI_API_KEY=.\+' "$BE/.env"; then
  cat "$ROOT/deploy/nm/ai.env" >> "$BE/.env"
fi

step "migrations (compute/up3d تازه‌اند) + migrate هر دو دیتابیس"
cd "$BE"
"$PY" manage.py makemigrations compute up3d --noinput | tail -3
"$PY" manage.py migrate --noinput | tail -3
"$PY" manage.py migrate --database=studio --noinput | tail -3
"$PY" manage.py panel_seed

step "کاربرِ مدیر"
"$PY" manage.py shell -c "
import secrets, pathlib
from django.contrib.auth import get_user_model
U = get_user_model()
u, created = U.objects.get_or_create(username='admin', defaults={'is_staff': True, 'is_superuser': True, 'email': 'admin@localhost'})
f = pathlib.Path('$DATA/admin-password.txt')
if created or not f.exists():
    pw = secrets.token_urlsafe(10)
    u.is_staff = u.is_superuser = True
    u.set_password(pw); u.save()
    f.write_text(pw + '\n'); f.chmod(0o600)
    print('admin password written to', f)
else:
    print('admin exists; password in', f)
"

step "داده‌های قدیمیِ سه‌بعدی (اگر هنوز وارد نشده)"
OLD3D=/var/www/NM/3D/data
[ -d /var/www/NM/_retired/3D/data ] && OLD3D=/var/www/NM/_retired/3D/data
if [ -f "$OLD3D/up3d.sqlite3" ] && [ ! -f "$DATA/up3d/.imported" ]; then
  "$PY" manage.py up3d_import_legacy --db "$OLD3D/up3d.sqlite3"
  for d in jobs uploads bundle asset-packs thumbs; do
    [ -d "$OLD3D/$d" ] && [ ! -e "$DATA/up3d/$d" ] && cp -a "$OLD3D/$d" "$DATA/up3d/$d"
  done
  touch "$DATA/up3d/.imported"
fi

step "سرورهای پردازش: gpu-1 و gpu-2 (توکن در data/compute-nodes.txt)"
"$PY" manage.py shell -c "
from apps.compute.models import ComputeNode
import pathlib
lines = []
for name in ('gpu-1', 'gpu-2'):
    n, _ = ComputeNode.objects.get_or_create(name=name)
    lines.append(f'{name}\t{n.token}')
f = pathlib.Path('$DATA/compute-nodes.txt'); f.write_text('\n'.join(lines) + '\n'); f.chmod(0o600)
print(open(f).read())
"

step "کارگرِ CPU ِ سه‌بعدی روی همین سرور (server-cpu)"
"$PY" manage.py up3d_setup --local-worker server-cpu | tail -1
TOK=$(cat "$DATA/up3d/local-worker.token" 2>/dev/null || true)
[ -n "$TOK" ] && printf 'UP3D_WORKER_TOKEN=%s
' "$TOK" > "$DATA/up3d-worker.env" && chmod 600 "$DATA/up3d-worker.env"

step "collectstatic"
"$PY" manage.py collectstatic --noinput | tail -1

step "فرانت (پنل) — npm ci + build"
cd "$ROOT/frontend"
# قفلِ بسته‌ها ممکن است با package.json ناهمگام باشد (three برای نمایشگرِ سه‌بعدی) ⇐ npm install
npm ci --no-audit --no-fund --loglevel=error 2>/dev/null || npm install --no-audit --no-fund --loglevel=error || die "npm install frontend"
npm run build 2>&1 | tail -5
[ -f dist/index.html ] || die "frontend build"

step "سایتِ عمومی (Next.js) — build standalone"
cd "$ROOT/website"
cat > .env.production.local <<EOF
NEXT_PUBLIC_API_BASE=http://127.0.0.1:$PORT
NEXT_PUBLIC_PANEL_URL=http://$HOST_IP:$PORT/panel
NEXT_PUBLIC_SITE_URL=http://$HOST_IP:$PORT
REVALIDATE_SECRET=$(grep '^WEBSITE_REVALIDATE_SECRET=' "$BE/.env" | cut -d= -f2-)
EOF
npm ci --no-audit --no-fund --loglevel=error 2>/dev/null || npm install --no-audit --no-fund --loglevel=error || die "npm install website"
npm run build 2>&1 | tail -5
[ -f .next/standalone/server.js ] || die "website build"
# standalone به static و public نیاز دارد
rm -rf .next/standalone/.next/static && cp -r .next/static .next/standalone/.next/static
rm -rf .next/standalone/public && cp -r public .next/standalone/public
# فونت‌های تصویرِ اشتراک‌گذاری (opengraph-image) — بی آن /en/opengraph-image خطای 500 می‌داد (۱۴۰۵/۰۸/۰۲)
[ -d assets ] && { rm -rf .next/standalone/assets && cp -r assets .next/standalone/assets; }

step "systemd"
for u in nm-web nm-celery nm-celery-beat nm-website nm-up3d-orchestrator nm-up3d-worker; do
  cp "$ROOT/deploy/nm/$u.service" /etc/systemd/system/$u.service
done
systemctl daemon-reload
systemctl enable nm-web nm-celery nm-celery-beat nm-website nm-up3d-orchestrator nm-up3d-worker >/dev/null 2>&1
systemctl restart nm-web nm-celery nm-celery-beat nm-website nm-up3d-orchestrator nm-up3d-worker

step "nginx :$PORT"
cp "$ROOT/deploy/nm/nginx-port_8040.conf" /www/server/panel/vhost/nginx/port_8040.conf
/www/server/nginx/sbin/nginx -t 2>&1 | tail -1 && /www/server/nginx/sbin/nginx -s reload
ufw allow $PORT/tcp >/dev/null 2>&1 || true

step "وضعیت"
sleep 3
for u in nm-web nm-celery nm-celery-beat nm-website nm-up3d-orchestrator nm-up3d-worker; do
  printf '  %-22s %s\n' "$u" "$(systemctl is-active $u)"
done
curl -s -o /dev/null -w "  /healthz  → %{http_code}\n" http://127.0.0.1:$PORT/healthz
curl -s -o /dev/null -w "  /panel/   → %{http_code}\n" http://127.0.0.1:$PORT/panel/
curl -s -o /dev/null -w "  /         → %{http_code}\n" http://127.0.0.1:$PORT/
curl -s -o /dev/null -w "  /panel/tools/studio → %{http_code}\n" http://127.0.0.1:$PORT/panel/tools/studio
curl -s -o /dev/null -w "  /panel/tools/3d → %{http_code}\n" http://127.0.0.1:$PORT/panel/tools/3d
curl -s -o /dev/null -w "  /panel/tools/compute → %{http_code}\n" http://127.0.0.1:$PORT/panel/tools/compute
echo "تمام. پنل: http://$HOST_IP:$PORT/panel/  — رمزِ admin در $DATA/admin-password.txt"

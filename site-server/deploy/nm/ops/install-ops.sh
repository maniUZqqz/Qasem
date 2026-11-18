#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  install-ops.sh — نصبِ ابزارهای عملیاتِ سرور (idempotent؛ چندبار اجرا شود مشکلی نیست)
#
#   اسکریپت‌ها      ⇒ /usr/local/bin/  (nm-tmp-sweep nm-reload nm-backup nm-watchdog nm-nightly-tests)
#   logrotate       ⇒ /etc/logrotate.d/nm   (با «logrotate -d» اعتبارسنجی می‌شود؛ خراب بود نصب نمی‌شود)
#   cron            ⇒ /etc/cron.d/nm-ops    (نه crontab ِ root: آن مالِ چغر/aaPanel است)
#   unitهای systemd ⇒ فقط اگر deploy/nm/*.service با نسخهٔ نصب‌شده فرق داشت (daemon-reload؛ ری‌استارت نمی‌کند)
#
#  چیزی را ری‌استارت نمی‌کند. خروجی می‌گوید کدام سرویس برای اثرگرفتنِ تغییرِ unit باید ری‌استارت شود:
#     nm-web: فقط ExecReload اضافه شده ⇒ ری‌استارت لازم نیست.   nm-celery-beat: --loglevel ⇒ یک ری‌استارتِ بی‌خطر.
#  استفاده:   bash deploy/nm/ops/install-ops.sh [--check]     (--check = فقط می‌گوید چه عوض می‌شود)
# ═══════════════════════════════════════════════════════════════════════════
set -eu
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
NMDIR=$(dirname "$HERE")
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1
BIN="${NM_OPS_BIN:-/usr/local/bin}"
SYSTEMD="${NM_OPS_SYSTEMD:-/etc/systemd/system}"
LOGROTATE_D="${NM_OPS_LOGROTATE_D:-/etc/logrotate.d}"
CRON_D="${NM_OPS_CRON_D:-/etc/cron.d}"
changed=()

put() {  # put <src> <dst> <mode>  — فقط اگر فرق داشت می‌نویسد؛ CRLF را می‌زداید
  local src="$1" dst="$2" mode="$3" tmp
  tmp=$(mktemp)
  sed 's/\r$//' "$src" > "$tmp"
  if [ -f "$dst" ] && cmp -s "$tmp" "$dst"; then rm -f "$tmp"; return 1; fi
  if [ "$CHECK" = "1" ]; then rm -f "$tmp"; changed+=("$dst (would change)"); return 0; fi
  install -m "$mode" "$tmp" "$dst"; rm -f "$tmp"
  changed+=("$dst"); return 0
}

for s in nm-tmp-sweep nm-reload nm-backup nm-watchdog nm-nightly-tests; do
  put "$HERE/$s" "$BIN/$s" 755 || true
done

# «دامنه + SSL»: /root/nm-domain.sh ⇒ deploy/nm/nm-domain.sh (symlink؛ خودِ اسکریپت کنارِ nm_domain.py می‌ماند)
if [ -f "$NMDIR/nm-domain.sh" ]; then
  link="${NM_DOMAIN_LINK:-/root/nm-domain.sh}"
  if [ "$(readlink "$link" 2>/dev/null)" != "$NMDIR/nm-domain.sh" ]; then
    if [ "$CHECK" = "1" ]; then changed+=("$link (would link)"); else ln -sfn "$NMDIR/nm-domain.sh" "$link"; chmod +x "$NMDIR/nm-domain.sh"; changed+=("$link"); fi
  fi
fi

# logrotate: اول اعتبارسنجی
if [ -f "$HERE/nm-logrotate.conf" ]; then
  if command -v logrotate >/dev/null 2>&1 && ! logrotate -d -s /tmp/nm-logrotate-check.state "$HERE/nm-logrotate.conf" >/dev/null 2>&1; then
    echo "install-ops: nm-logrotate.conf نامعتبر است؛ نصب نشد" >&2
  else
    put "$HERE/nm-logrotate.conf" "$LOGROTATE_D/nm" 644 || true
  fi
  rm -f /tmp/nm-logrotate-check.state
fi

[ -f "$HERE/nm-ops.cron" ] && { put "$HERE/nm-ops.cron" "$CRON_D/nm-ops" 644 || true; }

# unitهای systemd: فقط دو ویرایشِ هدفمند روی نسخهٔ نصب‌شده (نه جایگزینیِ کلِ فایل؛ تا تغییراتِ دستیِ دیگران نپرد)
reload=0
patch_unit() {  # patch_unit <unit> <python-snippet> — فایل را می‌خواند، تغییر می‌دهد، فقط اگر فرق کرد می‌نویسد
  local unit="$SYSTEMD/$1" before after
  [ -f "$unit" ] || return 0
  before=$(cat "$unit")
  after=$(python3 -c "import sys; t=sys.stdin.read(); $2; sys.stdout.write(t)" < "$unit")
  if [ "$before" != "$after" ]; then
    if [ "$CHECK" = "1" ]; then changed+=("$unit (would change)"); return 0; fi
    printf '%s\n' "$after" > "$unit"; changed+=("$unit"); reload=1; echo "unit عوض شد: $1"
  fi
}
# nm-web: ری‌لودِ بی‌وقفه (systemctl reload nm-web ⇒ HUP ِ gunicorn)
patch_unit nm-web.service "import re; t = t if re.search(r'(?m)^ExecReload=', t) else re.sub(r'(?m)^(ExecStart=.*)$', lambda m: m.group(1) + chr(10) + 'ExecReload=/bin/kill -s HUP \$MAINPID', t, count=1)"
# nm-celery-beat: هر دقیقه یک خطِ «Scheduler: Sending due task» نوشتنش لازم نیست
patch_unit nm-celery-beat.service "t = t.replace('--loglevel=INFO', '--loglevel=WARNING')"
if [ "$reload" = "1" ] && [ "$CHECK" = "0" ] && [ "${NM_OPS_NO_SYSTEMCTL:-0}" != "1" ] && command -v systemctl >/dev/null 2>&1; then systemctl daemon-reload; fi

if [ "${#changed[@]}" -eq 0 ]; then echo "install-ops: همه‌چیز از قبل به‌روز است"; else printf 'install-ops: %s\n' "${changed[@]}"; fi
exit 0

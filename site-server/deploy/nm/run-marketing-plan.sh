#!/usr/bin/env bash
# بعد از استقرارِ «برنامهٔ بازاریابی»: پلن را برای یک فروشگاه می‌سازد و اجرا می‌کند (تکرارپذیر؛ هیچ‌چیز منتشر یا فرستاده نمی‌شود).
#   bash deploy/nm/run-marketing-plan.sh          # فروشگاهِ «چغر» (نامش «چغر» دارد)
#   bash deploy/nm/run-marketing-plan.sh 34       # فروشگاه با این شناسه
#   bash deploy/nm/run-marketing-plan.sh 34 --restart   # شروع را به فردا ببر و زمان‌ها را تازه کن
# کارهای سرورِ پردازش (GPU) در صفِ ماندگار می‌مانند و با روشن‌شدنِ گره خودشان اجرا می‌شوند؛ تیکِ ده‌دقیقه‌ایِ Celery وضعیت‌ها را تازه می‌کند.
set -u
NM_ROOT="${NM_ROOT:-/var/www/NM/upmarket}"
cd "$NM_ROOT/backend" || exit 1
PY="$NM_ROOT/venv/bin/python"
if [ "${1:-}" != "" ] && [ "${1#-}" = "$1" ]; then
  WHO=(--store "$1"); shift
else
  WHO=(--name "چغر")
fi
"$PY" -X utf8 manage.py migrate --noinput 2>&1 | tail -3
"$PY" -X utf8 manage.py marketing_plan_run "${WHO[@]}" "$@" 2>&1 | tail -80
echo "---- وضعیتِ کنونی ----"
"$PY" -X utf8 manage.py marketing_plan_run "${WHO[@]}" --report 2>&1 | head -12

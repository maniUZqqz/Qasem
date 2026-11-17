#!/usr/bin/env bash
# نصب/به‌روزرسانیِ آنچه «تصویر به کد» (apps/img2code) لازم دارد — ایده‌مپوتنت، می‌شود هر چند بار اجرا کرد؛ install.sh هم آن را صدا می‌زند.
#
#   bash deploy/nm/install-img2code.sh            (به‌عنوانِ root، از هر جا)
#
# چه چیزی نصب می‌شود (هیچ torch و هیچ مدلِ سنگینی نیست):
#   1) apt:  tesseract-ocr + tesseract-ocr-fas + tesseract-ocr-eng   (خواندنِ متنِ فارسی/انگلیسیِ تصویرِ بارگذاری‌شده؛ ~۴۰ مگ)
#   2) pip (در venv ِ خودِ NM):  mv2code (پین‌شده به commit ِ c8029ba = برچسبِ v2.0.0 از مخزنِ Machine-vision-TO-code)، pytesseract، playwright (فقط پایتونش؛ مرورگر دانلود نمی‌شود)
#      mv2code اول از چرخِ همراهِ همین مخزن (deploy/nm/wheels/، بدونِ اینترنت) نصب می‌شود؛ نشد از GitHub با همان commit.
#   3) مرورگرِ بی‌سر: همان chrome-headless-shell ِ موجود (/opt/up3d-uitest/browsers/…، یا $MV2CODE_CHROME) — دانلودِ تازه‌ای لازم نیست.
# در پایان یک «probe» می‌زند و می‌گوید چه چیزی آماده است؛ کدِ خروج ۰ یعنی همه‌چیز آماده است.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${NM_ROOT:-/var/www/NM/upmarket}"
VENV="${NM_VENV:-$ROOT/venv}"
PY="$VENV/bin/python"
REQ="$HERE/requirements-img2code.txt"
WHEEL="$(ls "$HERE"/wheels/mv2code-*.whl 2>/dev/null | head -1)"
export PYTHONIOENCODING=utf-8
step() { echo; echo "==== $*"; }
warn() { echo "!! $*" >&2; }
rc=0

[ -x "$PY" ] || { warn "venv ِ $VENV پیدا نشد؛ اول deploy/nm/install.sh"; exit 2; }

step "Tesseract (فارسی + انگلیسی)"
if ! command -v tesseract >/dev/null 2>&1 || ! tesseract --list-langs 2>/dev/null | grep -qx fas || ! tesseract --list-langs 2>/dev/null | grep -qx eng; then
  if command -v apt-get >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q tesseract-ocr tesseract-ocr-fas tesseract-ocr-eng >/dev/null 2>&1 \
      || { apt-get update -q >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -q tesseract-ocr tesseract-ocr-fas tesseract-ocr-eng >/dev/null 2>&1; } \
      || { warn "نصبِ tesseract با apt نشد"; rc=1; }
  else
    warn "apt-get نیست؛ tesseract-ocr با زبان‌های fas و eng را دستی نصب کنید"; rc=1
  fi
fi
tesseract --list-langs 2>/dev/null | tr '\n' ' '; echo

step "بسته‌های پایتون (pytesseract، playwright، mv2code)"
pinned_mv2code() { grep -E '^mv2code' "$REQ" | head -1; }
have_mv2code() { "$PY" - <<'PYEOF'
import sys
try:
    import mv2code
except Exception:
    sys.exit(1)
sys.exit(0 if mv2code.__version__ == "2.0.0" else 1)
PYEOF
}
"$PY" -m pip install -q --disable-pip-version-check "pytesseract==0.3.13" "playwright==1.63.0" >/dev/null 2>&1 || { warn "نصبِ pytesseract/playwright نشد"; rc=1; }
if have_mv2code; then
  echo "mv2code 2.0.0 از قبل هست"
else
  if [ -n "$WHEEL" ] && "$PY" -m pip install -q --disable-pip-version-check --no-deps "$WHEEL" >/dev/null 2>&1; then
    echo "mv2code از چرخِ همراه نصب شد: $(basename "$WHEEL")"
  elif "$PY" -m pip install -q --disable-pip-version-check --no-deps "$(pinned_mv2code | sed 's/^mv2code *@ *//')" >/dev/null 2>&1; then
    echo "mv2code از GitHub (commit ِ پین‌شده) نصب شد"
  else
    warn "mv2code نصب نشد (نه چرخ، نه GitHub)"; rc=1
  fi
  # وابستگی‌های سبکش (numpy، opencv headless، Pillow) معمولاً هست؛ اگر نبود نصب کن
  "$PY" -m pip install -q --disable-pip-version-check "numpy>=1.24" "opencv-python-headless>=4.8" "Pillow>=10.0" >/dev/null 2>&1 || true
fi

step "وارسی (probe)"
cd "$ROOT/backend" 2>/dev/null || cd "$HERE/../../backend" || exit 2
OUT="$("$PY" -m apps.img2code.runner probe 2>&1 | grep '^RESULT ' | tail -1)"
echo "${OUT:-بدونِ خروجی}"
for want in '"mv2code": "2.0.0"' '"pytesseract": true' '"fas": true' '"playwright": true'; do
  echo "$OUT" | grep -q "$want" || { warn "آماده نیست: $want"; rc=1; }
done
echo "$OUT" | grep -q '"chrome": null' && { warn "chrome-headless-shell پیدا نشد؛ گرفتنِ عکس از نشانی و تصویرِ مقایسه کار نمی‌کند (MV2CODE_CHROME را بگذارید)"; rc=1; }
[ $rc -eq 0 ] && echo "همه‌چیز آماده است" || echo "بعضی چیزها آماده نیست (بالا را ببینید)"
exit $rc

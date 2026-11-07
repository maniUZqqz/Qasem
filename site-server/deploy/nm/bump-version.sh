#!/usr/bin/env bash
# بالا بردنِ شمارهٔ نسخهٔ NMarketing:  2.60 → 2.61   و   2.99 → 3.00
#
#   bash deploy/nm/bump-version.sh                 همین حالا یک نسخه بالا ببر (دستی: nm.sh bump)
#   bash deploy/nm/bump-version.sh --if-changed    فقط اگر کدِ پروژه از آخرین بار عوض شده (install.sh و autopush)
#   bash deploy/nm/bump-version.sh --dry-run       فقط بگو چه می‌کردی، چیزی ننویس
#   bash deploy/nm/bump-version.sh --show          نسخهٔ فعلی را چاپ کن
#   --quiet                                        خروجی نده
#
# می‌نویسد:  <ریشه>/VERSION  و  <ریشه>/build.json  ({"version","built_at","commit"})
#
# قاعده‌ها:
#  • هرگز نمی‌شکند و همیشه با کدِ ۰ برمی‌گردد — این فایل داخلِ install.sh و git-autopush.sh
#    صدا زده می‌شود و یک شمارهٔ نسخه نباید استقرار یا پشتیبان‌گیری را بخواباند.
#  • --if-changed انگشت‌نگارِ درختِ پروژه را (مسیر + اندازه + زمانِ تغییرِ فایل‌ها، نه محتوا؛
#    پس روی ۱٫۶ گیگِ up3d-engine هم در کسری از ثانیه تمام می‌شود) با انگشت‌نگارِ دفعهٔ قبل
#    مقایسه می‌کند. autopush ای که چیزی عوض نشده، نسخه را بالا نمی‌برد.
#    اولین اجرا (انگشت‌نگارِ قبلی نیست) فقط خط‌مبنا را ثبت می‌کند و نسخه را عوض نمی‌کند.
#  • VERSION و build.json و .env و *.bak* و داده‌ها در انگشت‌نگار نیستند؛ خودِ bump آن را عوض نمی‌کند.
#  • کامیت: `git -C /root/qasem-repo rev-parse --short HEAD` اگر شد، وگرنه "".
#
# متغیرهای محیطی (برای آزمون): NM_ROOT (پیش‌فرض: دو پوشه بالاتر از همین فایل)،
# NM_VERSION_REPO (پیش‌فرض /root/qasem-repo)، NM_VERSION_STATE (پیش‌فرض <ریشه>/data).
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
ROOT="${NM_ROOT:-$(cd "$SELF_DIR/../.." 2>/dev/null && pwd)}"
REPO="${NM_VERSION_REPO:-/root/qasem-repo}"
STATE_DIR="${NM_VERSION_STATE:-$ROOT/data}"
HASH_FILE="$STATE_DIR/.version-tree-hash"
VERSION_FILE="$ROOT/VERSION"
BUILD_FILE="$ROOT/build.json"
INITIAL="2.60"

IF_CHANGED=0; DRY=0; QUIET=0; SHOW=0
for a in "$@"; do
  case "$a" in
    --if-changed) IF_CHANGED=1 ;;
    --dry-run)    DRY=1 ;;
    --quiet|-q)   QUIET=1 ;;
    --show)       SHOW=1 ;;
    *) ;;
  esac
done

say() { [ "$QUIET" = 1 ] || echo "$*"; }

read_version() {
  [ -r "$VERSION_FILE" ] || return 0
  head -n 1 "$VERSION_FILE" 2>/dev/null | tr -d ' \t\r\n'
}

# انگشت‌نگارِ درخت: مسیر + اندازه + ثانیهٔ تغییر. چیزِ بیرون‌ازکد (داده، لاگ، بیلد، وابستگی) نیست.
tree_hash() {
  command -v sha1sum >/dev/null 2>&1 || return 0
  [ -d "$ROOT" ] || return 0
  ( cd "$ROOT" 2>/dev/null || exit 0
    find . \( -name .git -o -name node_modules -o -name __pycache__ -o -name venv \
              -o -path ./data -o -path ./logs -o -path ./models -o -path ./server-state \
              -o -path ./backend/media -o -path ./backend/staticfiles \
              -o -path './frontend/dist*' -o -path ./website/.next \
              -o -path ./up3d-engine/vendor -o -path ./up3d-engine/data \
              -o -path ./processing/work -o -path ./processing/logs -o -path ./processing/vendor \) -prune -o \
         -type f ! -name '*.pyc' ! -name '*.log' ! -name '*.sqlite3' ! -name '*.bak*' ! -name '*.tmp' \
         ! -name '.env' ! -name '.env.local' ! -name '.env.production.local' ! -name ai.env \
         ! -name node.json ! -name VERSION ! -name build.json ! -name '.VERSION.tmp.*' \
         -printf '%p\t%s\t%Ts\n' 2>/dev/null \
      | LC_ALL=C sort | sha1sum | cut -d' ' -f1 )
}

if [ "$SHOW" = 1 ]; then
  cur="$(read_version)"
  echo "${cur:-نامعلوم}"
  exit 0
fi

if [ ! -d "$ROOT" ]; then
  say "bump-version: پوشهٔ $ROOT نیست — کاری نشد"
  exit 0
fi

# قفل: install.sh و autopush ممکن است هم‌زمان بیایند
if command -v flock >/dev/null 2>&1 && mkdir -p "$STATE_DIR" 2>/dev/null; then
  { exec 9>"$STATE_DIR/.version-bump.lock"; } 2>/dev/null && flock -w 20 9 2>/dev/null
fi

cur="$(read_version)"
new=""
if [ -z "$cur" ]; then
  new="$INITIAL"                     # VERSION نیست: نسخهٔ اول
elif printf '%s' "$cur" | grep -Eq '^[0-9]{1,3}\.[0-9]{2}$'; then
  :
else
  say "bump-version: محتوای VERSION («$cur») قالبِ بزرگ.کوچک ندارد — دست نخورد"
  exit 0
fi

hash_now=""
if [ "$IF_CHANGED" = 1 ] || [ "$DRY" = 0 ]; then
  hash_now="$(tree_hash)"
fi

if [ -n "$cur" ] && [ "$IF_CHANGED" = 1 ]; then
  if [ -z "$hash_now" ]; then
    say "bump-version: انگشت‌نگار ساخته نشد — نسخه عوض نشد ($cur)"
    exit 0
  fi
  hash_old="$(cat "$HASH_FILE" 2>/dev/null | tr -d ' \t\r\n')"
  if [ -z "$hash_old" ]; then
    if [ "$DRY" = 1 ]; then
      say "bump-version(dry): خط‌مبنا ثبت می‌شد؛ نسخه همان $cur می‌ماند"
      exit 0
    fi
    mkdir -p "$STATE_DIR" 2>/dev/null && printf '%s\n' "$hash_now" > "$HASH_FILE" 2>/dev/null
    say "bump-version: خط‌مبنا ثبت شد؛ نسخه همان $cur می‌ماند"
    # build.json نیست؟ بسازش تا نشان تاریخ داشته باشد
    if [ ! -f "$BUILD_FILE" ]; then new="$cur"; else exit 0; fi
  elif [ "$hash_old" = "$hash_now" ]; then
    say "bump-version: چیزی عوض نشده — نسخه همان $cur"
    exit 0
  fi
fi

if [ -n "$cur" ] && [ -z "$new" ]; then
  major="${cur%%.*}"; minor="${cur#*.}"
  major=$((10#$major)); minor=$((10#$minor + 1))
  if [ "$minor" -gt 99 ]; then major=$((major + 1)); minor=0; fi
  new="$(printf '%d.%02d' "$major" "$minor")"
fi

if [ "$DRY" = 1 ]; then
  say "bump-version(dry): ${cur:-—} → $new"
  exit 0
fi

commit=""
if command -v git >/dev/null 2>&1 && [ -d "$REPO/.git" ]; then
  commit="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null | head -n 1 | tr -cd '0-9a-f' | cut -c1-12)"
fi
built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

write_atomic() {   # write_atomic <مقصد> <متن>
  local tmp="$ROOT/.VERSION.tmp.$$"
  if printf '%s\n' "$2" > "$tmp" 2>/dev/null && mv -f "$tmp" "$1" 2>/dev/null; then
    return 0
  fi
  rm -f "$tmp" 2>/dev/null
  return 1
}

if write_atomic "$VERSION_FILE" "$new" \
   && write_atomic "$BUILD_FILE" "{\"version\": \"$new\", \"built_at\": \"$built_at\", \"commit\": \"$commit\"}"; then
  if [ -n "$hash_now" ]; then
    mkdir -p "$STATE_DIR" 2>/dev/null && printf '%s\n' "$hash_now" > "$HASH_FILE" 2>/dev/null
  fi
  if [ -z "$cur" ] || [ "$cur" = "$new" ]; then
    say "bump-version: نسخهٔ $new نوشته شد"
  else
    say "bump-version: $cur → $new"
  fi
else
  say "bump-version: نوشتن در $ROOT نشد (دسترسی؟) — نسخه عوض نشد"
fi
exit 0

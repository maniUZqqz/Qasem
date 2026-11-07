# -*- coding: utf-8 -*-
"""نسخهٔ نرم‌افزار — یک منبعِ حقیقت: فایل `VERSION` کنارِ ریشهٔ پروژه.

چه چیزهایی کنار هم‌اند
=======================

    VERSION            فقط یک خط: `2.60`  (بزرگ.کوچک؛ کوچک همیشه دو رقم)
    build.json         {"version", "built_at", "commit"} — `deploy/nm/bump-version.sh` می‌نویسد
    CHANGELOG-fa.md    «چه چیزی تازه است» به فارسی؛ هر نسخه یک تیترِ `## v2.60 — ۱۴۰۵/۰۸/۱۶`

این ماژول فقط می‌خواند، هرگز نمی‌نویسد، و هرگز خطا نمی‌دهد: فایلی که نیست یا
خراب است یعنی «نسخه نامعلوم» (رشتهٔ خالی) و «فهرستِ تغییراتِ خالی». نشانِ نسخه
یک چیزِ تزئینی است؛ نباید بتواند صفحهٔ ورود یا ادمین را بشکند.

خواندنِ فایل‌ها با کلیدِ (زمانِ تغییر، اندازه) در حافظهٔ پردازه نگه داشته می‌شود،
پس درخواست‌های پشت‌سرهم دیسک را لمس نمی‌کنند و با `bump-version.sh` همان لحظه
تازه می‌شوند.

مسیر: پیش‌فرض ریشهٔ پروژه (دو پوشه بالاتر از backend/)؛ برای آزمون و استقرارِ
غیرمعمول با متغیرِ محیطی `NM_VERSION_DIR` عوض می‌شود. این متغیر در *هر* فراخوانی
خوانده می‌شود، نه هنگامِ import.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import threading
from pathlib import Path

NAME = "NMarketing"
VERSION_FILE = "VERSION"
BUILD_FILE = "build.json"
CHANGELOG_FILE = "CHANGELOG-fa.md"

# سقف‌ها: فایلِ عجیب‌وغریب نباید حافظه یا پاسخ را باد کند
MAX_FILE_BYTES = 256 * 1024
MAX_ENTRIES = 200
MAX_ITEMS = 100
MAX_ITEM_CHARS = 600

_VERSION_RE = re.compile(r"^(\d{1,3})\.(\d{2,3})$")
_BUILT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]{5,16}(Z|[+-]\d{2}:?\d{2})?$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")
# رقم‌های فارسی و عربی ⇒ لاتین؛ «٫» (ممیزِ عربی) ⇒ «.»
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")

_lock = threading.Lock()
_cache: dict = {}


# ---------------------------------------------------------------- مسیر و کش

def root_dir() -> Path:
    env = os.environ.get("NM_VERSION_DIR", "").strip()
    if env:
        return Path(env)
    # backend/apps/common/versioning.py ⇒ ریشهٔ پروژه سه پوشه بالاتر است
    return Path(__file__).resolve().parents[3]


def _stat(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _cached(name: str, paths: list[Path], loader):
    """نتیجهٔ `loader()` را تا وقتی فایل‌ها عوض نشده‌اند نگه می‌دارد."""
    key = (name, tuple(str(p) for p in paths))
    stamp = tuple(_stat(p) for p in paths)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == stamp:
            return copy.deepcopy(hit[1])
    try:
        value = loader()
    except Exception:  # noqa: BLE001 — هیچ خطایی از این ماژول بیرون نمی‌رود
        value = None
    with _lock:
        _cache[key] = (stamp, value)
    return copy.deepcopy(value)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _read_text(path: Path) -> str:
    with open(path, "rb") as fh:
        raw = fh.read(MAX_FILE_BYTES)
    return raw.decode("utf-8-sig", errors="replace")


# ---------------------------------------------------------------- نسخه

def clean_version(value) -> str:
    """`"2.60"` ⇒ `"2.60"`؛ هر چیزِ دیگر (خالی، متنِ خراب، `2.6`) ⇒ `""`."""
    if not isinstance(value, str):
        return ""
    text = value.strip().translate(_DIGITS)
    if text[:1] in ("v", "V"):
        text = text[1:].strip()
    return text if _VERSION_RE.match(text) else ""


def read_version() -> str:
    path = root_dir() / VERSION_FILE

    def load():
        return clean_version(_read_text(path).strip().splitlines()[0]) if path.exists() else ""

    return _cached("version", [path], load) or ""


def _iso_from_mtime(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, ValueError, OverflowError):
        return ""


def read_build() -> dict:
    """{"version", "built_at", "commit", "name"} — همیشه یک دیکشنری با همین چهار کلید."""
    d = root_dir()
    vpath, bpath = d / VERSION_FILE, d / BUILD_FILE

    def load():
        version = clean_version(_read_text(vpath).strip().splitlines()[0]) if vpath.exists() else ""
        built_at, commit = "", ""
        try:
            data = json.loads(_read_text(bpath))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            # build.json به یک VERSION تعلق دارد؛ اگر کسی VERSION را دستی عوض کرده
            # باشد، تاریخ و کامیتِ آن‌یکی دیگر مالِ این نسخه نیست.
            if not version or clean_version(data.get("version")) == version:
                b, c = data.get("built_at"), data.get("commit")
                built_at = b.strip() if isinstance(b, str) and _BUILT_RE.match(b.strip()) else ""
                commit = c.strip().lower() if isinstance(c, str) and _COMMIT_RE.match(c.strip()) else ""
        if not built_at and version:
            built_at = _iso_from_mtime(vpath)
        return {"version": version, "built_at": built_at, "commit": commit, "name": NAME}

    value = _cached("build", [vpath, bpath], load)
    if not isinstance(value, dict):
        value = {"version": "", "built_at": "", "commit": "", "name": NAME}
    return value


# ---------------------------------------------------------------- تقویمِ شمسی (برای راهنمای نشان)

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def built_at_fa(iso: str) -> str:
    """`2026-11-07T10:00:00Z` ⇒ `۱۴۰۵/۰۸/۱۶` (به وقتِ تهران)؛ ناخوانا ⇒ ""."""
    if not isinstance(iso, str) or not _BUILT_RE.match(iso):
        return ""
    try:
        text = iso.replace("Z", "+00:00")
        when = _dt.datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        when = when.astimezone(_dt.timezone(_dt.timedelta(hours=3, minutes=30)))
        jy, jm, jd = gregorian_to_jalali(when.year, when.month, when.day)
        return f"{jy:04d}/{jm:02d}/{jd:02d}".translate(_FA)
    except (ValueError, OverflowError):
        return ""


def admin_context() -> dict:
    """کلیدهایی که `templates/admin/base_site.html` برای نشانِ نسخه می‌خواند."""
    build = read_build()
    return {
        "nm_version": build["version"],
        "nm_commit": build["commit"],
        "nm_built_fa": built_at_fa(build["built_at"]),
    }


# ---------------------------------------------------------------- فهرستِ تغییرات

# «## v2.60 — ۱۴۰۵/۰۸/۱۶» ؛ جداکننده می‌تواند — – - : | باشد و تاریخ اختیاری است
_HEAD_RE = re.compile(
    r"^\s{0,3}##\s+[vV]?\s*([0-9۰-۹٠-٩]{1,3}\s*[.٫]\s*[0-9۰-۹٠-٩]{2,3})\s*"
    r"(?:[—–\-:|]+\s*(.*?))?\s*#*\s*$"
)
_OTHER_HEAD_RE = re.compile(r"^\s{0,3}#{1,2}(?!#)(\s|$)")
_BULLET_RE = re.compile(r"^(\s*)(?:[-*+•]|\d{1,3}[.)])\s+(.*\S)\s*$")


def _plain(text: str) -> str:
    text = text.replace("**", "").replace("`", "")
    return text.strip()[:MAX_ITEM_CHARS]


def parse_changelog(text) -> list[dict]:
    """متنِ CHANGELOG-fa.md ⇒ [{"version", "date", "summary", "items": [...]}].

    تحمل‌پذیر است: ورودیِ غیرمتن، BOM، CRLF، رقم‌های فارسی، خطِ خراب — هر چه باشد
    فهرست برمی‌گرداند (در بدترین حالت خالی)، هرگز استثنا نمی‌اندازد.
    """
    try:
        if isinstance(text, bytes):
            text = text.decode("utf-8-sig", errors="replace")
        if not isinstance(text, str):
            return []
        entries: list[dict] = []
        current: dict | None = None
        last_item = False  # آیا خطِ قبلی یک بولت بود (برای ادامهٔ خطِ شکسته)
        for line in text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            head = _HEAD_RE.match(line)
            if head:
                version = clean_version(head.group(1).translate(_DIGITS).replace(" ", ""))
                if not version:
                    current = None
                    continue
                if len(entries) >= MAX_ENTRIES:
                    break
                current = {"version": version, "date": _plain(head.group(2) or ""), "summary": "", "items": []}
                entries.append(current)
                last_item = False
                continue
            if _OTHER_HEAD_RE.match(line):
                # تیترِ سطحِ ۱ یا ۲ که نسخه نیست («## نکته»): بخشِ قبلی همین‌جا تمام می‌شود
                current = None
                last_item = False
                continue
            if current is None:
                continue
            if line.lstrip().startswith("#"):  # زیرتیترها (###) نادیده‌اند
                last_item = False
                continue
            bullet = _BULLET_RE.match(line)
            if bullet:
                if len(current["items"]) < MAX_ITEMS:
                    current["items"].append(_plain(bullet.group(2)))
                last_item = True
                continue
            stripped = line.strip()
            if not stripped:
                last_item = False
                continue
            if last_item and current["items"] and line[:1] in (" ", "\t"):
                joined = f"{current['items'][-1]} {stripped}"
                current["items"][-1] = _plain(joined)
            elif not current["items"]:
                joined = f"{current['summary']} {stripped}".strip()
                current["summary"] = _plain(joined)
        return entries
    except Exception:  # noqa: BLE001
        return []


def read_changelog() -> list[dict]:
    path = root_dir() / CHANGELOG_FILE

    def load():
        return parse_changelog(_read_text(path)) if path.exists() else []

    value = _cached("changelog", [path], load)
    return value if isinstance(value, list) else []

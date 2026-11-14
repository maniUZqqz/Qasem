# -*- coding: utf-8 -*-
"""کاتالوگِ 21st.dev برای سایت‌ساز: خزیدنِ فهرستِ عمومی (نه کد)، جست‌وجو، «الهام برای AI»، و گرفتنِ کد فقط با کلیدِ API ِ خودِ مالک.

چه چیزی مجاز است و چه چیزی نه (از robots.txt و llms.txt ِ خودِ 21st.dev، ۱۴۰۵/۰۸/۲۳):

* ``Content-Signal: ai-train=no, search=yes, ai-input=yes`` و ``Allow: /`` ⇒ صفحه‌های ``.md`` ِ دسته‌ها و قطعه‌ها را برای «جست‌وجو» و
  «ورودیِ هوش مصنوعی» می‌شود خواند؛ آموزشِ مدل (train) نه. ما فقط فهرست می‌سازیم و هرگز کتابخانه را به مدل نمی‌دهیم.
* ``Disallow: /r/`` برای خزنده‌ها ⇒ کدِ قطعه (ریجیستری) را **نمی‌خزیم**؛ فقط با کلیدِ API ِ مالک و از راهِ رسمیِ نصب (``x-api-key``) و در سقفِ روزانهٔ
  حسابِ رایگان (۲ قطعه در روز) گرفته می‌شود.
* هر قطعه مجوزِ خودش را دارد؛ فقط مجوزهای آزاد (MIT، Apache-2.0، BSD، ISC، CC0، Unlicense) ``usable`` ‌اند؛ بقیه (و «no-license») فقط برای دیدن‌اند.

داده زیرِ ``NM_DATA_DIR/c21st/`` است (فایل، بدونِ مهاجرت): ``catalog.json`` ، ``crawl.json`` (وضعیتِ خزش، قابلِ ازسرگیری)، ``code/`` ، ``key`` (فقط برای مالک)،
``quota.json``. هیچ کلیدی در پاسخ یا لاگ نمی‌آید.

حالتِ AI: ``ai_context.build(..., refs21=[...])`` حداکثر ۳ قطعه را به‌صورتِ «الهام» (عنوان، خلاصه، برچسب، وابستگی، مجوز و — اگر کدش گرفته شده — یک برشِ
کوتاه) به مدل می‌دهد، زیرِ همان سقفِ ۹۰۰۰ نویسه؛ مدل باید با HTML/CSSِ ساده و کلاس‌های خودمان بنویسد، نه React.
حالتِ دستی: «نزدیک‌ترین قطعهٔ ما» (``nearest_components``) را به بوم اضافه می‌کند.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from django.conf import settings

from services import safenet

logger = logging.getLogger(__name__)

BASE = "https://21st.dev"
MAX_PER_CATEGORY = 60                    # ‏«Showing the first 60» ِ خودِ صفحه
DELAY = 1.2                              # ثانیه بینِ دو درخواست (مؤدبانه)
MAX_CODE_CHARS = 60_000
EXCERPT_CHARS = 900
MAX_AI_REFS = 3
DAILY_LIMIT_DEFAULT = 2                  # حسابِ رایگانِ 21st.dev
PERMISSIVE = {"mit", "apache-2.0", "apache 2.0", "bsd", "bsd-2-clause", "bsd-3-clause", "isc", "0bsd", "unlicense", "cc0", "cc0-1.0"}

#: دسته‌های 21st.dev (از llms.txt) ⇒ (برچسبِ فارسی، دسته‌ی نزدیک در قطعه‌های خودمان یا '')؛ ترتیب = اولویتِ خزش برای سایتِ فروشگاهی
CATEGORIES: dict[str, tuple[str, str]] = {
    "hero": ("سربرگِ بزرگ", "hero"), "features": ("ویژگی‌ها", "features"), "cta": ("دعوت به اقدام", "cta"), "pricing-section": ("قیمت", "pricing"),
    "testimonials": ("نظرها", "testimonials"), "navigation": ("منوی بالا", "navbar"), "footer": ("پابرگ", "footer"), "card": ("کارت", "cards"),
    "accordion": ("پرسش‌های پرتکرار", "faq"), "marquee": ("نوارِ متحرک", "gallery"), "landing-page": ("صفحهٔ فرود", "steps"), "background": ("پس‌زمینه", "hero"),
    "text-animation": ("متنِ متحرک", "hero"), "carousel": ("اسلایدر", "gallery"), "animated": ("متحرک", ""), "tabs": ("تب", "features"), "button": ("دکمه", "cta"),
    "badge": ("نشان", ""), "form": ("فرم", "cta"), "search": ("جست‌وجو", ""), "avatar": ("آواتار", "testimonials"), "notification": ("اعلان", ""),
    "dialog": ("پنجرهٔ باز‌شو", ""), "ai-chat": ("گفت‌وگوی AI", ""), "login": ("ورود", ""), "dashboard": ("داشبورد", ""), "table": ("جدول", ""),
    "sidebar": ("نوارِ کناری", ""), "tooltip": ("راهنمای شناور", ""), "chart": ("نمودار", ""),
}


class CatalogError(RuntimeError):
    """پیامِ فارسیِ قابلِ نمایش."""


# ───────────────────────────── ذخیره

_lock = threading.Lock()
_cache: dict = {"mtime": 0.0, "rows": []}


def root() -> Path:
    p = Path(settings.NM_DATA_DIR) / "c21st"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _atomic(path: Path, text: str, mode: int | None = None) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
    tmp.replace(path)


def load() -> list[dict]:
    p = root() / "catalog.json"
    try:
        m = p.stat().st_mtime
    except OSError:
        return []
    if _cache["mtime"] != m or _cache.get("path") != str(p):
        try:
            _cache.update(mtime=m, rows=json.loads(p.read_text(encoding="utf-8")), path=str(p))
        except (OSError, ValueError):
            return []
    return _cache["rows"]


def save(rows: list[dict]) -> None:
    with _lock:
        _atomic(root() / "catalog.json", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        _cache["mtime"] = 0.0


def by_id(cid: str) -> dict | None:
    return next((r for r in load() if r["id"] == cid), None)


# ───────────────────────────── تجزیهٔ صفحه‌های .md

_ENTRY = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<url>https://21st\.dev/@[^)\s]+?)(?:\.md)?\)(?:\s+—\s+by\s+(?P<author>.+))?$", re.M)


def entry_id(url: str) -> str:
    """https://21st.dev/@ppramanik62/components/accordion(/variant) ⇒ ppramanik62/accordion(/variant)"""
    m = re.match(r"^https://21st\.dev/@([^/]+)/components/([^/?#]+)(?:/([^/?#]+))?", url)
    if not m:
        return ""
    return "/".join(p for p in (m.group(1), m.group(2), m.group(3)) if p)


def parse_category_md(md: str) -> list[dict]:
    out = []
    for m in _ENTRY.finditer(md or ""):
        cid = entry_id(m.group("url"))
        if cid:
            out.append({"id": cid, "title": m.group("title").strip()[:120], "author_name": (m.group("author") or "").strip()[:80]})
    return out


def _field(md: str, name: str) -> str:
    m = re.search(r"^- %s:\s*(.+)$" % re.escape(name), md, re.M)
    return m.group(1).strip() if m else ""


def parse_component_md(md: str) -> dict:
    title = re.search(r"^#\s+(.+)$", md or "", re.M)
    desc = re.search(r"^>\s+(.+)$", md or "", re.M)
    link = lambda s: (re.match(r"\[([^\]]+)\]", s) or [None, s])[1]  # noqa: E731
    lic = _field(md, "License")
    tags = [t.strip() for t in _field(md, "Tags").split(",") if t.strip()]
    deps = [t.strip() for t in _field(md, "npm dependencies").split(",") if t.strip()]
    return {"title": title.group(1).strip()[:120] if title else "", "description": desc.group(1).strip()[:260] if desc else "",
            "author_name": link(_field(md, "Author"))[:80], "library": _field(md, "Library")[:80], "license": lic[:40],
            "tags": tags[:10], "deps": deps[:8]}


def is_permissive(lic: str) -> bool:
    s = (lic or "").strip().lower()
    return s in PERMISSIVE or s.startswith(("bsd", "apache"))


# ───────────────────────────── خزش (قابلِ ازسرگیری، مؤدبانه)

def _state_path() -> Path:
    return root() / "crawl.json"


def crawl_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


RUNNING_STALE_S = 600


def is_running(st: dict | None = None) -> bool:
    """نوبتِ خزش همین الان در کار است؟ (اگر کارگر وسطِ نوبت مرد، پس از ۱۰ دقیقه دیگر «در حالِ کار» حساب نمی‌شود.)"""
    st = crawl_state() if st is None else st
    return bool(st.get("running")) and time.time() - float(st.get("running_at") or 0) < RUNNING_STALE_S


def _save_state(st: dict) -> None:
    _atomic(_state_path(), json.dumps(st, ensure_ascii=False))


def _fetch_md(url: str, fetch) -> str:
    try:
        res = fetch(url, max_bytes=400_000, accept="text/markdown,text/plain;q=0.9,*/*;q=0.1")
    except safenet.FetchError as exc:
        raise CatalogError(exc.message) from exc
    return res.text


def crawl(*, fetch=None, categories=None, detail_limit: int = 400, max_seconds: float = 240.0, delay: float = DELAY, sleep=time.sleep,
          clock=time.monotonic) -> dict:
    """یک «نوبت» از خزش: اول فهرستِ دسته‌ها (۶۰ تای اول هرکدام)، بعد جزئیاتِ قطعه‌ها (مجوز، برچسب، وابستگی) تا سقفِ زمان/تعداد.
    وضعیت در crawl.json می‌ماند؛ دوباره صدا زدن از همان‌جا ادامه می‌دهد. ⇒ {state, ...}"""
    get = fetch or safenet.get
    started = clock()
    st = crawl_state()
    if not st or st.get("finished"):
        st = {"started_at": _now(), "finished": False, "cats_done": [], "details_done": 0, "errors": [], "turns": 0}
    st["running"] = True
    st["running_at"] = time.time()
    st["turns"] = st.get("turns", 0) + 1
    _save_state(st)
    rows = {r["id"]: r for r in load()}
    cats = [c for c in (categories or list(CATEGORIES)) if c in CATEGORIES]
    errors = st.get("errors", [])[-20:]

    def out_of_time() -> bool:
        return clock() - started > max_seconds

    for cat in cats:
        if cat in st["cats_done"]:
            continue
        if out_of_time():
            break
        try:
            md = _fetch_md(f"{BASE}/community/components/s/{quote(cat)}.md", get)
            for e in parse_category_md(md)[:MAX_PER_CATEGORY]:
                r = rows.setdefault(e["id"], {"id": e["id"], "title": e["title"], "author_name": e["author_name"], "cats": [], "detail": False})
                if cat not in r["cats"]:
                    r["cats"].append(cat)
            st["cats_done"].append(cat)
        except CatalogError as exc:
            errors.append(f"{cat}: {exc}")
        sleep(delay)
    todo = [r for r in rows.values() if not r.get("detail")]
    # اول قطعه‌هایی که در دسته‌های مهمِ سایتِ فروشگاهی‌اند
    prio = {c: i for i, c in enumerate(CATEGORIES)}
    todo.sort(key=lambda r: min((prio.get(c, 99) for c in r.get("cats", [])), default=99))
    done_now = 0
    for r in todo:
        if done_now >= detail_limit or out_of_time():
            break
        try:
            parts = r["id"].split("/")
            md = _fetch_md(f"{BASE}/@{parts[0]}/components/{'/'.join(parts[1:])}.md", get)
            d = parse_component_md(md)
            r.update({k: v for k, v in d.items() if v}, detail=True)
            r["usable"] = is_permissive(r.get("license", ""))
            r["url"] = f"{BASE}/@{parts[0]}/components/{'/'.join(parts[1:])}"
        except CatalogError as exc:
            r["detail"] = True                       # رد شد؛ دوباره و دوباره تلاش نکن
            r["usable"] = False
            errors.append(f"{r['id']}: {exc}")
        done_now += 1
        st["details_done"] = st.get("details_done", 0) + 1
        sleep(delay)
    save(sorted(rows.values(), key=lambda r: r["id"]))
    remaining = sum(1 for r in rows.values() if not r.get("detail")) + sum(1 for c in cats if c not in st["cats_done"])
    st.update(running=False, errors=errors[-20:], updated_at=_now(), total=len(rows), remaining=remaining, finished=remaining == 0)
    if st["finished"]:
        st["finished_at"] = _now()
    _save_state(st)
    return st


def _now() -> str:
    from django.utils import timezone

    return timezone.now().isoformat(timespec="seconds")


# ───────────────────────────── جست‌وجو

def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^\w؀-ۿ]+", (text or "").lower()) if len(w) > 1}


def search(q: str = "", cat: str = "", usable_only: bool = False, page: int = 1, size: int = 24) -> dict:
    rows = load()
    words = _words(q)
    scored = []
    for r in rows:
        if cat and cat not in r.get("cats", []):
            continue
        if usable_only and not r.get("usable"):
            continue
        s = 0
        if words:
            hay = _words(" ".join([r.get("title", ""), r.get("description", ""), " ".join(r.get("tags", [])), r.get("library", ""), r.get("author_name", ""), " ".join(r.get("cats", []))]))
            s = 3 * len(words & _words(r.get("title", ""))) + len(words & hay)
            if s == 0:
                continue
        scored.append((s, 1 if r.get("detail") else 0, r))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]["id"]))
    size = max(1, min(60, size))
    page = max(1, page)
    items = [public(r) for _s, _d, r in scored[(page - 1) * size: page * size]]
    cats = [{"key": k, "label": v[0], "count": sum(1 for r in rows if k in r.get("cats", []))} for k, v in CATEGORIES.items()]
    return {"total": len(scored), "page": page, "size": size, "items": items, "categories": [c for c in cats if c["count"]], "catalog_size": len(rows)}


def public(r: dict) -> dict:
    code = (root() / "code" / (safe_name(r["id"]) + ".tsx")).is_file()
    return {"id": r["id"], "title": r.get("title", ""), "description": r.get("description", ""), "author": r.get("author_name", ""), "library": r.get("library", ""),
            "license": r.get("license", "") or ("بررسی‌نشده" if not r.get("detail") else "بدونِ مجوز"), "usable": bool(r.get("usable")), "tags": r.get("tags", []),
            "deps": r.get("deps", []), "cats": r.get("cats", []), "url": r.get("url") or f"{BASE}/@{r['id'].split('/')[0]}/components/{'/'.join(r['id'].split('/')[1:])}",
            "has_code": code, "nearest": nearest_components(r)}


def safe_name(cid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "__", cid)[:120]


# ───────────────────────────── «نزدیک‌ترین قطعهٔ ما» (حالتِ دستی)

def nearest_components(r: dict, limit: int = 2) -> list[dict]:
    from . import components as comps

    want = {CATEGORIES[c][1] for c in r.get("cats", []) if c in CATEGORIES and CATEGORIES[c][1]}
    words = _words(" ".join([r.get("title", ""), " ".join(r.get("tags", [])), r.get("description", "")]))
    scored = []
    for k in comps.ORDER:
        c = comps.COMPONENTS[k]
        if c["root"] != "section" and c["cat"] not in want:
            continue
        s = (3 if c["cat"] in want else 0) + len(words & _words(" ".join(c["tags"]) + " " + c["label"]))
        if s:
            scored.append((s, k))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"key": k, "label": comps.COMPONENTS[k]["label"], "type": comps.block_type(k)} for _s, k in scored[:limit]]


# ───────────────────────────── کلیدِ API و گرفتنِ کد (فقط برای مالک)

def _key_path() -> Path:
    return root() / "key"


def get_key() -> str:
    env = (os.environ.get("API_KEY_21ST") or "").strip()
    if env:
        return env
    try:
        return _key_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_key(key: str) -> None:
    key = (key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._\-]{16,200}", key):
        raise CatalogError("کلید معتبر نیست؛ همان رشتهٔ بلندی را بچسبانید که 21st.dev/mcp می‌دهد.")
    _atomic(_key_path(), key, mode=0o600)


def clear_key() -> None:
    _key_path().unlink(missing_ok=True)


def daily_limit() -> int:
    try:
        return max(1, int(os.environ.get("C21ST_DAILY_LIMIT") or DAILY_LIMIT_DEFAULT))
    except ValueError:
        return DAILY_LIMIT_DEFAULT


def quota_used(today: str | None = None) -> int:
    today = today or time.strftime("%Y-%m-%d")
    try:
        d = json.loads((root() / "quota.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(d.get("n", 0)) if d.get("day") == today else 0


def _bump_quota() -> None:
    today = time.strftime("%Y-%m-%d")
    _atomic(root() / "quota.json", json.dumps({"day": today, "n": quota_used(today) + 1}))


def key_status() -> dict:
    has = bool(get_key())
    used = quota_used()
    return {"has_key": has, "limit": daily_limit(), "used_today": used, "left_today": max(0, daily_limit() - used) if has else 0,
            "how": "کلیدِ API را از 21st.dev/mcp بسازید (رایگان؛ ۲ قطعه در روز). بدونِ کلید فقط فهرست و جست‌وجو کار می‌کند."}


def fetch_code(cid: str, *, fetch=None) -> dict:
    """کدِ یک قطعه (فقط مجوزِ آزاد) از ریجیستریِ رسمی با کلیدِ مالک؛ ⇒ {id, files, chars}. هیچ خطایی کلید را فاش نمی‌کند."""
    r = by_id(cid)
    if r is None:
        raise CatalogError("این قطعه در کاتالوگ نیست.")
    if not r.get("usable"):
        raise CatalogError("مجوزِ این قطعه «%s» است؛ فقط قطعه‌های با مجوزِ آزاد (MIT، Apache، BSD، ISC، CC0) گرفته می‌شوند." % (r.get("license") or "نامعلوم"))
    key = get_key()
    if not key:
        raise CatalogError("برای گرفتنِ کدِ قطعه کلیدِ API ِ 21st.dev لازم است (رایگان؛ ۲ قطعه در روز). کلید را در همین بخش وارد کنید.")
    if quota_used() >= daily_limit():
        raise CatalogError("سقفِ امروزِ حسابِ 21st.dev پر شد (%d قطعه در روز)؛ فردا دوباره یا حسابِ پولی." % daily_limit())
    parts = cid.split("/")
    url = f"{BASE}/r/{quote(parts[0])}/{quote(parts[1])}" + (f"/{quote(parts[2])}" if len(parts) > 2 else "")
    get = fetch or safenet.get
    try:
        res = get(url, max_bytes=800_000, accept="application/json", headers={"x-api-key": key}, allow_status=(200,))
    except safenet.FetchError as exc:
        if exc.code in ("http_401", "http_403"):
            raise CatalogError("21st.dev کلید را نپذیرفت (۴۰۱/۴۰۳)؛ کلید را دوباره بسازید.") from exc
        if exc.code == "http_429":
            raise CatalogError("21st.dev گفت سقفِ استفاده پر شده است؛ بعداً دوباره.") from exc
        raise CatalogError("گرفتنِ قطعه ممکن نشد: " + exc.message) from exc
    try:
        data = json.loads(res.text)
    except ValueError as exc:
        raise CatalogError("جوابِ 21st.dev خوانده نشد.") from exc
    files = [f for f in (data.get("files") or []) if isinstance(f, dict) and isinstance(f.get("content"), str)]
    if not files:
        raise CatalogError("جوابِ 21st.dev فایلی نداشت.")
    out_files, total = [], 0
    for f in files[:6]:
        content = f["content"][: max(0, MAX_CODE_CHARS - total)]
        total += len(content)
        out_files.append({"path": str(f.get("path") or "")[:160], "content": content})
        if total >= MAX_CODE_CHARS:
            break
    d = root() / "code"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": cid, "license": r.get("license", ""), "author": r.get("author_name", ""), "url": r.get("url", ""), "fetched_at": _now(),
            "dependencies": data.get("dependencies") or [], "files": out_files}
    _atomic(d / (safe_name(cid) + ".json"), json.dumps(meta, ensure_ascii=False))
    _atomic(d / (safe_name(cid) + ".tsx"), out_files[0]["content"])
    _bump_quota()
    return {"id": cid, "files": [f["path"] for f in out_files], "chars": total}


def code_excerpt(cid: str, limit: int = EXCERPT_CHARS) -> str:
    try:
        text = (root() / "code" / (safe_name(cid) + ".tsx")).read_text(encoding="utf-8")
    except OSError:
        return ""
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text[:limit]


# ───────────────────────────── به مدل (حالتِ AI)

def inspiration_for(ids, limit: int = MAX_AI_REFS) -> list[dict]:
    """حداکثر ``limit`` قطعه ⇒ ردیف‌های کوچک برای پرامپت. شناسهٔ ناشناخته یا بی‌مجوزِ آزاد دور ریخته می‌شود (برای قطعه‌های بی‌مجوز فقط عنوان و برچسب)."""
    out: list[dict] = []
    for cid in list(dict.fromkeys(ids or []))[:limit]:
        r = by_id(str(cid))
        if r is None:
            continue
        row = {"id": r["id"], "title": r.get("title", ""), "summary": (r.get("description") or "")[:200], "tags": r.get("tags", [])[:6],
               "deps": r.get("deps", [])[:4], "license": r.get("license", "") or "نامعلوم"}
        if r.get("usable"):
            ex = code_excerpt(r["id"])
            if ex:
                row["code_excerpt"] = ex
        out.append(row)
    return out


def valid_ids(ids) -> list[str]:
    have = {r["id"] for r in load()}
    return [i for i in dict.fromkeys(str(x) for x in (ids or [])) if i in have][:MAX_AI_REFS]

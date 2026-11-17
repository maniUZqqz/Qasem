# -*- coding: utf-8 -*-
"""خزندهٔ مؤدبِ 21st.dev: کلِ فهرستِ عمومی (نقشهٔ سایت)، جزئیاتِ هر قطعه (مجوز، برچسب، وابستگی، کتابخانه)، صفحهٔ کتابخانه‌ها (مخزنِ GitHub)
و تصویرِ پیش‌نمایش. قابلِ ازسرگیری، با تلاشِ مجدد، و ``robots.txt`` را «واقعاً» می‌خواند (نه فقط در توضیح).

چه چیزی را می‌خزد و چه چیزی را نه (از robots.txt و llms.txt ِ خودِ 21st.dev):

* ``Allow: /`` برای همهٔ عامل‌ها؛ ``Disallow: /api/ /r/ /preview/ /auth/ /admin/ /sign-in /community/bookmarks/``  ⇒ هر درخواست پیش از ارسال با
  ``Robots.allowed`` سنجیده می‌شود؛ مسیرِ ممنوع هرگز فرستاده نمی‌شود (نه ریجیستری ``/r/``، نه ``/api/``، نه ``/preview/``).
* ``Content-Signal: ai-train=no, search=yes, ai-input=yes`` ⇒ آموزشِ مدل نمی‌کنیم؛ فقط فهرست‌سازی و «ورودیِ AI» با چند قطعهٔ مرتبط در هر درخواست.
* کدِ خودِ قطعه در صفحهٔ عمومی نیست («The component's own source comes with a free account»)؛ فقط کدِ «نمونهٔ استفاده» (Usage.tsx) دیده می‌شود.
  این‌جا فقط آن نمونه خوانده می‌شود؛ کدِ قطعه را ``c21_source`` از مخزنِ عمومیِ خودِ کتابخانه (اگر مجوزِ آزاد دارد) یا با کلیدِ API ِ مالک می‌آورد.
* تصویرِ پیش‌نمایش از ``/og/component/<نویسنده>/<قطعه>`` (کارتِ اشتراک؛ robots.txt صریحاً باز گذاشته) گرفته و کوچک می‌شود.
* نقشهٔ سایت (``Sitemap:`` در robots.txt) فهرستِ همهٔ قطعه‌هاست؛ ۶۰ تای اولِ هر دسته کافی نیست.

نرخ: یک درخواست در هر ``DELAY`` ثانیه (+ کمی تصادف)، همیشه یکی‌یکی؛ ۴۲۹/۵۰۰ ⇒ تلاشِ مجدد با صبرِ فزاینده و ``Retry-After``؛ ۴۰۳ پشت‌سرِ هم ⇒ توقفِ نوبت.
مسیرِ جایگزین: اگر سرور مسدود شد، همین کارها را کارِ گرهٔ GPU ``crawl21.run`` با مرورگرِ بی‌سر انجام می‌دهد (processing/crawl21_jobs.py) و نتیجه به ``ingest`` می‌رسد.
"""
from __future__ import annotations

import io
import json
import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from services import safenet

from . import c21_net, c21st

logger = logging.getLogger(__name__)

BASE = c21st.BASE
UA_TOKEN = "NMarketingBot"
DELAY = 1.2                          # ثانیه بینِ دو درخواست (کنارِ این، ۰ تا ۰٫۴ ثانیه تصادف)
RETRY_WAITS = (2.0, 6.0, 18.0)          # ۴۲۹ / ۵xx: صبرِ فزاینده
CONNECT_RETRIES = 5                    # قطعِ اتصال/زمان‌سنج (هنوز چیزی فرستاده نشده؛ اینترنتِ ایران لنگ می‌زند): زود و بی‌صبرِ زیاد دوباره
CONNECT_WAIT = 1.0
MAX_RETRY_AFTER = 120.0
ROBOTS_TTL_S = 24 * 3600
ROBOTS_STALE_OK_S = 7 * 24 * 3600     # robots.txt خوانده نشد (مسیرِ ایران لنگ می‌زند) ⇒ نسخهٔ ذخیره‌شدهٔ تا یک هفته پیش را به‌کار ببر؛ نه «همه‌چیز ممنوع»
SITEMAP_TTL_S = 6 * 24 * 3600
PREVIEW_W = 560
PREVIEW_MAX_BYTES = 900_000
DETAIL_SHARE = 0.65                  # سهمِ جزئیات از زمانِ یک نوبت؛ بقیه برای کتابخانه‌ها و پیش‌نمایش‌ها
STOP_AFTER_FORBIDDEN = 4             # ۴۰۳ پشت‌سرهم ⇒ احتمالاً مسدود شده‌ایم؛ نوبت را ببند

_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}(?:/[A-Za-z0-9._-]{1,120}){1,2}$")


class CrawlBlocked(RuntimeError):
    """ ۴۰۳ چندباره: سرور ما را نمی‌پذیرد؛ کارِ گره (crawl21.run) جایگزین است."""


# ───────────────────────────── robots.txt (طبقِ RFC 9309: بلندترین تطبیق برنده است؛ مساوی ⇒ Allow)

class Robots:
    def __init__(self, text: str = "", *, ok: bool = True):
        self.groups: list[tuple[list[str], list[tuple[bool, str]], dict]] = []
        self.sitemaps: list[str] = []
        self.ok = ok                         # false = robots.txt خوانده نشد ⇒ محتاطانه همه‌چیز ممنوع
        self._parse(text or "")

    def _parse(self, text: str) -> None:
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        extra: dict = {}
        seen_rule = False

        def flush():
            if agents:
                self.groups.append((list(agents), list(rules), dict(extra)))

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if seen_rule:
                    flush()
                    agents, rules, extra, seen_rule = [], [], {}, False
                agents.append(val.lower())
            elif key in ("allow", "disallow"):
                seen_rule = True
                if val or key == "allow":        # «Disallow:» خالی = همه‌چیز مجاز؛ قاعده‌ای نمی‌سازد
                    rules.append((key == "allow", val))
            elif key == "crawl-delay":
                try:
                    extra["crawl_delay"] = float(val)
                except ValueError:
                    pass
            elif key == "sitemap":
                self.sitemaps.append(val)
        flush()

    def _group(self, ua: str):
        ua = ua.lower()
        best, best_len = None, -1
        for agents, rules, extra in self.groups:
            for a in agents:
                if a != "*" and a in ua and len(a) > best_len:
                    best, best_len = (rules, extra), len(a)
        if best:
            return best
        for agents, rules, extra in self.groups:
            if "*" in agents:
                return rules, extra
        return [], {}

    @staticmethod
    def _match(pattern: str, path: str) -> int:
        """طولِ تطبیق یا -1. * هر دنباله، $ پایانِ نشانی."""
        if not pattern:
            return -1
        anchored = pattern.endswith("$")
        pat = pattern[:-1] if anchored else pattern
        rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pat)
        m = re.match(rx + ("$" if anchored else ""), path)
        return len(pat) if m else -1

    def allowed(self, url_or_path: str, ua: str = UA_TOKEN) -> bool:
        if not self.ok:
            return False
        parts = urlsplit(url_or_path)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        rules, _extra = self._group(ua)
        best_len, best_allow = -1, True
        for allow, pat in rules:
            n = self._match(pat, path)
            if n > best_len or (n == best_len and allow and not best_allow):
                best_len, best_allow = n, allow
        return best_allow if best_len >= 0 else True

    def crawl_delay(self, ua: str = UA_TOKEN) -> float:
        return float(self._group(ua)[1].get("crawl_delay") or 0)


# ───────────────────────────── دریافتِ مؤدبانه

class Session:
    """یک نوبتِ خزش: robots، محدودکنندهٔ نرخ، تلاشِ مجدد. ``fetch`` / ``sleep`` / ``clock`` برای آزمون جایگزین می‌شوند."""

    def __init__(self, *, fetch=None, sleep=time.sleep, clock=time.monotonic, delay: float = DELAY, jitter: float = 0.4, robots: Robots | None = None,
                 rng=random.random, robots_cache: bool = False):
        self.fetch = fetch or c21_net.get              # اتصالِ هم‌زمانِ چندتایی + Keep-Alive برای 21st.dev (c21_net)؛ میزبانِ دیگر ⇒ safenet.get
        self.robots_cache = robots_cache               # robots.txt روی دیسک می‌ماند (۲۴ ساعت تازه؛ تا ۷ روز اگر خواندنِ تازه شکست خورد)
        self.sleep, self.clock, self.delay, self.jitter, self.rng = sleep, clock, delay, jitter, rng
        self.robots = robots
        self._last = None
        self.requests = 0
        self.forbidden_streak = 0
        self.refused: list[str] = []         # نشانی‌هایی که robots.txt اجازه نداد (برای گزارش و آزمون)

    # ── robots
    # ── robots.txt روی دیسک (از نوبتی به نوبتِ دیگر؛ خواندنِ هر بارهٔ آن از ایران گاهی شکست می‌خورد و کلِ نوبت را هدر می‌داد)
    @staticmethod
    def robots_cache_path() -> Path:
        return c21st.root() / "robots.txt"

    def _read_robots_cache(self, max_age: float) -> str | None:
        try:
            p = self.robots_cache_path()
            if time.time() - p.stat().st_mtime <= max_age:
                text = p.read_text(encoding="utf-8")
                return text if text.strip() else None
        except OSError:
            pass
        return None

    def _write_robots_cache(self, text: str) -> None:
        try:
            c21st._atomic(self.robots_cache_path(), text)
        except OSError:
            pass

    def load_robots(self, *, cached_text: str | None = None) -> Robots:
        if self.robots is not None:
            return self.robots
        if cached_text:
            self.robots = Robots(cached_text)
            return self.robots
        if self.robots_cache:
            fresh = self._read_robots_cache(ROBOTS_TTL_S)
            if fresh:
                self.robots = Robots(fresh)
                self.robots.raw = fresh
                return self.robots
        last = None
        for attempt in range(CONNECT_RETRIES + 1):                      # یک زمان‌سنجِ گذرا نباید کلِ نوبت را بخواباند
            try:
                res = self.fetch(f"{BASE}/robots.txt", max_bytes=200_000, accept="text/plain,*/*;q=0.1", timeout=40.0)
                self.robots = Robots(res.text)
                self.robots.raw = res.text
                if self.robots_cache and res.text.strip():
                    self._write_robots_cache(res.text)
                return self.robots
            except safenet.FetchError as exc:
                last = exc
                if exc.code.startswith("http_4") and exc.code != "http_429":
                    break
                if attempt < CONNECT_RETRIES:
                    self.sleep(CONNECT_WAIT * min(attempt + 1, 3) if exc.code in ("connect", "timeout") else RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)])
        if self.robots_cache and not (last and last.code.startswith("http_4") and last.code != "http_429"):
            stale = self._read_robots_cache(ROBOTS_STALE_OK_S)             # شبکه شکست خورد ولی نسخهٔ هفتهٔ گذشته هست: همان قاعده‌ها معتبرند
            if stale:
                self.robots = Robots(stale)
                self.robots.raw = stale
                self.robots.from_cache = True
                return self.robots
        # ۴xx = «robots.txt ندارد» ⇒ مجاز؛ غیرِ آن (قطعی، زمان‌سنج) ⇒ محتاطانه ممنوع
        self.robots = Robots("", ok=bool(last and last.code.startswith("http_4") and last.code != "http_429"))
        self.robots.raw = ""
        return self.robots

    def _pace(self) -> None:
        wait = self.delay + max(self.robots.crawl_delay() if self.robots else 0, 0) + self.jitter * self.rng()
        now = self.clock()
        if self._last is not None and now - self._last < wait:
            self.sleep(wait - (now - self._last))
        self._last = self.clock()

    def get(self, url: str, *, max_bytes: int = 600_000, accept: str = "text/markdown,text/plain;q=0.9,*/*;q=0.1"):
        """⇒ Fetched. ممنوعِ robots ⇒ FetchError(code='robots')؛ ۴۰۳ پشت‌سرهم ⇒ CrawlBlocked."""
        robots = self.load_robots()
        if not robots.allowed(url):
            self.refused.append(urlsplit(url).path)
            raise safenet.FetchError("robots.txt این نشانی را برای خزنده‌ها بسته است.", "robots")
        tries_conn = tries_http = 0
        while True:
            self._pace()
            self.requests += 1
            try:
                res = self.fetch(url, max_bytes=max_bytes, accept=accept)
                self.forbidden_streak = 0
                return res
            except safenet.FetchError as exc:
                if exc.code == "http_403":
                    self.forbidden_streak += 1
                    if self.forbidden_streak >= STOP_AFTER_FORBIDDEN:
                        raise CrawlBlocked("سرور ۴۰۳ می‌دهد") from exc
                    raise
                if exc.code in ("timeout", "connect"):                 # هنوز چیزی به سرور نرسیده؛ زود دوباره
                    tries_conn += 1
                    if tries_conn > CONNECT_RETRIES:
                        raise
                    self.sleep(CONNECT_WAIT * min(tries_conn, 3))
                    continue
                if exc.code == "http_429" or exc.code.startswith("http_5"):
                    if tries_http >= len(RETRY_WAITS):
                        raise
                    self.sleep(min(MAX_RETRY_AFTER, RETRY_WAITS[tries_http]))
                    tries_http += 1
                    continue
                raise


# ───────────────────────────── تجزیه

_LOC = re.compile(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]*)</lastmod>)?", re.S)
_COMP = re.compile(r"^https://21st\.dev/@([A-Za-z0-9._-]{1,60})/components/([A-Za-z0-9._-]{1,120})(?:/([A-Za-z0-9._-]{1,120}))?/?$")
_LIB = re.compile(r"^https://21st\.dev/@([A-Za-z0-9._-]{1,60})/library/([A-Za-z0-9._-]{1,120})/?$")


def parse_sitemap(xml: str) -> dict:
    """⇒ {'components': [(id, lastmod)], 'libraries': [(owner/slug, lastmod)], 'other': n}"""
    comps, libs, other = [], [], 0
    for m in _LOC.finditer(xml or ""):
        loc, mod = m.group(1).strip(), (m.group(2) or "").strip()
        c = _COMP.match(loc)
        if c:
            comps.append(("/".join(p for p in c.groups() if p), mod))
            continue
        l = _LIB.match(loc)
        if l:
            libs.append(("%s/%s" % l.groups(), mod))
        else:
            other += 1
    return {"components": comps, "libraries": libs, "other": other}


def title_from_slug(slug: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", slug.split("/")[-1])).strip().title()[:120]


_GH = re.compile(r"https://github\.com/([A-Za-z0-9._-]{1,60})/([A-Za-z0-9._-]{1,100})")


def parse_library_md(md: str, lib_id: str) -> dict:
    """صفحهٔ ``/@owner/library/<slug>.md`` ⇒ {id, name, owner, components, github, website, component_ids}"""
    title = re.search(r"^#\s+(.+)$", md or "", re.M)
    desc = re.search(r"^>\s+(.+)$", md or "", re.M)
    gh = ""
    g = _GH.search(c21st._field(md, "GitHub"))
    if g:
        repo = re.sub(r"\.git$", "", g.group(2))
        gh = "https://github.com/%s/%s" % (g.group(1), repo)
    n = re.search(r"Components:\s*(\d+)", md or "")
    ids = []
    for m in re.finditer(r"^- \[[^\]]+\]\((https://21st\.dev/@[^)\s]+?)(?:\.md)?\)", md or "", re.M):
        cid = c21st.entry_id(m.group(1))
        if cid:
            ids.append(cid)
    web = c21st._field(md, "Website")
    return {"id": lib_id, "name": (title.group(1).strip() if title else lib_id)[:100], "description": (desc.group(1).strip() if desc else "")[:300],
            "owner": re.sub(r"^\[([^\]]+)\].*$", r"\1", c21st._field(md, "Owner"))[:80], "components": int(n.group(1)) if n else len(ids),
            "github": gh, "website": web[:200] if web.startswith("http") else "", "component_ids": ids[:600]}


def library_id_of(md_library_field: str) -> str:
    """«[Magic UI](https://21st.dev/@dillionverma/library/magic-ui)» ⇒ dillionverma/magic-ui"""
    m = re.search(r"/@([^/]+)/library/([^/)\s?#]+)", md_library_field or "")
    return "%s/%s" % (m.group(1), m.group(2)) if m else ""


def tag_slug(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (tag or "").lower()).strip("-")


# برچسبِ 21st.dev (به‌شکلِ slug) ⇒ دستهٔ ما. بازبینیِ ۱۱/۱۶: ۱۲۲ از ۲۷۸ قطعهٔ تبدیل‌شده دسته نداشت چون فقط برچسبی که دقیقاً نامِ دسته بود می‌خورد.
TAG_ALIAS = {
    "faq": "accordion", "collapsible": "accordion", "expandable": "accordion", "disclosure": "accordion",
    "navbar": "navigation", "nav": "navigation", "menu": "navigation", "header": "navigation", "toolbar": "navigation", "breadcrumb": "navigation", "pagination": "navigation",
    "modal": "dialog", "popover": "dialog", "drawer": "dialog", "sheet": "dialog", "overlay": "dialog", "alert-dialog": "dialog", "lightbox": "dialog",
    "hover-card": "tooltip", "popup": "tooltip", "kbd": "badge", "tag": "badge", "chip": "badge", "label": "badge", "status": "badge",
    "login-form": "login", "sign-in": "login", "sign-up": "login", "signup": "login", "auth": "login", "authentication": "login", "register": "login",
    "input": "form", "textarea": "form", "select": "form", "checkbox": "form", "radio": "form", "switch": "form", "slider": "form", "color-picker": "form",
    "date-picker": "form", "upload": "form", "file-upload": "form", "dropzone": "form", "otp": "form", "newsletter": "form", "contact": "form",
    "testimonial": "testimonials", "reviews": "testimonials", "review": "testimonials", "social-proof": "testimonials", "customers": "testimonials",
    "pricing": "pricing-section", "plans": "pricing-section", "price": "pricing-section", "comparison": "pricing-section",
    "timeline": "landing-page", "steps": "landing-page", "stepper": "landing-page", "onboarding": "landing-page", "empty-state": "landing-page", "launch": "landing-page",
    "gallery": "carousel", "slideshow": "carousel", "image": "carousel", "video-player": "carousel", "video": "carousel", "media": "carousel",
    "list": "table", "data-table": "table", "grid-list": "card", "bento": "features", "bento-grid": "features", "benefits": "features", "services": "features",
    "chat": "ai-chat", "ai": "ai-chat", "agent": "ai-chat", "prompt": "ai-chat", "assistant": "ai-chat", "llm": "ai-chat",
    "graph": "chart", "data-visualization": "chart", "analytics": "dashboard", "stats": "dashboard", "kpi": "dashboard", "metrics": "dashboard",
    "typography": "text-animation", "heading": "text-animation", "title": "text-animation", "text": "text-animation",
    "loading": "animated", "spinner": "animated", "skeleton": "animated", "progress": "animated", "loader": "animated", "motion": "animated", "animation": "animated",
    "hover": "animated", "cursor": "animated", "shader": "background", "webgl": "background", "canvas": "background", "gradient": "background", "particles": "background",
    "banner": "hero", "landing": "landing-page", "splash": "hero", "intro": "hero", "announcement": "notification", "toast": "notification", "alert": "notification",
    "banners": "notification", "sidebar-menu": "sidebar", "drawer-menu": "sidebar", "command": "search", "command-palette": "search", "autocomplete": "search",
    "button": "button", "buttons": "button", "toggle": "button", "like": "button", "copy": "button",
}
TITLE_WORDS = (("hero", "hero"), ("pricing", "pricing-section"), ("testimonial", "testimonials"), ("footer", "footer"), ("navbar", "navigation"),
               ("nav-", "navigation"), ("navigation", "navigation"), ("menu", "navigation"), ("faq", "accordion"), ("accordion", "accordion"), ("marquee", "marquee"),
               ("carousel", "carousel"), ("feature", "features"), ("cta", "cta"), ("call-to-action", "cta"), ("login", "login"), ("sign-in", "login"), ("signup", "login"),
               ("dashboard", "dashboard"), ("sidebar", "sidebar"), ("button", "button"), ("btn", "button"), ("card", "card"), ("dialog", "dialog"), ("modal", "dialog"),
               ("popover", "dialog"), ("drawer", "dialog"), ("tooltip", "tooltip"), ("badge", "badge"), ("avatar", "avatar"), ("tabs", "tabs"), ("tab-", "tabs"),
               ("input", "form"), ("form", "form"), ("select", "form"), ("checkbox", "form"), ("switch", "form"), ("slider", "form"), ("upload", "form"),
               ("search", "search"), ("table", "table"), ("chart", "chart"), ("graph", "chart"), ("chat", "ai-chat"), ("prompt", "ai-chat"), ("toast", "notification"),
               ("notification", "notification"), ("alert", "notification"), ("heading", "text-animation"), ("typing", "text-animation"),
               ("spinner", "animated"), ("loader", "animated"), ("loading", "animated"), ("progress", "animated"), ("background", "background"),
               ("gradient", "background"))


def _has_word(norm: str, word: str) -> bool:
    """واژه به‌صورتِ «توکنِ کامل» (با s جمع) در شناسه/عنوان؛ «transform» دسته‌ی «form» نمی‌شود."""
    return re.search(r"(^|-)%ss?(-|$)" % re.escape(word.strip("-")), norm) is not None


def infer_cats(row: dict) -> list[str]:
    """دسته‌های ما از برچسب‌های 21st.dev (نامِ دسته یا هم‌معنی‌اش، TAG_ALIAS) و واژه‌های عنوان/شناسه؛ ترتیبِ حفظ‌شده و بی‌تکرار.
    اولویت با دسته‌های «بخشِ صفحه» (hero، قیمت، منو، پابرگ …) تا هر قطعه دست‌کم یک دسته داشته باشد."""
    cats = list(row.get("cats") or [])
    hay = [tag_slug(t) for t in row.get("tags", []) or []]
    title = (row.get("title", "") + " " + row.get("id", "")).lower()
    norm = tag_slug(title)
    for slug in hay:
        if slug in c21st.CATEGORIES and slug not in cats:
            cats.append(slug)
        elif slug + "-section" in c21st.CATEGORIES and slug + "-section" not in cats:
            cats.append(slug + "-section")
    for word, cat in TITLE_WORDS:
        if cat not in cats and _has_word(norm, word):
            cats.append(cat)
    for slug in hay:
        cat = TAG_ALIAS.get(slug)
        if cat and cat in c21st.CATEGORIES and cat not in cats:
            cats.append(cat)
    return cats[:6]


# ───────────────────────────── ذخیره‌های جانبی

def libs_path() -> Path:
    return c21st.root() / "libraries.json"


def load_libs() -> dict:
    try:
        return json.loads(libs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_libs(libs: dict) -> None:
    c21st._atomic(libs_path(), json.dumps(libs, ensure_ascii=False, separators=(",", ":")))


def previews_dir() -> Path:
    d = c21st.root() / "previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def preview_path(cid: str) -> Path:
    return previews_dir() / (c21st.safe_name(cid) + ".webp")


def make_preview(png_bytes: bytes, dest: Path, width: int = PREVIEW_W) -> int:
    """PNG ⇒ webp کوچک (نسبتِ ۱۲۰۰×۶۳۰ حفظ)؛ ⇒ اندازهٔ فایل."""
    from PIL import Image

    im = Image.open(io.BytesIO(png_bytes))
    im.load()
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    im = im.convert("RGB")
    tmp = dest.with_suffix(".tmp")
    im.save(tmp, "WEBP", quality=72, method=4)
    tmp.replace(dest)
    return dest.stat().st_size


# ───────────────────────────── نوبتِ خزش

PRIORITY_CATS = list(c21st.CATEGORIES)


def _prio(row: dict) -> tuple:
    cats = row.get("cats") or []
    best = min((PRIORITY_CATS.index(c) for c in cats if c in PRIORITY_CATS), default=99)
    return (0 if row.get("lib_known") else 1, best, row["id"])


def add_sitemap_rows(rows: dict, sm: dict) -> int:
    new = 0
    for cid, mod in sm["components"]:
        if not _ID_RE.match(cid):
            continue
        r = rows.get(cid)
        if r is None:
            rows[cid] = {"id": cid, "title": title_from_slug(cid), "author_name": "", "cats": [], "detail": False, "lastmod": mod}
            new += 1
        else:
            if mod and r.get("lastmod") != mod:
                r["lastmod_new"] = mod           # تغییر کرده؛ جزئیات یک بار دیگر خوانده می‌شود
                if r.get("detail") and r.get("detail_at", "") < mod:
                    r["detail"] = False
            r.setdefault("lastmod", mod)
    return new


def run_turn(*, session: Session | None = None, max_seconds: float = 240.0, detail_limit: int = 120, preview_limit: int = 40, lib_limit: int = 30,
             categories=None, clock=time.monotonic) -> dict:
    """یک نوبتِ خزش؛ وضعیت در crawl.json می‌ماند و دوباره صدا زدن از همان‌جا ادامه می‌دهد. ⇒ وضعیت.
    ترتیب: robots ⇒ نقشهٔ سایت ⇒ دسته‌ها (۶۰ تای اول) ⇒ کتابخانه‌ها ⇒ جزئیاتِ قطعه‌ها ⇒ پیش‌نمایشِ قطعه‌های با مجوزِ آزاد."""
    s = session or Session(robots_cache=True)
    started = clock()
    from . import c21_pipeline
    ps = c21_pipeline.pipeline_state()
    if ps.get("running") and time.time() - float(ps.get("running_at") or 0) < c21_pipeline.RUNNING_STALE_S:
        return {**c21st.crawl_state(), "deferred": "pipeline-running", "finished": False}
    st = c21st.crawl_state()
    if not st or st.get("finished"):
        st = {"started_at": c21st._now(), "finished": False, "cats_done": [], "details_done": 0, "errors": [], "turns": 0}
    st["running"], st["running_at"] = True, time.time()
    st["turns"] = st.get("turns", 0) + 1
    c21st._save_state(st)
    rows = {r["id"]: r for r in c21st.load()}
    for r in rows.values():                              # دسته‌های تازه (TAG_ALIAS/عنوان) برای ردیف‌های قدیمی در همین نوبت؛ فقط افزودن (نوشتنِ جدا با خزش درگیر می‌شد)
        if r.get("detail"):
            new = infer_cats(r)
            if new != (r.get("cats") or []):
                r["cats"] = new
    libs = load_libs()
    errors = st.get("errors", [])[-20:]
    blocked = False

    def marker() -> int:
        """کارِ انجام‌شده تا حالا (جزئیات + پیش‌نمایش + کتابخانه + دسته)؛ تفاوتِ اولِ نوبت با آخرش = پیشرفتِ این نوبت."""
        return (sum(1 for r in rows.values() if r.get("detail")) + sum(1 for r in rows.values() if r.get("preview") or r.get("preview_err"))
                + sum(1 for lb in libs.values() if lb.get("detail")) + len(st.get("cats_done", [])))
    marker0 = marker()

    def out_of_time() -> bool:
        return clock() - started > max_seconds

    def note(msg: str) -> None:
        errors.append(msg[:200])

    try:
        robots = s.load_robots(cached_text=None)
        st["robots_ok"] = robots.ok
        st["robots_disallow"] = sorted({pat for allow, pat in robots._group(UA_TOKEN)[0] if not allow})[:20]
        if not robots.ok:
            note("robots.txt خوانده نشد؛ محتاطانه چیزی خزیده نشد")
            raise StopIteration

        # ۱) نقشهٔ سایت
        if time.time() - float(st.get("sitemap_at") or 0) > SITEMAP_TTL_S and not out_of_time():
            try:
                res = s.get(f"{BASE}/sitemap.xml", max_bytes=8_000_000, accept="application/xml,text/xml;q=0.9,*/*;q=0.1")
                sm = parse_sitemap(res.text)
                new = add_sitemap_rows(rows, sm)
                for lid, mod in sm["libraries"]:
                    libs.setdefault(lid, {"id": lid, "name": title_from_slug(lid), "github": "", "detail": False, "lastmod": mod})
                st.update(sitemap_at=time.time(), sitemap_components=len(sm["components"]), sitemap_libraries=len(sm["libraries"]), sitemap_new=new)
            except safenet.FetchError as exc:
                note("sitemap: " + exc.message)

        # ۲) دسته‌ها: ۶۰ تای اولِ هر دسته (دسته‌ی هر قطعه + ترتیبِ اهمیت)
        cats = [c for c in (categories or list(c21st.CATEGORIES)) if c in c21st.CATEGORIES]
        for cat in cats:
            if cat in st["cats_done"] or out_of_time():
                continue
            try:
                md = s.get(f"{BASE}/community/components/s/{quote(cat)}.md").text
                for e in c21st.parse_category_md(md)[:c21st.MAX_PER_CATEGORY]:
                    r = rows.setdefault(e["id"], {"id": e["id"], "title": e["title"], "author_name": e["author_name"], "cats": [], "detail": False})
                    r["title"] = e["title"] or r["title"]
                    r["author_name"] = e["author_name"] or r.get("author_name", "")
                    if cat not in r["cats"]:
                        r["cats"].append(cat)
                st["cats_done"].append(cat)
            except safenet.FetchError as exc:
                note(f"{cat}: {exc.message}")

        # ۳) کتابخانه‌ها (مخزنِ GitHub برای یافتنِ کد)
        todo_libs = [l for l in libs.values() if not l.get("detail")]
        for lib in todo_libs[:lib_limit]:
            if out_of_time():
                break
            try:
                owner, slug = lib["id"].split("/", 1)
                md = s.get(f"{BASE}/@{quote(owner)}/library/{quote(slug)}.md").text
                got = parse_library_md(md, lib["id"])
                lib.update(got, detail=True, lastmod=lib.get("lastmod", ""))
            except safenet.FetchError as exc:
                lib["detail"] = True
                lib["error"] = exc.message[:120]
                note(f"library {lib['id']}: {exc.message}")
        for lib in libs.values():                     # قطعه‌های کتابخانه‌دار پیش از بقیه
            for cid in lib.get("component_ids") or []:
                if cid in rows:
                    rows[cid].setdefault("library_id", lib["id"])
                    rows[cid]["lib_known"] = bool(lib.get("github"))

        # ۴) جزئیاتِ قطعه‌ها (.md): مجوز، برچسب، وابستگی، کتابخانه
        todo = sorted((r for r in rows.values() if not r.get("detail")), key=_prio)
        done_now = 0
        for r in todo:
            if done_now >= detail_limit or out_of_time() or clock() - started > max_seconds * DETAIL_SHARE:      # بخشی از زمان برای پیش‌نمایش‌ها می‌ماند
                break
            parts = r["id"].split("/")
            try:
                md = s.get(f"{BASE}/@{quote(parts[0])}/components/{'/'.join(quote(p) for p in parts[1:])}.md").text
                d = c21st.parse_component_md(md)
                r.update({k: v for k, v in d.items() if v}, detail=True, detail_at=c21st._now())
                r["library_id"] = library_id_of(c21st._field(md, "Library")) or r.get("library_id", "")
                r["usable"] = c21st.is_permissive(r.get("license", ""))
                r["url"] = f"{BASE}/@{parts[0]}/components/{'/'.join(parts[1:])}"
                r["cats"] = infer_cats(r)
                if r.get("lastmod_new"):
                    r["lastmod"] = r.pop("lastmod_new")
            except CrawlBlocked:
                blocked = True
                break
            except safenet.FetchError as exc:
                if exc.code == "robots":
                    r["detail"], r["usable"] = True, False
                elif exc.code == "http_404":
                    r["detail"], r["usable"], r["gone"] = True, False, True
                else:
                    note(f"{r['id']}: {exc.message}")
                    continue
            done_now += 1
            st["details_done"] = st.get("details_done", 0) + 1
            if done_now % 25 == 0:
                c21st.save(sorted(rows.values(), key=lambda x: x["id"]))

        # ۵) پیش‌نمایش (فقط مجوزِ آزاد)
        if not blocked:
            pv = 0
            for r in sorted((r for r in rows.values() if r.get("usable") and r.get("detail") and not r.get("preview") and not r.get("preview_err")), key=_prio):
                if pv >= preview_limit or out_of_time():
                    break
                parts = r["id"].split("/")
                if len(parts) != 2:
                    r["preview_err"] = "variant"
                    continue
                try:
                    res = s.get(f"{BASE}/og/component/{quote(parts[0])}/{quote(parts[1])}", max_bytes=PREVIEW_MAX_BYTES, accept="image/png,image/*;q=0.8")
                    make_preview(res.body, preview_path(r["id"]))
                    r["preview"] = True
                except CrawlBlocked:
                    blocked = True
                    break
                except safenet.FetchError as exc:
                    r["preview_err"] = exc.code
                except Exception as exc:               # noqa: BLE001 - تصویرِ خراب ⇒ فقط همین قطعه بی‌پیش‌نمایش
                    r["preview_err"] = "image"
                    logger.warning("c21 preview %s: %s", r["id"], exc)
                pv += 1
    except StopIteration:
        pass
    except CrawlBlocked:
        blocked = True
    finally:
        for r in rows.values():
            r.pop("lastmod_new", None) if r.get("detail") else None
        c21st.save(sorted(rows.values(), key=lambda x: x["id"]))
        save_libs(libs)
        remaining = (sum(1 for r in rows.values() if not r.get("detail")) + sum(1 for c in (categories or c21st.CATEGORIES) if c not in st["cats_done"] and c in c21st.CATEGORIES)
                     + sum(1 for l in libs.values() if not l.get("detail"))
                     + sum(1 for r in rows.values() if r.get("usable") and r.get("detail") and not r.get("preview") and not r.get("preview_err") and len(r["id"].split("/")) == 2))
        made = marker() - marker0
        st["turn_progress"] = made
        st["idle_turns"] = 0 if made > 0 else int(st.get("idle_turns", 0)) + 1       # نوبتِ پشت‌سرِ هم بی‌پیشرفت ⇒ سرور نمی‌رسد؛ کارِ گره (crawl21.run) وارد می‌شود
        st.update(running=False, errors=errors[-20:], updated_at=c21st._now(), total=len(rows), libraries=len(libs), remaining=remaining,
                  finished=remaining == 0 and not blocked, blocked=blocked, requests=st.get("requests", 0) + s.requests,
                  refused=sorted(set(st.get("refused", []) + s.refused))[:30],
                  usable=sum(1 for r in rows.values() if r.get("usable")), previews=sum(1 for r in rows.values() if r.get("preview")))
        if st["finished"]:
            st["finished_at"] = c21st._now()
        c21st._save_state(st)
    return st


def recategorize_catalog() -> dict:
    """ردیف‌های با جزئیاتِ کاتالوگ دسته‌های تازه (TAG_ALIAS / واژه‌های عنوان) را می‌گیرند؛ فقط افزودن، هرگز حذف. نوشتنِ کاتالوگ فقط وقتی خزش/تبدیل ننوشته‌اند. ⇒ {changed, uncategorised}."""
    if c21st.is_running():
        return {"changed": 0, "deferred": True}
    rows = c21st.load()
    changed = 0
    for r in rows:
        if not r.get("detail"):
            continue
        new = infer_cats(r)
        if new != (r.get("cats") or []):
            r["cats"] = new
            changed += 1
    if changed:
        c21st.save(rows)
    return {"changed": changed, "uncategorised": sum(1 for r in rows if r.get("detail") and not r.get("cats"))}


STALL_TURNS = 3                      # نوبتِ پشت‌سرِ هم بی‌پیشرفت ⇒ سرور نمی‌رسد؛ گره (crawl21.run) کار را می‌گیرد


def needs_node(st: dict) -> bool:
    """وضعیتِ خزش ⇒ آیا کارِ گرهٔ GPU باید پر نگه داشته شود؟ (۴۰۳، robots.txt خوانده نشد، یا چند نوبتِ بی‌پیشرفت؛ و کاتالوگ هنوز تمام نشده)"""
    if not st or st.get("finished"):
        return False
    return bool(st.get("blocked") or not st.get("robots_ok", True) or int(st.get("idle_turns") or 0) >= STALL_TURNS)


def usable_without_preview(limit: int = 50) -> list[str]:
    """شناسهٔ قطعه‌هایی که مجوزِ آزاد دارند ولی هنوز پیش‌نمایش ندارند (کارِ گره از همین‌ها شروع می‌کند)."""
    out = []
    for r in c21st.load():
        if r.get("usable") and not r.get("preview") and len(r["id"].split("/")) == 2:
            out.append(r["id"])
            if len(out) >= limit:
                break
    return out

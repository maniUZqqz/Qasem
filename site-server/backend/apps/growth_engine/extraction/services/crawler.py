"""Reading one website: the home page, then the contact / about / support pages it links to.

All fetching goes through ``SafeFetcher`` (SSRF guard, robots.txt, per-host spacing, timeouts, GET-only
retries). The crawler never submits anything, never logs in, never follows an off-site redirect, and reads
at most ``EXTRACT_MAX_PAGES`` pages (the home page included; a refused or failed fetch counts too).

``crawl_site`` returns the merged findings plus a log entry for every page it tried, so what happened is
always visible in the panel.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from apps.growth_engine.core import conf
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.integrations import safe_http as sh

from . import parser
from .parser import CONF, CONTACT_PAGE_LABEL, SINGLE_VALUED, Finding, PageResult

logger = logging.getLogger(__name__)

#: tried (as budget allows) only when the home page links to no contact/about/support page at all
GUESS_PATHS = [("contact", "/contact"), ("contact", "/contact-us"), ("contact", "/contactus"), ("about", "/about"), ("about", "/about-us")]
_CATEGORY_ORDER = {"contact": 0, "about": 1, "support": 2}

ROBOTS_NOTES = {
    "ok": "robots.txt خوانده شد",
    "none": "robots.txt ندارد (همه‌چیز مجاز)",
    "disallow_all": "robots.txt دسترسی را بسته است",
    "unavailable": "robots.txt خوانده نشد؛ برای احتیاط رد شد",
    "off": "بررسیِ robots.txt خاموش است",
}


@dataclass
class PageLogEntry:
    url: str
    kind: str
    status: int = 0
    outcome: str = ""
    elapsed_ms: int = 0
    bytes: int = 0
    note: str = ""


@dataclass
class CrawlResult:
    status: str = "done"  # done | failed
    reason: str = ""  # "" | robots_blocked | robots_unavailable | fetch_failed | no_pages
    findings: list[Finding] = field(default_factory=list)
    logs: list[PageLogEntry] = field(default_factory=list)
    robots_state: str = ""
    home_url: str = ""
    pages_fetched: int = 0
    aborted: bool = False


# --------------------------------------------------------------------------- merging findings


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """One finding per (field, key) - the most trusted; for single-valued fields one per field.
    Ties keep the earlier one (the home page is parsed first)."""
    best: dict[tuple[str, str], Finding] = {}
    for f in findings:
        identity = (f.field, "" if f.field in SINGLE_VALUED else (f.key or f.value))
        current = best.get(identity)
        if current is None or f.confidence > current.confidence:
            best[identity] = f
    order = {"contact_form": 0, "phone": 1, "email": 2}
    return sorted(best.values(), key=lambda f: (order.get(f.field, 3), -f.confidence))


# --------------------------------------------------------------------------- page selection


def select_candidates(home: PageResult, home_url: str, budget: int) -> list[tuple[str, str]]:
    """[(url, category)] of up to ``budget`` same-host pages the home page links to, contact first."""
    seen = {home_url.rstrip("/")}
    scored: list[tuple[int, int, int, str, str]] = []
    for index, link in enumerate(home.links):
        if not parser.same_host(home_url, link.url):
            continue
        url = link.url.rstrip("/")
        classified = parser.classify_link(link.url, link.text)
        if not classified or url in seen:
            continue
        seen.add(url)
        category, score = classified
        scored.append((_CATEGORY_ORDER[category], -score, index, link.url, category))
    scored.sort()
    # at most two pages of a kind, so one noisy menu cannot eat the whole budget
    taken: dict[str, int] = {}
    chosen: list[tuple[str, str]] = []
    for _, _, _, url, category in scored:
        if taken.get(category, 0) >= 2 or len(chosen) >= budget:
            continue
        taken[category] = taken.get(category, 0) + 1
        chosen.append((url, category))
    return chosen


def guess_candidates(home_url: str, budget: int) -> list[tuple[str, str]]:
    parts = urlsplit(home_url)
    base = f"{parts.scheme}://{parts.netloc}"
    return [(base + path, category) for category, path in GUESS_PATHS[:budget]]


# --------------------------------------------------------------------------- the crawl


def _log_from_result(result: sh.FetchResult, kind: str, note: str = "") -> PageLogEntry:
    return PageLogEntry(
        url=(result.final_url or result.url)[:500], kind=kind, status=result.status, outcome=result.outcome,
        elapsed_ms=result.elapsed_ms, bytes=result.bytes_read, note=(note or ("" if result.ok else result.label))[:300],
    )


def crawl_site(
    website: str,
    fetcher: sh.SafeFetcher,
    *,
    max_pages: int | None = None,
    heartbeat: Callable[[], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> CrawlResult:
    """Read ``website`` and return what its own pages show. Never raises for network problems."""
    max_pages = max_pages or int(conf.get("EXTRACT_MAX_PAGES"))
    outcome = CrawlResult()
    try:
        clean = nz.clean_url(website)
    except nz.NormalizationError as exc:
        outcome.status, outcome.reason = "failed", "fetch_failed"
        outcome.logs.append(PageLogEntry(url=website[:500], kind="home", outcome=sh.BAD_URL, note=exc.message))
        return outcome
    start = clean.fetch_url
    outcome.home_url = clean.url
    shared_platform = nz._is_shared_platform(clean.host_ascii)

    home_fetch = fetcher.get_page(start)
    if heartbeat:
        heartbeat()
    # robots.txt state of this host (already cached by the fetch above; skipped when the address itself was refused)
    if home_fetch.outcome not in (sh.BAD_URL, sh.SSRF_BLOCKED, sh.BLOCKED_PORT, sh.DNS_ERROR):
        _, state = fetcher.robots_allows(start)
        outcome.robots_state = state
        parts = urlsplit(start)
        outcome.logs.append(
            PageLogEntry(url=f"{parts.scheme}://{parts.netloc}/robots.txt", kind="robots", outcome=state, note=ROBOTS_NOTES.get(state, state))
        )

    if not home_fetch.ok:
        outcome.logs.append(_log_from_result(home_fetch, "home"))
        outcome.status = "failed"
        if home_fetch.outcome == sh.ROBOTS_BLOCKED:
            outcome.reason = "robots_blocked"
        elif home_fetch.outcome == sh.ROBOTS_UNAVAILABLE:
            outcome.reason = "robots_unavailable"
        else:
            outcome.reason = "fetch_failed"
            if home_fetch.text and parser.looks_like_challenge(home_fetch.text, home_fetch.headers):
                outcome.logs[-1].note = "صفحهٔ چالشِ مرورگر (مثلاً Cloudflare)؛ محتوایی برای خواندن نیست"
        return outcome

    home = parser.parse_page(home_fetch.text, home_fetch.final_url or start, "home")
    if home.is_challenge:
        outcome.logs.append(_log_from_result(home_fetch, "home", "صفحهٔ چالشِ مرورگر (مثلاً Cloudflare)؛ محتوایی برای خواندن نیست"))
        outcome.status, outcome.reason = "failed", "fetch_failed"
        return outcome
    if home.is_app_shell:
        outcome.logs.append(_log_from_result(home_fetch, "home", "صفحه فقط پوستهٔ جاوااسکریپتی است؛ بدونِ اجرای جاوااسکریپت چیزی دیده نمی‌شود"))
        outcome.status, outcome.reason = "failed", "no_pages"
        outcome.pages_fetched = 1
        return outcome
    outcome.logs.append(_log_from_result(home_fetch, "home", f"{len(home.findings)} یافته"))
    outcome.pages_fetched = 1
    pages: list[PageResult] = [home]

    attempts = 1
    if not shared_platform:
        budget = max_pages - attempts
        candidates = select_candidates(home, home.url, budget)
        if not candidates:
            candidates = guess_candidates(home.url, budget)
            guessed = True
        else:
            guessed = False
        for url, category in candidates:
            if attempts >= max_pages:
                break
            if should_stop and should_stop():
                outcome.aborted = True
                break
            attempts += 1
            fetched = fetcher.get_page(url)
            if heartbeat:
                heartbeat()
            kind_label = "guess" if guessed else category
            if not fetched.ok:
                outcome.logs.append(_log_from_result(fetched, kind_label))
                continue
            page = parser.parse_page(fetched.text, fetched.final_url or url, category)
            if page.is_challenge or page.is_app_shell:
                note = "صفحهٔ چالش" if page.is_challenge else "پوستهٔ جاوااسکریپتی؛ چیزی دیده نشد"
                outcome.logs.append(_log_from_result(fetched, kind_label, note))
                continue
            outcome.logs.append(_log_from_result(fetched, kind_label, f"{len(page.findings)} یافته"))
            outcome.pages_fetched += 1
            pages.append(page)

    findings = [f for page in pages for f in page.findings]
    # a contact page with no form: worth keeping only when nothing better (a form or a ticket page) was found
    if not any(f.field == "contact_form" and f.confidence >= CONF["ticket_link"] for f in findings):
        for page in pages:
            if page.contact_page_without_form:
                key = value = parser.contact_form_key(page.url)
                findings.append(
                    Finding(field="contact_form", value=value, key=key, source_url=page.url, label=CONTACT_PAGE_LABEL,
                            confidence=CONF["contact_page_no_form"], evidence="صفحهٔ تماس؛ فرمی در آن دیده نشد")
                )
                break
    outcome.findings = merge_findings(findings)
    return outcome

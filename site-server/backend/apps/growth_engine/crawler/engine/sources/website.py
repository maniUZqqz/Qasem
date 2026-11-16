"""A business's own website as a source: follow its internal links to the contact / about pages and read what they say.

This is the step that turns «a name and a site» into «a name, a mobile number, an Instagram page, an address and opening hours».
It reuses the Growth Engine's contact parser (``extraction.services.parser``: phones with confidence tiers, e-mails, social
profile links, contact forms, JSON-LD, ``<address>``) and the page selection of ``extraction.services.crawler`` (the home page,
then at most two contact / two about / two support pages the home page links to - never an off-site link), and adds what a
mission needs on top: opening hours, a rating, the words the site uses (does it really look like a gym / a café?) and the
signals that say whether the business is a good customer for the mission's product.

Fetching is separate from reading: ``fetch_site`` gets the pages (here, through the robots-aware, cached ``WebClient``), and
``analyze_site`` reads a list of pages. The processing node's ``crawl.run`` job returns pages in the same shape, so a site read on the
node (or rendered there when it is a JavaScript shell) goes through the very same ``analyze_site``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.extraction.services import crawler as site_crawler
from apps.growth_engine.extraction.services import parser as contact_parser
from apps.growth_engine.integrations import safe_http as sh

from ... import presets
from .. import extras, textnorm
from ..candidates import Found
from .base import SourceContext, TaskFailed, TaskSpec

SOURCE = "website"
MIN_PHONE_CONF = 60
MIN_EMAIL_CONF = 65


@dataclass
class PageData:
    url: str
    kind: str  # home | contact | about | support | guess
    html: str = ""
    status: int = 0
    outcome: str = sh.OK
    note: str = ""
    rendered: bool = False


@dataclass
class SiteInfo:
    home_url: str = ""
    ok: bool = False
    reason: str = ""  # robots_blocked | robots_unavailable | fetch_failed | js_shell | challenge | no_pages | ""
    pages: list[dict] = field(default_factory=list)  # [{url, kind, status, outcome, note, findings}]
    fields: dict = field(default_factory=dict)  # phones, emails, instagram, ... (validated by the candidate merge, not here)
    meta: dict = field(default_factory=dict)
    words: list[str] = field(default_factory=list)
    fit_words: list[str] = field(default_factory=list)
    hours: str = ""
    rating: float | None = None
    js_shell: bool = False
    robots: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("home_url", "ok", "reason", "pages", "fields", "meta", "words", "fit_words", "hours", "rating", "js_shell", "robots")}


# --------------------------------------------------------------------------- fetching (on the server)


def fetch_site(web, url: str, *, max_pages: int = 5, stop=None) -> tuple[list[PageData], str]:
    """The home page and the contact / about pages it links to. Returns ``(pages, robots_state)``; a page that could not be read
    is still returned (with its outcome) so the log can say why."""
    try:
        clean = nz.clean_url(url)
    except nz.NormalizationError as exc:
        return [PageData(url=url[:300], kind="home", outcome=sh.BAD_URL, note=exc.message)], ""
    start = clean.fetch_url
    pages: list[PageData] = []
    home = web.page(start)
    robots = ""
    if home.outcome not in (sh.BAD_URL, sh.SSRF_BLOCKED, sh.BLOCKED_PORT, sh.DNS_ERROR):
        _, robots = web.fetcher.robots_allows(start)
    pages.append(PageData(url=home.final_url or start, kind="home", html=home.text if home.ok else "", status=home.status, outcome=home.outcome, note="" if home.ok else home.label))
    if not home.ok or nz._is_shared_platform(clean.host_ascii):
        return pages, robots
    parsed = contact_parser.parse_page(home.text, home.final_url or start, "home")
    if parsed.is_challenge or parsed.is_app_shell:
        return pages, robots
    budget = max_pages - 1
    chosen = site_crawler.select_candidates(parsed, parsed.url, budget)
    guessed = not chosen
    if guessed:
        chosen = site_crawler.guess_candidates(parsed.url, min(budget, 2))
    for url2, category in chosen:
        if stop and stop():
            break
        res = web.page(url2)
        pages.append(PageData(url=res.final_url or url2, kind="guess" if guessed else category, html=res.text if res.ok else "", status=res.status, outcome=res.outcome, note="" if res.ok else res.label))
    return pages, robots


# --------------------------------------------------------------------------- reading (shared with the node's pages)


def analyze_site(pages: list[PageData], *, home_url: str, type_words: list[str], fit_words: list[str], robots: str = "") -> SiteInfo:
    info = SiteInfo(home_url=home_url, robots=robots)
    findings = []
    texts: list[str] = []
    hours = ""
    rating = None
    for page in pages:
        log = {"url": page.url[:300], "kind": page.kind, "status": page.status, "outcome": page.outcome, "note": page.note, "findings": 0}
        info.pages.append(log)
        if page.outcome != sh.OK or not page.html:
            if page.kind == "home":
                info.reason = {sh.ROBOTS_BLOCKED: "robots_blocked", sh.ROBOTS_UNAVAILABLE: "robots_unavailable"}.get(page.outcome, "fetch_failed")
            continue
        parsed = contact_parser.parse_page(page.html, page.url, page.kind if page.kind in ("home", "contact", "about", "support") else "contact")
        if parsed.is_challenge:
            log["note"] = "صفحهٔ چالشِ مرورگر"
            if page.kind == "home":
                info.reason = "challenge"
            continue
        if parsed.is_app_shell and not page.rendered:
            log["note"] = "پوستهٔ جاوااسکریپتی"
            info.js_shell = True
            if page.kind == "home":
                info.reason = "js_shell"
            continue
        log["findings"] = len(parsed.findings)
        findings.extend(parsed.findings)
        if page.kind == "home":
            info.meta = extras.page_meta(page.html)
        text = extras.visible_text(page.html, 14_000)
        texts.append(text)
        if not hours:
            hours = extras.find_hours(page.html, text)
        if rating is None:
            rating = extras.find_rating(text)
    merged = site_crawler.merge_findings(findings)
    by: dict[str, list] = {}
    for f in merged:
        by.setdefault(f.field, []).append(f)
    info.fields = {
        "phones": [f.value for f in by.get("phone", []) if f.confidence >= MIN_PHONE_CONF],
        "emails": [f.value for f in by.get("email", []) if f.confidence >= MIN_EMAIL_CONF],
        "instagram": (by.get("instagram") or [None])[0].value if by.get("instagram") else "",
        "telegram": (by.get("telegram") or [None])[0].value if by.get("telegram") else "",
        "whatsapp": [f.value for f in by.get("whatsapp", [])],
        "contact_form": (by.get("contact_form") or [None])[0].value if by.get("contact_form") else "",
        "address": (by.get("address") or [None])[0].value if by.get("address") else "",
        "city": (by.get("city") or [None])[0].value if by.get("city") else "",
        "business_name": (by.get("business_name") or [None])[0].value if by.get("business_name") else "",
        "language": (by.get("language") or [None])[0].value if by.get("language") else "",
    }
    blob = "\n".join(texts + [info.meta.get("title", ""), info.meta.get("description", "")])
    info.words = extras.find_words(blob, type_words)
    info.fit_words = extras.find_words(blob, fit_words)
    info.hours, info.rating = hours, rating
    info.ok = bool(texts)
    if info.ok:
        info.reason = ""
    elif not info.reason:
        info.reason = "no_pages"
    return info


# --------------------------------------------------------------------------- applying to a candidate


def words_for(types: list[str], spec: dict) -> tuple[list[str], list[str]]:
    words: list[str] = []
    fit: list[str] = []
    for key in types:
        bt = presets.get_type(key)
        if bt:
            words += list(bt.words)
            fit += list(bt.fit_words)
    words += [str(k) for k in (spec.get("keywords") or [])]
    return list(dict.fromkeys(words)), list(dict.fromkeys(fit))


def apply_to_candidate(c, info: SiteInfo) -> bool:
    """Write what the site said into the candidate (fill-only; nothing found = nothing changed). Returns True when it changed."""
    from ..candidates import _apply, strong_keys, _register_keys

    f = info.fields
    found = Found(
        name=c.name, source=SOURCE, ref=f"website:{textnorm.domain_key(c.website)}"[:120], url=info.home_url, city=f.get("city", ""), address=f.get("address", ""),
        phones=f.get("phones", []), emails=f.get("emails", []), whatsapp=f.get("whatsapp", []), instagram=f.get("instagram", ""), telegram=f.get("telegram", ""),
        contact_form=f.get("contact_form", ""), hours=info.hours, rating=info.rating,
        signals={"site": {"title": info.meta.get("title", "")[:160], "description": info.meta.get("description", "")[:300], "lang": f.get("language") or info.meta.get("lang", ""),
                          "words": info.words, "fit_words": info.fit_words, "pages": len([p for p in info.pages if p.get("outcome") == sh.OK]),
                          "js_shell": info.js_shell, "robots": info.robots, "reason": info.reason}},
    )
    from ..candidates import clean_found

    found = clean_found(found)
    changed = _apply(c, found)
    c.enriched = True
    c.save()
    _register_keys(c, strong_keys(c))
    return changed


# --------------------------------------------------------------------------- the task


def task_for(candidate, priority: int = 50, kind: str = "site") -> TaskSpec:
    from urllib.parse import urlsplit

    host = urlsplit(candidate.website).hostname or candidate.website
    return TaskSpec(source=SOURCE, kind=kind, key=f"{kind}:{candidate.pk}", stage="enrich", priority=priority, label=f"سایت: {host}",
                    params={"candidate_id": candidate.pk, "url": candidate.website})


def execute(task, ctx: SourceContext) -> dict:
    from ...models import CrawlCandidate

    cand = CrawlCandidate.objects.filter(pk=task.params.get("candidate_id"), run_id=ctx.run.pk).first()
    if cand is None or not cand.website:
        raise TaskFailed("نامزد یا آدرسِ سایتش پیدا نشد.")
    max_pages = ctx.budget("max_pages_per_site", 5)
    pages, robots = fetch_site(ctx.web, cand.website, max_pages=max_pages, stop=ctx.stop)
    type_words, fit = words_for(list(cand.types or ctx.types()), ctx.spec)
    info = analyze_site(pages, home_url=cand.website, type_words=type_words, fit_words=fit, robots=robots)
    if info.ok or info.js_shell:
        apply_to_candidate(cand, info)
    else:
        cand.signals = {**(cand.signals or {}), "site": {"reason": info.reason, "pages": 0}}
        cand.enriched = True
        cand.save(update_fields=["signals", "enriched"])
    result = {"ok": info.ok, "reason": info.reason, "pages": len(info.pages), "phones": len(info.fields.get("phones", [])), "emails": len(info.fields.get("emails", [])),
              "instagram": bool(info.fields.get("instagram")), "hours": bool(info.hours), "js_shell": info.js_shell}
    if info.js_shell and not info.ok and ctx.node_available:
        ctx.add_tasks([TaskSpec(source=SOURCE, kind="node_site", key=f"node_site:{cand.pk}:render", stage="node", priority=70, label=f"سایتِ جاوااسکریپتی (رندر روی سرورِ پردازش): {cand.website[:60]}",
                                params={"candidate_id": cand.pk, "url": cand.website, "render": "always"})])
        result["queued_render"] = True
    return result

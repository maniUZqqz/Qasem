"""A public directory of sports coaches (morabiyab.com) - where the finder looks for PERSONAL TRAINERS.

Why this exists: personal trainers are not on any map and a web search for them returns noise from this server (checked 2026-11-17: Bing
answers a Persian «مربی بدنسازی تهران» with music pages and school quizzes). A coach directory is the one open place where a trainer
publishes, on purpose, how to reach him or her for work.

What is allowed and what is taken (robots.txt of the site: «Disallow: /wp-admin/» only; every request still goes through the finder's own robots
check, delay and budget):

* the LIST pages ``/all-coaches/?my_page=N`` (a card = name, specialties, «province، city», mode: online / in person / both);
* the PROFILE page of a coach who fits the mission (his / her city, or online when the mission includes online coaches, and a fitness
  specialty). From the profile only the block «ارتباط با مربی» (``aside.coach-contact-panel``) is read: the phone, WhatsApp, Instagram and
  Telegram the coach entered in the directory to be contacted for work. The directory's own footer (its support number, its own Instagram)
  is NOT read, and it is removed again by the generic boilerplate rule if it ever slips in.
* nothing else: no gallery photo, no home address (a coach's «gym address» line is a business address and is not stored either), no comment.

The data is a coach's self-published BUSINESS contact; it stays a draft source for a person to contact with an approved message (opt-out
sentence included), exactly like every other lead.

An independent coach IS his or her own business, so the person's name and professional contact lines are the business's data - and are handled as
personal data: the lead is tagged «فردِ مستقل» (filter / bulk-remove it), the panel says so, no name is written to the run diary or the task list
(only the directory's profile number), a mission can switch these coaches off (``include_individuals``), and the «تماس نگیر» list and the SMS
opt-out are checked before any draft exists.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from apps.growth_engine.core import normalization as nz

from .. import place, textnorm
from ..candidates import Found
from .base import SourceContext, TaskFailed, TaskSpec

SOURCE = "directory"
DIRECTORY = "morabiyab"
HOST = "morabiyab.com"
LIST_URL = f"https://{HOST}/all-coaches/"
#: a coach whose specialties name none of these (a tai-chi or a dance teacher) is not a fitness coach
FITNESS_WORDS = ("بدنسازی", "فیتس", "فیتنس", "قدرتی", "حرکتی", "کراس", "trx", "فانکشنال", "آمادگی", "تناسب", "چربی", "لاغری", "تغذیه", "وزن", "عضل", "پیلاتس", "یوگا",
                 "اصلاحی", "استقامت", "هوازی", "کالیستنیکس", "تمرین")
MAX_PAGES = 12
ONLINE = "آنلاین"


def list_url(page: int = 1) -> str:
    return LIST_URL if page <= 1 else f"{LIST_URL}?my_page={page}"


def plan(spec: dict) -> list[TaskSpec]:
    """One task for the first list page; it plans the other pages and the profiles by itself."""
    if "personal_trainer" not in (spec.get("business_types") or []) or not spec.get("include_individuals", True):
        return []
    return [TaskSpec(source=SOURCE, kind="list", key=f"dir:{list_url(1)}", priority=22, label="مربی‌یاب: فهرستِ مربی‌ها",
                     params={"url": list_url(1), "directory": DIRECTORY, "types": ["personal_trainer"], "page": 1})]


# --------------------------------------------------------------------------- parsing


def _mode_of(text: str) -> str:
    t = nz.normalize_text(text)
    online, inperson = ONLINE in t, "حضوری" in t
    return "both" if online and inperson else "online" if online else "in_person" if inperson else ""


def parse_cards(html: str, base: str = f"https://{HOST}") -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    cards: list[dict] = []
    for art in soup.select("article.coach-card"):
        a = art.select_one("h3 a[href]")
        if not a:
            continue
        paras = [nz.normalize_text(p.get_text(" ", strip=True)) for p in art.find_all("p")]
        specialties = paras[0] if paras else ""
        loc = paras[1] if len(paras) > 1 else ""
        mode = _mode_of(paras[2]) if len(paras) > 2 else ""
        province, _, city = loc.partition("،")
        url = a["href"]
        cards.append({"id": art.get("data-coach-id", ""), "name": nz.normalize_text(a.get_text(" ", strip=True)), "url": url if url.startswith("http") else base + url,
                      "specialties": specialties, "province": nz.normalize_text(province), "city": nz.normalize_text(city) or nz.normalize_text(province), "mode": mode})
    return cards


def last_page(html: str) -> int:
    pages = [1]
    for a in BeautifulSoup(html or "", "html.parser").select("nav.pagination a[href], .directory-pagination a[href]"):
        got = parse_qs(urlsplit(a["href"]).query).get("my_page")
        if got and got[0].isdigit():
            pages.append(int(got[0]))
    return min(max(pages), MAX_PAGES)


def fitness_coach(specialties: str) -> bool:
    return bool(textnorm.name_has_word(specialties, FITNESS_WORDS))


def wanted_card(card: dict, spec: dict) -> str:
    """Why a coach is wanted: ``city`` (his / her city is one of the mission's), ``online`` (an online coach, and the mission takes online coaches), or '' (not wanted)."""
    if not fitness_coach(card["specialties"]):
        return ""
    cities = {place.canonical_city(c) for c in (spec.get("cities") or []) if c}
    here = place.canonical_city(card["city"])
    if not cities or here in cities:
        return "city"
    return "online" if spec.get("include_online") and card["mode"] in ("online", "both") else ""


BADGE = "تایید و توصیه"  # the directory's «verified by our team» badge sits inside the page's <h1>, after the coach's name


def _h1_name(h1) -> str:
    """The coach's name from the page's <h1>: without its icons / badge (the badge text is the directory's, not part of the name)."""
    for tag in h1.find_all(["span", "svg", "i", "img"]):
        tag.decompose()
    text = nz.normalize_text(h1.get_text(" ", strip=True))
    return nz.normalize_text(text.split(BADGE)[0])


def parse_profile(html: str, url: str, card: dict | None = None) -> Found | None:
    """The coach's own contact block -> one ``Found``. None when the page has no coach name."""
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    name = (card or {}).get("name") or (_h1_name(h1) if h1 else "")  # the list card's name is the cleanest (just the link text)
    if not name:
        return None
    panel = soup.select_one("aside.coach-contact-panel")
    phones: list[str] = []
    whatsapp: list[str] = []
    instagram = telegram = ""
    if panel is not None:
        for a in panel.find_all("a", href=True):
            href = a["href"].strip()
            kind = (a.get("data-coach-contact") or "").lower()
            if href.lower().startswith("tel:") or kind == "phone":
                phones.append(href[4:] if href.lower().startswith("tel:") else a.get_text(strip=True))
            elif "wa.me/" in href or kind == "whatsapp":
                m = re.search(r"wa\.me/\+?(\d{8,15})", href)
                if m:
                    whatsapp.append("+" + m.group(1))
            elif "instagram.com/" in href or kind == "instagram":
                instagram = instagram or href
            elif "t.me/" in href or kind == "telegram":
                telegram = telegram or href
    card = card or {}
    return Found(
        name=name, source=SOURCE, ref=f"directory:{DIRECTORY}:{card.get('id') or textnorm.domain_key(url)}"[:120], url=url, category="مربی", types=["personal_trainer"],
        city=card.get("city", ""), city_src="evidence" if card.get("city") and not card.get("via_online") else "", phones=phones, whatsapp=whatsapp, instagram=instagram,
        telegram=telegram,
        signals={"directory": DIRECTORY, "dir_host": HOST, "individual": True, "coach": {"specialties": card.get("specialties", "")[:200], "mode": card.get("mode", "")},
                 **({"place_free": True} if card.get("via_online") else {})},  # an online coach is wanted for being online, wherever he or she lives
    )


# --------------------------------------------------------------------------- running


def execute(task, ctx: SourceContext) -> dict:
    from . import directory

    if task.kind == "list":
        return _list(task, ctx, directory)
    if task.kind == "detail":
        return _detail(task, ctx, directory)
    raise TaskFailed("نوعِ کارِ فهرستِ مربی‌ها شناخته نشد.")


def _list(task, ctx: SourceContext, directory) -> dict:
    p = task.params
    result = directory._fetch(ctx, p["url"])
    cards = parse_cards(result.text)
    page = int(p.get("page") or 1)
    follow: list[TaskSpec] = []
    if page == 1:
        for n in range(2, last_page(result.text) + 1):
            follow.append(TaskSpec(source=SOURCE, kind="list", key=f"dir:{list_url(n)}", priority=23, label=f"مربی‌یاب: صفحهٔ {n}",
                                   params={"url": list_url(n), "directory": DIRECTORY, "types": ["personal_trainer"], "page": n}))
    keep = []
    for c in cards:
        why = wanted_card(c, ctx.spec)
        if why:
            keep.append({**c, "via_online": why == "online"})
    max_details = ctx.budget("max_directory_details", 120)
    for c in keep[:max_details]:
        # the task label (shown in the panel and the diary) never carries the coach's name: only the directory's own number
        follow.append(TaskSpec(source=SOURCE, kind="detail", key=f"dir:{c['url']}", priority=60, label=f"مربی‌یاب: پروفایلِ شمارهٔ {c.get('id') or '؟'}", stage="discover",
                               params={"url": c["url"], "directory": DIRECTORY, "types": ["personal_trainer"], "card": c}))
    ctx.add_tasks(follow)
    return {"cards": len(cards), "kept": len(keep), "detail_tasks": min(len(keep), max_details), "new_candidates": 0}


def _detail(task, ctx: SourceContext, directory) -> dict:
    p = task.params
    result = directory._fetch(ctx, p["url"])
    found = parse_profile(result.text, result.final_url or p["url"], p.get("card"))
    if found is None:
        return {"found": False}
    _, created = ctx.emit(found)
    return {"found": True, "new_candidates": 1 if created else 0, "has_phone": bool(found.phones or found.whatsapp), "has_instagram": bool(found.instagram)}

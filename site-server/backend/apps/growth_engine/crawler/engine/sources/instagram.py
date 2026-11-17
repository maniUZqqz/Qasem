"""Instagram business pages: FINDING them by hashtag and location, and READING them with Abagram on the processing node (the existing ``ig.scrape`` job kind).

Where the handles come from:

* the mission's own **hashtags** and **locations** (neighbourhoods, areas, cities): each becomes a ``site:instagram.com`` query asked of the web
  search engines that can answer it (``search.ask``). Instagram itself is never searched and no hashtag / location page of it is opened: those
  pages need a signed-in session and one page view per post to learn who posted, which would load the owner's account for little. The public web
  index already shows the profile's name, bio line and (often) its public follower count, so a profile found this way is a candidate at once;
* the map (OpenStreetMap ``contact:instagram``), business websites (their «Instagram» link), directories (the coach directory) and web search
  (a result that IS an Instagram profile).

What the node adds: Abagram reads the PUBLIC profile page of a business (name, bio, category, public follower count) with the pauses and limits
it has built in, and stops at the first sign of trouble. The owner signs Abagram in once on the node (documented in the panel); until then the job
waits in the durable queue, and ``ig.health`` tells the panel exactly what is missing. No followers / following list is read and nothing is posted.

What is kept: the bio's phone numbers / e-mails / website (a business's own public contact lines), the category and the public numbers. The posts the
batch also carries are ignored here (they belong to the trends feature).
"""
from __future__ import annotations

import re

from apps.growth_engine.core import normalization as nz

from ... import presets
from .. import extras, place
from ..candidates import Found, _apply, _register_keys, clean_found, strong_keys
from .base import SourceContext, TaskFailed, TaskSpec

SOURCE = "instagram"
KIND = "ig.scrape"
MAX_PER_JOB = 12


def handle_of(candidate) -> str:
    if not candidate.instagram:
        return ""
    try:
        return nz.parse_instagram(candidate.instagram).handle
    except nz.NormalizationError:
        return ""


def task_for(candidate, priority: int = 80) -> TaskSpec:
    handle = handle_of(candidate)
    # an independent person's handle is an identifier of that person: the panel and the diary say only «a page», the job itself carries the handle
    label = "پیجِ اینستاگرام: یک مربیِ مستقل" if (candidate.signals or {}).get("individual") else f"پیجِ اینستاگرام: @{handle}"
    return TaskSpec(source=SOURCE, kind="ig_profile", key=f"ig:{handle}", stage="ig", priority=priority, label=label,
                    params={"candidate_id": candidate.pk, "handle": handle})


def build_payload(handles: list[str], run_id: int) -> dict:
    return {"accounts": handles, "max_accounts": len(handles), "pace_s": [45, 110], "fresh": False, "posts_per_account": 3, "run_id": run_id,
            "purpose": "growth_crawler"}


def timeout_for(n: int) -> int:
    return n * (300 + 110) + 600


def apply_account(c, account: dict) -> bool:
    """Write one account of an ``nm-ig-batch`` into the candidate. ``account`` is already cleaned by the node module."""
    bio = str(account.get("biography") or "")
    found = extras.contacts_in_text(bio)
    sig = {
        "followers": account.get("followers"), "following": account.get("following"), "posts": account.get("posts_count"),
        "verified": bool(account.get("is_verified")), "is_business": bool(account.get("is_business")), "private": bool(account.get("is_private")),
        "category": str(account.get("category") or "")[:80], "bio": bio[:300], "full_name": str(account.get("full_name") or "")[:120], "from": "node",
    }
    f = clean_found(Found(
        name=c.name, source=SOURCE, ref=f"ig:{account.get('username', '')}"[:120], url=f"https://www.instagram.com/{account.get('username', '')}/",
        phones=found["phones"], emails=found["emails"], whatsapp=found["whatsapp"], website=(found["websites"] or [""])[0],
        telegram=(f"https://t.me/{found['telegram'][0]}" if found["telegram"] else ""), signals={"ig": sig},
    ))
    if (not c.name or c.name == handle_of(c)) and sig["full_name"]:
        c.name = sig["full_name"]
    changed = _apply(c, f)
    c.save()
    _register_keys(c, strong_keys(c))
    return changed


# --------------------------------------------------------------------------- finding profiles by hashtag and location

DISCOVER = "discover"
MAX_QUERIES = 6


def clean_term(text: str) -> str:
    """«#مربی_بدنسازی» -> «مربی بدنسازی»; «#TehranFitness» -> «TehranFitness»."""
    return nz.normalize_text(re.sub(r"[#_]+", " ", text or "")).strip()


def plan(spec: dict) -> list[TaskSpec]:
    """One task per (hashtag or location) query, the cities sharing the budget. Without hashtags and locations the mission's own business types are the hashtags."""
    if not (spec.get("sources") or {}).get("instagram"):
        return []
    limit = int((spec.get("budget") or {}).get("max_ig_queries") if (spec.get("budget") or {}).get("max_ig_queries") is not None else MAX_QUERIES)
    if limit <= 0:
        return []
    cities = [c for c in spec.get("cities", []) if c] or [""]
    types = [presets.get_type(t) for t in spec.get("business_types", []) if presets.get_type(t)]
    keys = [t.key for t in types]
    type_words = [w for t in types for w in (*t.words, *t.terms_fa)] or [clean_term(k) for k in (spec.get("keywords") or []) if clean_term(k)]
    tags = [clean_term(t) for t in (spec.get("ig_hashtags") or []) if clean_term(t)]
    places = [clean_term(t) for t in (spec.get("ig_locations") or []) if clean_term(t)]
    if not tags and not places:
        tags = [bt.terms_fa[0] for bt in types if bt.terms_fa][:2] + [clean_term(k) for k in (spec.get("keywords") or [])[:2]]
    seen: set[str] = set()
    lanes: list[list[dict]] = []

    def add(lane: list[dict], query: str, **params) -> None:
        q = nz.normalize_text(query)
        if q and q not in seen:
            seen.add(q)
            lane.append({"query": q, "types": keys, "lang": "fa", **params})

    tag_lane: list[dict] = []
    for tag in tags:
        for city in cities:  # the cities share the budget: every city gets the first hashtag before any city gets the second
            add(tag_lane, f'site:instagram.com "{tag}" {city}'.strip(), kind="hashtag", term=tag, city=city, words=[*tag.split(), *type_words])
    place_lane: list[dict] = []
    for loc in places:
        canon = place.canonical_city(loc)
        city = canon if canon in place.CITY_CENTERS else (cities[0] if len([c for c in cities if c]) == 1 else "")
        for bt in types or [None]:
            term = bt.terms_fa[0] if bt is not None and bt.terms_fa else ""
            add(place_lane, f'site:instagram.com "{term}" "{loc}"'.replace('"" ', ""), kind="location", term=loc, city=city, words=type_words)
    lanes = [tag_lane, place_lane]
    merged: list[dict] = []
    for i in range(max((len(x) for x in lanes), default=0)):
        merged += [x[i] for x in lanes if i < len(x)]
    out = []
    for q in merged[:limit]:
        label = ("هشتگِ «#" + q["term"].replace(" ", "_") + "»" if q["kind"] == "hashtag" else "مکانِ «" + q["term"] + "»") + (f" · {q['city']}" if q.get("city") else "")
        out.append(TaskSpec(source=SOURCE, kind=DISCOVER, key=f"igd:{nz.search_key(q['query'])}"[:380], stage="discover", priority=32, label=f"پیج‌های اینستاگرام: {label}", params=q))
    return out


def execute(task, ctx: SourceContext) -> dict:
    """Ask the search engines for public profiles of this hashtag / location and take the relevant ones (``search.take_hits``)."""
    from . import search

    if task.kind != DISCOVER:
        raise TaskFailed("نوعِ کارِ اینستاگرام شناخته نشد.")
    p = task.params
    hits, used, problems = search.ask(ctx, p["query"], persian=bool(re.search(r"[\u0600-\u06ff]", p["query"])), site_op=True)
    label = task.label.replace("پیج‌های اینستاگرام: ", "")
    if not hits:
        search.say_no_hits(ctx, label, problems)
        return {"engine": "", "problems": problems, "results": 0, "note": "هیچ موتورِ جست‌وجویی نتیجه نداد"}
    out = search.take_hits(ctx, p, hits, used)
    ctx.log("info", f"{label} ({search.ENGINES[used]['label']}): {len(hits)} نتیجه، {out['relevant']} پیجِ مرتبط.")
    return {"engine": used, "problems": problems, "results": len(hits), **out}

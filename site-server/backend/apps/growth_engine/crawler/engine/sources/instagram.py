"""Instagram business pages, read by Abagram on the processing node (the existing ``ig.scrape`` job kind).

Where the handles come from: the map (OpenStreetMap ``contact:instagram``), business websites (their «Instagram» link), directories and
the web search (a result that IS an Instagram profile). Nothing is searched on Instagram itself, no followers / following list is read and
nothing is posted: Abagram reads the PUBLIC profile page of a business (name, bio, category, public follower count) with the pauses and limits
it has built in, and stops at the first sign of trouble. The owner signs Abagram in once on the node (documented in the panel); until then
the job waits in the durable queue, and ``ig.health`` tells the panel exactly what is missing.

What is kept: the bio's phone numbers / e-mails / website (a business's own public contact lines), the category and the public numbers. The
posts the batch also carries are ignored here (they belong to the trends feature).
"""
from __future__ import annotations

from apps.growth_engine.core import normalization as nz

from .. import extras
from ..candidates import Found, _apply, _register_keys, clean_found, strong_keys
from .base import TaskSpec

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
    return TaskSpec(source=SOURCE, kind="ig_profile", key=f"ig:{handle}", stage="ig", priority=priority, label=f"پیجِ اینستاگرام: @{handle}",
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
        "category": str(account.get("category") or "")[:80], "bio": bio[:300], "full_name": str(account.get("full_name") or "")[:120],
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

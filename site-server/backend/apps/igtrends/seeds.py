"""What a store watches: pages (scanned), hashtags and keywords (the niche's vocabulary). Editable in the panel.

**The starter pack is a starting point, not a verdict.** The hashtags and keywords are ordinary Persian words of the fitness / coaching /
gym niche (nothing factual). The pages are well-known **public** fitness pages that exist; a page that does not exist or was renamed is
switched off by itself after two «not found» answers. They are international because inventing Persian page names that cannot be
checked from here would only waste the scan budget — add the Persian pages you follow in the panel (or import an Abagram export).

Abagram reads pages, not hashtag feeds: a hashtag seed is used to recognise the niche in captions and to rank topics, it is not
scanned by itself.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import normalize, textproc
from .models import IgSeed, IgStoreConfig

DEFAULT_HASHTAGS = [
    "بدنسازی", "تناسب_اندام", "فیتنس", "باشگاه", "مربی_بدنسازی", "مربی_ورزشی", "برنامه_تمرینی", "برنامه_غذایی", "رژیم_غذایی",
    "کاهش_وزن", "چربی_سوزی", "عضله_سازی", "تمرین_در_خانه", "ورزش_در_خانه", "پروتئین", "حرکات_کششی", "تمرین_پا", "تمرین_سینه",
    "تمرین_شکم", "مکمل_ورزشی", "آمادگی_جسمانی", "کراس_فیت", "یوگا", "دویدن", "انگیزه_ورزشی",
]
DEFAULT_KEYWORDS = ["برنامه تمرینی", "مربی", "باشگاه", "رژیم", "لاغری", "عضله", "پروتئین", "تمرین", "ورزش", "فیتنس", "بدنسازی", "شکم", "اضافه وزن"]
DEFAULT_ACCOUNTS = [
    ("jeffnippard", "آموزشِ علمیِ بدنسازی"), ("athleanx", "تمرین و پیشگیری از آسیب"), ("chloe_ting", "تمرین در خانه"),
    ("kayla_itsines", "برنامهٔ تمرینی بانوان"), ("thebodycoach", "تمرین و آشپزی ساده"), ("whitneyysimmons", "بدنسازی و سبک زندگی"),
]
STARTER_NOTE = "نمونهٔ اولیه؛ صفحه‌های فارسی‌زبانِ خودتان را اضافه کنید"
#: a shop's OWN page, so its posts can be compared with the niche (only for the shop it belongs to). The user name is the one the public
#: site of Chagher links to (docs/chagher/brand-facts-fa.md says it is unconfirmed): a wrong name switches itself off after two answers.
OWN_PAGES = {"چغر": ("cheg_her", "صفحهٔ خودِ چغر (نامِ کاربری از لینکِ سایت؛ تأیید نشده)"),
             "chagher": ("cheg_her", "صفحهٔ خودِ چغر (نامِ کاربری از لینکِ سایت؛ تأیید نشده)")}

#: the first seed pack is chosen by the shop's own words; this list says when to use the fitness one
FITNESS_WORDS = ("ورزش", "باشگاه", "بدنسازی", "فیتنس", "مربی", "تمرین", "تناسب", "gym", "fitness", "coach", "چغر")


def looks_like_fitness(store) -> bool:
    text = " ".join([getattr(store, "name", "") or "", getattr(store, "business_type", "") or ""]).lower()
    return any(w in text for w in FITNESS_WORDS)


def clean_value(kind: str, value: str) -> str:
    v = str(value or "").strip()
    if kind == IgSeed.Kind.ACCOUNT:
        v = v.rstrip("/").rsplit("/", 1)[-1] if "instagram.com/" in v else v
        v = v.lstrip("@").lower()
        return v if normalize.USERNAME_RE.match(v) else ""
    if kind == IgSeed.Kind.HASHTAG:
        v = textproc.normalize(v.lstrip("#")).replace(" ", "_").strip("_")
        return v[:80] if v and "/" not in v else ""
    v = textproc.normalize(v)
    return v[:80]


def add_seed(store, kind: str, value: str, note: str = "", source: str = "user") -> tuple[IgSeed | None, bool]:
    value = clean_value(kind, value)
    if not value:
        return None, False
    seed, created = IgSeed.objects.get_or_create(store=store, kind=kind, value=value, defaults={"note": note[:200], "source": source})
    if not created and (not seed.enabled or (kind == IgSeed.Kind.ACCOUNT and not seed.scrape and source == "user")):
        seed.enabled = True
        if kind == IgSeed.Kind.ACCOUNT:
            seed.scrape, seed.fail_count = True, 0
        seed.save()
    return seed, created


def apply_defaults(store, force: bool = False) -> int:
    """The starter pack for this kind of shop, once (or again with force). Returns how many seeds were added."""
    cfg, _ = IgStoreConfig.objects.get_or_create(store=store)
    if cfg.seeded and not force:
        return 0
    added = 0
    if looks_like_fitness(store) or force:
        for tag in DEFAULT_HASHTAGS:
            added += add_seed(store, IgSeed.Kind.HASHTAG, tag, source="default")[1]
        for word in DEFAULT_KEYWORDS:
            added += add_seed(store, IgSeed.Kind.KEYWORD, word, source="default")[1]
        for name, note in DEFAULT_ACCOUNTS:
            added += add_seed(store, IgSeed.Kind.ACCOUNT, name, note="%s — %s" % (note, STARTER_NOTE), source="default")[1]
        text = (getattr(store, "name", "") or "").lower()
        for word, (name, note) in OWN_PAGES.items():
            if word in text:
                added += add_seed(store, IgSeed.Kind.ACCOUNT, name, note=note, source="default")[1]
                break
    cfg.seeded = True
    cfg.save(update_fields=["seeded", "updated_at"])
    return added


def due_accounts(store, now=None, limit: int | None = None, force: bool = False) -> list[str]:
    """Pages to read now: never read first, then the longest unread; not read again within the store's minimum gap; not pages that
    kept failing."""
    now = now or timezone.now()
    cfg, _ = IgStoreConfig.objects.get_or_create(store=store)
    gap = timedelta(hours=cfg.min_reread_h)
    seeds = IgSeed.objects.filter(store=store, kind=IgSeed.Kind.ACCOUNT, enabled=True, scrape=True, fail_count__lt=4)
    rows = [s for s in seeds if force or s.last_read_at is None or now - s.last_read_at >= gap]
    rows.sort(key=lambda s: (s.last_read_at is not None, s.last_read_at or now, s.value))
    names = [s.value for s in rows]
    return names[:limit] if limit else names

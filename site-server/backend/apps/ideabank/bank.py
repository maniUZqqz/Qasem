"""بانکِ ایده: ایده‌های آماده (کد) + ایده‌های خودِ فروشگاه (دیتابیس)، جست‌وجو و فیلتر، ستاره، پنهان، کپی، «ایده بساز» و شمارندهٔ استفاده.

SOURCE: ported from InstAI:instai/ideabank/bank.py @ 2f8aa90, adapted for store content ideas — همهٔ ایده‌ها به یک فروشگاه بسته‌اند (ستاره،
پنهان و استفاده برای هر فروشگاه جداست)، فقط فارسی، دسته‌ها و قالب‌ها تازه، و ایده‌ها قالبِ «جای‌گیردار» هستند که از پروفایلِ فروشگاه پر می‌شوند.

یک ایده: عنوان، یک‌جمله‌ای (logline)، قلاب (جملهٔ اولِ محتوا)، «چه چیزی فیلم/عکس بگیریم» (shoot)، دعوت به اقدام (cta)، قالب (ریلز/کاروسل/عکس/استوری)،
کانال (اینستاگرام/تلگرام) و برچسب‌ها؛ مناسبت‌ها هم تاریخِ ثابتِ شمسی دارند.
"""
from __future__ import annotations

import datetime as _dt
import functools
import random
import re
import uuid
from typing import Any

from django.db import DatabaseError
from django.db.models import Count

from . import fill, guard, jalali
from .catalog import CATEGORIES, CHANNELS, DEFAULT_CHANNEL, DEFAULT_FORMAT, FORMATS, ORIGINS
from .models import IdeaMark, IdeaUse, StoreIdea
from .seeds import BUILTIN_IDEAS

TEXT_FIELDS = ("title", "logline", "hook", "shoot", "cta")
LIMITS = {"title": 120, "logline": 600, "hook": 300, "shoot": 600, "cta": 80}
FIELDS = {"category": "tips", "format": DEFAULT_FORMAT, "channel": DEFAULT_CHANNEL, "tags": [], "title": "", "logline": "", "hook": "", "shoot": "",
          "cta": "", "occasion": None}


class BankError(Exception):
    """خطای قابلِ‌نمایش به کاربر (پیامِ فارسی). ``status`` = کدِ HTTP."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ------------------------------------------------------------------ متن

_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا",
                       "إ": "ا", "ؤ": "و", "‌": " ", "ـ": "",
                       **{c: str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")},
                       **{c: str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}})
_MARKS = re.compile("[ً-ٰٟ]")


def fold(text: Any) -> str:
    """متنِ فارسی را برای جست‌وجو هم‌شکل می‌کند (ی/ک عربی، نیم‌فاصله، اعراب، رقم‌ها، حروفِ کوچک)."""
    return re.sub(r"\s+", " ", _MARKS.sub("", str(text or "").translate(_FOLD)).lower()).strip()


def _s(v: Any, limit: int = 2000) -> str:
    return "" if v is None else re.sub(r"[ \t]+", " ", str(v)).strip()[:limit]


def _tags(v: Any) -> list[str]:
    raw = re.split(r"[,\n،]", v) if isinstance(v, str) else (v or [])
    out: dict[str, None] = {}
    for x in raw:
        t = _s(x, 30)
        if t:
            out[t] = None
    return list(out)[:8]


def _occasion(v: Any) -> dict | None:
    if not isinstance(v, dict):
        return None
    try:
        month, day = int(v.get("month")), int(v.get("day"))
    except (TypeError, ValueError):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return {"month": month, "day": day, "name": _s(v.get("name"), 80)}


def normalize(data: dict | None) -> dict:
    """ایدهٔ کامل و امن: کلیدِ ناشناخته دور ریخته، enumها به مقدارِ مجاز بسته می‌شوند، متن‌ها سقف دارند."""
    d = data or {}
    out: dict[str, Any] = {}
    for k, default in FIELDS.items():
        v = d.get(k, default)
        if k == "category":
            v = v if v in CATEGORIES else default
        elif k == "format":
            v = v if v in FORMATS else default
        elif k == "channel":
            v = v if v in CHANNELS else default
        elif k == "tags":
            v = _tags(v)
        elif k == "occasion":
            v = _occasion(v)
        else:
            v = _s(v, LIMITS[k])
        out[k] = v
    return out


def validate(data: dict) -> dict:
    n = normalize(data)
    if not n["title"]:
        raise BankError("validation_error", "عنوانِ ایده لازم است.")
    if not n["logline"]:
        raise BankError("validation_error", "توضیحِ یک‌جمله‌ای دربارهٔ ایده لازم است.")
    return n


# ------------------------------------------------------------------ ردیف‌ها

def _saved(store) -> bool:
    """فروشگاهِ ذخیره‌نشده (نمونهٔ آزمون/دمو) ردیفِ دیتابیسی ندارد."""
    return bool(getattr(store, "pk", None))


def _user_rows(store) -> dict[str, StoreIdea]:
    if not _saved(store):
        return {}
    try:
        return {r.key: r for r in StoreIdea.objects.filter(store=store)}
    except DatabaseError:
        return {}


def _marks(store) -> dict[str, IdeaMark]:
    if not _saved(store):
        return {}
    try:
        return {m.key: m for m in IdeaMark.objects.filter(store=store)}
    except DatabaseError:
        return {}


def _uses(store) -> dict[str, int]:
    if not _saved(store):
        return {}
    try:
        return {r["key"]: r["n"] for r in IdeaUse.objects.filter(store=store).values("key").annotate(n=Count("id"))}
    except DatabaseError:
        return {}


@functools.lru_cache(maxsize=1)
def _builtin_normalized() -> dict[str, dict]:
    return {k: normalize(v) for k, v in BUILTIN_IDEAS.items()}


def occasion_info(occ: dict | None, today: _dt.date | None = None) -> dict | None:
    """نزدیک‌ترین تاریخِ پیش‌رو برای مناسبتِ ثابتِ شمسی: {date, label, days}."""
    if not occ:
        return None
    today = today or _dt.date.today()
    when = jalali.next_occurrence(occ["month"], occ["day"], today)
    return {"date": when.isoformat(), "label": jalali.label(occ["month"], occ["day"]), "days": (when - today).days, "name": occ.get("name", "")}


def _entry(key: str, data: dict, *, builtin: bool, origin: str, based_on: str, marks: dict, uses: dict, ctx: dict | None, today: _dt.date | None) -> dict:
    m = marks.get(key)
    filled = {f: fill.fill_text(data[f], ctx) for f in TEXT_FIELDS}
    manual = guard.slots(" ".join(filled.values()))
    return {
        "key": key, "builtin": builtin, "origin": origin, "based_on": based_on, **data, "filled": filled, "slots": manual, "needs_data": bool(manual),
        "placeholders": fill.used_placeholders(*(data[f] for f in TEXT_FIELDS)), "favorite": bool(m and m.favorite), "hidden": bool(m and m.hidden),
        "uses": uses.get(key, 0), "occasion_next": occasion_info(data.get("occasion"), today),
    }


def all_ideas(store, ctx: dict | None = None, today: _dt.date | None = None) -> list[dict]:
    marks, uses = _marks(store), _uses(store)
    out = [_entry(k, dict(v), builtin=True, origin="builtin", based_on="", marks=marks, uses=uses, ctx=ctx, today=today) for k, v in _builtin_normalized().items()]
    out += [_entry(k, normalize(r.data), builtin=False, origin=r.origin, based_on=r.based_on, marks=marks, uses=uses, ctx=ctx, today=today)
            for k, r in _user_rows(store).items()]
    return out


def get_idea(store, key: str, ctx: dict | None = None, today: _dt.date | None = None) -> dict | None:
    return next((i for i in all_ideas(store, ctx, today) if i["key"] == key), None)


# ------------------------------------------------------------------ جست‌وجو و فیلتر

def matches(idea: dict, q: str) -> bool:
    words = [w for w in fold(q).split() if w]
    if not words:
        return True
    hay = fold(" ".join([idea[f] for f in TEXT_FIELDS] + [idea["filled"][f] for f in TEXT_FIELDS] + list(idea["tags"]) +
                        [CATEGORIES[idea["category"]]["fa"], FORMATS[idea["format"]]["fa"], CHANNELS[idea["channel"]]["fa"],
                         (idea.get("occasion") or {}).get("name", ""), idea["key"].replace("_", " ")]))
    return all(w in hay for w in words)


def list_ideas(store, *, q: str = "", category: str = "", tag: str = "", fmt: str = "", channel: str = "", favorite: bool = False, source: str = "",
               include_hidden: bool = False, needs_data: bool | None = None, ctx: dict | None = None, today: _dt.date | None = None) -> list[dict]:
    out = []
    for i in all_ideas(store, ctx, today):
        if i["hidden"] and not include_hidden:
            continue
        if category and i["category"] != category:
            continue
        if fmt and i["format"] != fmt:
            continue
        if channel and i["channel"] not in (channel, "both"):
            continue
        if tag and fold(tag) not in [fold(t) for t in i["tags"]]:
            continue
        if favorite and not i["favorite"]:
            continue
        if source == "builtin" and not i["builtin"]:
            continue
        if source == "mine" and i["builtin"]:
            continue
        if needs_data is not None and i["needs_data"] != needs_data:
            continue
        if q and not matches(i, q):
            continue
        out.append(i)
    order = {k: v["order"] for k, v in CATEGORIES.items()}

    def sort_key(i: dict):
        occ = i.get("occasion_next")
        return (not i["favorite"], order.get(i["category"], 99), occ["days"] if occ else 0, i["builtin"])      # پایدار: ترتیبِ نوشتنِ ایده‌ها حفظ می‌شود

    out.sort(key=sort_key)
    return out


def facets(rows: list[dict]) -> dict:
    """شمارنده‌ها برای تراشه‌های فیلتر: دسته‌ها (به ترتیبِ خودمان)، قالب‌ها، کانال‌ها و پرکاربردترین برچسب‌ها."""
    rows = [r for r in rows if not r["hidden"]]
    cats = [{"key": k, "fa": v["fa"], "count": sum(1 for r in rows if r["category"] == k)} for k, v in sorted(CATEGORIES.items(), key=lambda kv: kv[1]["order"])]
    fmts = [{"key": k, "fa": f["fa"], "count": sum(1 for r in rows if r["format"] == k)} for k, f in sorted(FORMATS.items(), key=lambda kv: kv[1]["order"])]
    chans = [{"key": k, "fa": c["fa"], "count": sum(1 for r in rows if r["channel"] in (k, "both"))} for k, c in CHANNELS.items() if k != "both"]
    tags: dict[str, int] = {}
    for r in rows:
        for t in r["tags"]:
            tags[t] = tags.get(t, 0) + 1
    top = sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    return {"categories": cats, "formats": fmts, "channels": chans, "tags": [{"tag": t, "count": n} for t, n in top], "total": len(rows),
            "needs_data": sum(1 for r in rows if r["needs_data"])}


def random_idea(store, category: str = "", ctx: dict | None = None) -> dict | None:
    rows = list_ideas(store, category=category, ctx=ctx)
    return random.choice(rows) if rows else None


# ------------------------------------------------------------------ نوشتن

def _new_key() -> str:
    return "u_" + uuid.uuid4().hex[:10]


def create_idea(store, data: dict, *, origin: str = "user", based_on: str = "", ctx: dict | None = None) -> dict:
    norm = validate(data)
    origin = origin if origin in ORIGINS else "user"
    key = _new_key()
    while StoreIdea.objects.filter(store=store, key=key).exists():
        key = _new_key()
    StoreIdea.objects.create(store=store, key=key, data=norm, origin=origin, based_on=based_on)
    return get_idea(store, key, ctx)  # type: ignore[return-value]


def update_idea(store, key: str, data: dict, ctx: dict | None = None) -> dict:
    if key in BUILTIN_IDEAS:
        raise BankError("conflict", "ایده‌های آماده فقط‌خواندنی‌اند؛ از آن کپی بگیرید و کپی را ویرایش کنید.", 409)
    row = StoreIdea.objects.filter(store=store, key=key).first()
    if not row:
        raise BankError("not_found", "ایده پیدا نشد.", 404)
    merged = {**normalize(row.data), **{k: v for k, v in (data or {}).items() if k in FIELDS}}
    row.data = validate(merged)
    row.save()
    return get_idea(store, key, ctx)  # type: ignore[return-value]


def delete_idea(store, key: str) -> None:
    if key in BUILTIN_IDEAS:
        raise BankError("conflict", "ایده‌های آماده حذف نمی‌شوند؛ می‌توانید پنهانشان کنید.", 409)
    n, _ = StoreIdea.objects.filter(store=store, key=key).delete()
    if not n:
        raise BankError("not_found", "ایده پیدا نشد.", 404)
    IdeaMark.objects.filter(store=store, key=key).delete()
    IdeaUse.objects.filter(store=store, key=key).delete()


def duplicate_idea(store, key: str, overrides: dict | None = None, ctx: dict | None = None) -> dict:
    src = get_idea(store, key, ctx)
    if not src:
        raise BankError("not_found", "ایده پیدا نشد.", 404)
    data = {k: src[k] for k in FIELDS}
    data.update({k: v for k, v in (overrides or {}).items() if k in FIELDS})
    if not (overrides or {}).get("title"):
        data["title"] = f"{data['title']} (کپی)"[:LIMITS["title"]]
    return create_idea(store, data, origin="duplicate", based_on=key, ctx=ctx)


def set_mark(store, key: str, *, favorite: bool | None = None, hidden: bool | None = None, ctx: dict | None = None) -> dict:
    if not get_idea(store, key, ctx):
        raise BankError("not_found", "ایده پیدا نشد.", 404)
    m, _ = IdeaMark.objects.get_or_create(store=store, key=key)
    if favorite is not None:
        m.favorite = bool(favorite)
    if hidden is not None:
        m.hidden = bool(hidden)
    m.save()
    return get_idea(store, key, ctx)  # type: ignore[return-value]


def title_key(title: str) -> str:
    return fold(re.sub(r"[*_]", "", str(title or "")))


def existing_titles(store, ctx: dict | None = None) -> set[str]:
    """عنوانِ همهٔ ایده‌های این فروشگاه (آماده، خودش، پنهان‌شده هم) برای جلوگیری از تکرار؛ هم قالب هم پرشده."""
    keys: set[str] = set()
    for i in all_ideas(store, ctx):
        keys.add(title_key(i["title"]))
        keys.add(title_key(i["filled"]["title"]))
    return keys


def add_generated(store, items: list[dict], *, category: str | None = None, origin: str = "generated", ctx: dict | None = None) -> list[dict]:
    """ایده‌های ساخته‌شده را به‌عنوانِ ایده‌های خودِ فروشگاه ذخیره می‌کند؛ عنوانِ تکراری رد می‌شود."""
    have = existing_titles(store, ctx)
    made = []
    for it in items:
        data = normalize({**it, **({"category": category} if category else {})})
        k = title_key(data["title"])
        if not data["title"] or not data["logline"] or k in have:
            continue
        made.append(create_idea(store, data, origin=origin, ctx=ctx))
        have.add(k)
    return made


def record_use(store, key: str, target: str, task_id: int | None = None) -> None:
    IdeaUse.objects.create(store=store, key=key, target=target, task_id=task_id)

"""«از این ایده شروع کن»: ایده را به استودیوی تولید محتوا، تقویمِ انتشار یا تامنیل‌ساز می‌برد؛ و ایده‌های ترندها را در بانک ذخیره می‌کند.

SOURCE: ported from InstAI:instai/ideabank/bank.py (start_project: «شروعِ پروژه از این ایده»)، adapted for store content — به‌جای ساختنِ «سریال»، یکی از این سه کار:

* **studio** — زبانهٔ «تولید محتوا» با خلاصهٔ ایده در کادرِ «هدف/توضیح» (``?brief=``)،
* **calendar** — یک کارِ «محتوا» با تاریخِ پیشنهادی در تختهٔ کمپین (همان که «تقویم انتشار» نشان می‌دهد؛ چیزی منتشر یا زمان‌بندی نمی‌شود)،
* **thumbnail** — تامنیل‌ساز با عنوان و قالبِ هماهنگ با ایده (``?title=&format=``).

هیچ‌کدام چیزی را خودکار نمی‌سازند یا منتشر نمی‌کنند؛ فقط پیش‌نویس و پرشدنِ فرم‌ها.
"""
from __future__ import annotations

import datetime as _dt
import re

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from . import bank, fill
from .catalog import CATEGORIES, CHANNELS, FORMATS

CAMPAIGN_NAME = "برنامهٔ محتوا (از بانکِ ایده)"
DEFAULT_HOUR = 10
STUDIO_TABS = (("video", "ویدیو"), ("image", "عکس و پوستر"), ("caption", "کپشن"))


BRIEF_MAX = 200        # «هدف» در ویدیو/کپشن یک CharField(200) است
DETAIL_MAX = 500


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ،؛:-—")


def brief_text(idea: dict) -> str:
    """خلاصهٔ کوتاه برای کادرِ «هدف» در استودیوی ویدیو و کپشن (حداکثر ۲۰۰ حرف): عنوان — قلاب."""
    f = idea["filled"]
    return _cut(" — ".join(p for p in (f["title"], f["hook"]) if p), BRIEF_MAX)


def detail_text(idea: dict) -> str:
    """توضیحِ کامل برای کادرِ «توضیحات» در استودیوی عکس و پوستر (حداکثر ۵۰۰ حرف)."""
    f = idea["filled"]
    parts = [f["title"], f"قلاب: {f['hook']}" if f["hook"] else "", f"چه بگیریم: {f['shoot']}" if f["shoot"] else "", f"دعوت به اقدام: {f['cta']}" if f["cta"] else ""]
    return _cut(" — ".join(p for p in parts if p), DETAIL_MAX)


def studio(idea: dict, *, product_id: int | None = None) -> dict:
    fmt = FORMATS[idea["format"]]
    return {"tab": fmt["studio_tab"], "tabs": [{"key": k, "label": v} for k, v in STUDIO_TABS], "product_id": product_id, "brief": brief_text(idea),
            "detail": detail_text(idea), "needs_data": idea["slots"]}


def hook_title(hook: str, fallback: str) -> str:
    """قلابِ ایده ⇒ عنوانِ کوتاهِ تامنیل: اولین بندِ جمله (تا «،» یا «؛»)، حداکثر ۱۰ واژه و روی مرزِ واژه؛ «؟» می‌ماند."""
    h = (hook or "").strip()
    if not h:
        return fill.clip_phrase(fallback, 10, 100)
    first = re.split(r"[،؛:]", h, maxsplit=1)[0].strip()
    if len(first.split()) < 3:
        first = h
    mark = "؟" if first.rstrip().endswith(("؟", "?")) else ""
    clipped = fill.clip_phrase(first, 10, 100)
    return (clipped + mark) if clipped else fill.clip_phrase(fallback, 10, 100)


def thumbnail(idea: dict) -> dict:
    """تامنیل‌ساز: «قلاب» عنوانِ تامنیل می‌شود و عنوانِ ایده زیرعنوان؛ قالب از قالبِ ایده و کانال."""
    f = idea["filled"]
    fmt = "telegram" if idea["channel"] == "telegram" else FORMATS[idea["format"]]["thumb_format"]
    return {"format": fmt, "title": hook_title(f["hook"], f["title"]), "subtitle": fill.clip_phrase(f["title"], 14, 120),
            "kicker": CATEGORIES[idea["category"]]["fa"][:34], "needs_data": idea["slots"]}


def task_detail(idea: dict) -> str:
    f = idea["filled"]
    lines = [f["logline"], ""]
    if f["hook"]:
        lines.append(f"قلاب: {f['hook']}")
    if f["shoot"]:
        lines.append(f"چه چیزی بگیریم: {f['shoot']}")
    if f["cta"]:
        lines.append(f"دعوت به اقدام: {f['cta']}")
    lines.append(f"قالب: {FORMATS[idea['format']]['fa']} · کانال: {CHANNELS[idea['channel']]['fa']}")
    if idea["slots"]:
        lines += ["", "جاهای خالی که پیش از انتشار باید با دادهٔ واقعیِ فروشگاه پر شود: " + "، ".join(idea["slots"])]
    return "\n".join(lines)[:8000]


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _aware(value, default_date: _dt.date) -> _dt.datetime:
    """تاریخ یا تاریخ‌وزمان ⇒ زمانِ آگاه از منطقهٔ زمانی. فقط-تاریخ = ساعتِ ۱۰ صبحِ همان روز (نه نیمه‌شب)."""
    if value in (None, ""):
        dt = _dt.datetime.combine(default_date, _dt.time(DEFAULT_HOUR))
    elif isinstance(value, _dt.datetime):
        dt = value
    elif isinstance(value, _dt.date):
        dt = _dt.datetime.combine(value, _dt.time(DEFAULT_HOUR))
    else:
        text = str(value).strip()
        d = parse_date(text) if _DATE_ONLY.match(text) else None
        dt = _dt.datetime.combine(d, _dt.time(DEFAULT_HOUR)) if d else parse_datetime(text)
        if dt is None:
            raise bank.BankError("bad_due", "تاریخ را درست بفرستید (مثلاً ۲۰۲۶-۱۲-۲۱).")
    return dt if timezone.is_aware(dt) else timezone.make_aware(dt)


def suggested_due(idea: dict, today: _dt.date | None = None) -> _dt.datetime:
    """مناسبت‌ها: روزِ خودِ مناسبت؛ بقیه: فردا (ساعتِ ۱۰ صبح به وقتِ پنل)."""
    today = today or timezone.localdate()
    occ = idea.get("occasion_next")
    day = _dt.date.fromisoformat(occ["date"]) if occ else today + _dt.timedelta(days=1)
    return _aware(None, day)


def plan(store, idea: dict, *, campaign_id=None, product_id=None, due=None, today: _dt.date | None = None) -> dict:
    """یک «کارِ محتوا» با تاریخِ پیشنهادی در تختهٔ کمپین می‌سازد. یا کمپینِ موجود یا محصولی (برای ساختِ «برنامهٔ محتوا») لازم است."""
    from apps.campaigns.models import Campaign
    from apps.campaigns.tasks_board import CampaignTask
    from apps.products.models import Product

    campaign = None
    if campaign_id not in (None, ""):
        try:
            campaign = Campaign.objects.filter(store=store, pk=int(campaign_id)).first()
        except (TypeError, ValueError):
            campaign = None
        if campaign is None:
            raise bank.BankError("not_found", "کمپین پیدا نشد.", 404)
    elif product_id not in (None, ""):
        try:
            product = Product.objects.filter(store=store, pk=int(product_id)).first()
        except (TypeError, ValueError):
            product = None
        if product is None:
            raise bank.BankError("not_found", "محصول پیدا نشد.", 404)
        campaign = Campaign.objects.filter(store=store, product=product, name=CAMPAIGN_NAME).first() or Campaign.objects.create(
            store=store, product=product, name=CAMPAIGN_NAME, goal="برنامهٔ پست‌ها", notes="کارهایی که از بانکِ ایده به تقویم آمده‌اند.")
    else:
        raise bank.BankError("need_campaign", "یک کمپین انتخاب کنید یا محصولی بدهید تا «برنامهٔ محتوا» برایش ساخته شود.")
    due_at = _aware(due, (suggested_due(idea, today)).date()) if due not in (None, "") else suggested_due(idea, today)
    task = CampaignTask.objects.create(
        campaign=campaign, store=store, kind=CampaignTask.Kind.CONTENT, title=idea["filled"]["title"][:200], detail=task_detail(idea),
        because=f"از بانکِ ایده: {idea['filled']['title']}"[:300], due_at=due_at, order=campaign.tasks.count())
    return {"task_id": task.pk, "campaign_id": campaign.pk, "campaign": campaign.name, "due_at": task.due_at.isoformat(), "needs_data": idea["slots"]}


# ───────────────────────────── ذخیره از ترندها

KIND_TO_FORMAT = {"VIDEO": "reel", "POST": "photo", "STORY": "story", "CAPTION": "photo"}
BRIEF_FORMAT = {"reel": "reel", "video": "reel", "carousel": "carousel", "photo": "photo", "story": "story"}


def _title_from(text: str) -> str:
    return fill.clip_phrase(str(text or "").replace("«", "").replace("»", ""), 9, 80)


def save_trend_idea(store, trend_idea, ctx: dict | None = None) -> tuple[dict, bool]:
    """یک ایدهٔ ترند (``TrendIdea``) ⇒ ایدهٔ بانک. ⇒ (ایده، تازه‌ساخته‌شد؟)"""
    idea_text = str(trend_idea.idea or "")
    main, _, steps = idea_text.partition("مراحل:")
    data = {"category": "tips", "format": KIND_TO_FORMAT.get(trend_idea.kind, "photo"), "channel": "instagram", "tags": ["ترند", _title_from(trend_idea.trend.title)[:28]],
            "title": _title_from(trend_idea.hook or main) or "ایدهٔ ترند", "logline": main.strip()[:600], "hook": str(trend_idea.hook or "")[:300],
            "shoot": steps.strip().replace("•", "-")[:600], "cta": ""}
    return _save_trend(store, data, ctx)


def save_cluster_brief(store, cluster, ctx: dict | None = None) -> tuple[dict, bool]:
    """موضوعِ ترندِ اینستاگرام که «ایده بساز»ش زده شده (``IgTrendCluster.brief``) ⇒ ایدهٔ بانک."""
    brief = cluster.brief or {}
    if not brief.get("idea") and not brief.get("hook"):
        raise bank.BankError("no_brief", "اول در همان کارت «ایده بساز» را بزنید.", 409)
    tags = ["ترند"] + [str(h).lstrip("#")[:28] for h in (brief.get("hashtags") or [])[:4]]
    data = {"category": "tips", "format": BRIEF_FORMAT.get(str(brief.get("format") or ""), "reel"), "channel": "instagram", "tags": tags,
            "title": _title_from(brief.get("hook") or brief.get("idea")) or "ایدهٔ ترند", "logline": str(brief.get("idea") or "")[:600],
            "hook": str(brief.get("hook") or "")[:300], "shoot": "؛ ".join(str(x) for x in (brief.get("outline") or []))[:600], "cta": ""}
    return _save_trend(store, data, ctx)


def _save_trend(store, data: dict, ctx: dict | None) -> tuple[dict, bool]:
    if not data["logline"]:
        data["logline"] = data["hook"] or data["title"]
    made = bank.add_generated(store, [data], origin="trend", ctx=ctx)
    if made:
        return made[0], True
    k = bank.title_key(data["title"])
    again = next((i for i in bank.all_ideas(store, ctx) if bank.title_key(i["title"]) == k or bank.title_key(i["filled"]["title"]) == k), None)
    if again is None:
        raise bank.BankError("save_failed", "ایده ذخیره نشد.", 400)
    return again, False

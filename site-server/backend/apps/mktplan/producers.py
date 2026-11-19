"""تولیدکننده‌ها: برای هر نوعِ کارِ برنامه یک تابع که «کارِ واقعیِ آن بخش» را با همان سرویسِ آن بخش می‌سازد.

قاعده‌ها (برای همهٔ تولیدکننده‌ها):

* **اول می‌پذیرد، بعد می‌سازد.** اگر فروشگاه از دورهای قبل چیزی دارد که به این کار می‌خورد (کارِ کمپین، رندرِ موشن، تامنیلِ منتظر، سندِ طراحی،
  مأموریتِ مشتری‌یاب…) همان به کار وصل می‌شود (و در صورتِ لزوم زمانش تازه می‌شود)؛ چیزِ تکراری ساخته نمی‌شود.
* **هر اجرا همان نتیجه را می‌دهد.** تولیدکننده اول ``item.refs`` را می‌بیند؛ ردیفی که زنده است دوباره ساخته نمی‌شود، ردیفِ لغوشده/پاک‌شده دوباره ساخته می‌شود.
* **هیچ‌چیز منتشر یا فرستاده نمی‌شود.** همه پیش‌نویس‌اند؛ پیامک فقط یک «ارسالِ گروهیِ پیش‌نویس» است که بدونِ تأیید نمی‌رود.
* **کارِ GPU همیشه در صفِ ماندگار می‌ماند.** گرهٔ خاموش خطا نیست: کار «منتظرِ سرورِ پردازش» می‌شود و با روشن‌شدنِ گره خودش اجرا می‌گردد.
* خطای یک تولیدکننده فقط همان کار را ``FAILED`` می‌کند و می‌ماند تا تیکِ بعدی دوباره امتحان کند؛ بقیهٔ برنامه ادامه می‌دهد.
"""
from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from django.utils import timezone

from apps.common.fatext import fa_digits

from . import ai as plan_ai
from . import clock, drafts, kinds, refs
from .models import PlanItem

logger = logging.getLogger(__name__)

PRODUCERS: dict[str, Callable] = {}


class NeedsYou(Exception):
    """کار فقط با دادهٔ خودِ مالک ادامه می‌یابد؛ متن برای مالک است."""


class NodeNotReady(Exception):
    """سرورِ پردازش (یا مدلِ لازم) هنوز آماده نیست؛ کار منتظر می‌ماند و تیکِ بعدی دوباره امتحان می‌کند."""


def producer(*names: str):
    def deco(fn):
        for n in names:
            PRODUCERS[n] = fn
        return fn

    return deco


@dataclass
class Ctx:
    plan: object
    store: object
    user: object
    f: dict
    log: Callable = lambda msg: None
    _items: dict = field(default_factory=dict)

    @property
    def owner(self):
        return self.user if getattr(self.user, "is_authenticated", False) else (self.plan.created_by or self.store.owner)

    def sibling(self, key: str):
        """کارِ هم‌پلنِ دیگر، **تازه از پایگاه‌داده**. (پیش‌تر یک بار خوانده و نگه داشته می‌شد؛ گوینده‌ای که زودتر از ریلزِ همراهش اجرا می‌شد پیش‌نویسِ
        خالیِ آن را می‌دید و به‌جای «متنِ گویندگی»ِ همان ریلز، متنِ ساختگیِ خودش را می‌خواند.)"""
        if not key:
            return None
        return self.plan.items.filter(key=key).first()

    def url(self, page_key: str) -> str:
        return kinds.url_for(page_key, self.store.pk)


# ----------------------------------------------------------------------------- ابزارها

def _alive(item, type_: str) -> list[dict]:
    """پیوندهای این نوع که هنوز زنده‌اند (لغوشده/پاک‌شده/ناموفق حساب نمی‌شود)."""
    out = []
    for r in refs.of_type(item, type_):
        st, _note = refs.state_of(r)
        if st not in (refs.MISSING, refs.CANCELLED, refs.FAILED):
            out.append(r)
    return out


def _drop_dead(item, type_: str) -> None:
    for r in refs.of_type(item, type_):
        if refs.state_of(r)[0] in (refs.MISSING, refs.CANCELLED):
            refs.remove(item, type_, r["id"])


def _checks(item, text: str, f: dict) -> None:
    item.meta = {**(item.meta or {}), "checks": drafts.check(text, f)}


def _set_draft(ctx: Ctx, item: PlanItem, text: str) -> None:
    """پیش‌نویسِ قاعده‌محور را می‌نویسد، فقط اگر هنوز خالی است (متنِ پولیش‌شده یا ویرایش‌شده را پاک نمی‌کند)."""
    if not item.draft:
        item.draft = text
        item.ai_wait = True          # تا وقتی هوش مصنوعی برگردد و پولیشش کند
    _checks(item, item.draft, ctx.f)


def _owner_product(ctx: Ctx):
    from apps.products.models import Product

    prod = None
    if ctx.f.get("flagship"):
        prod = Product.objects.filter(store=ctx.store, name=ctx.f["flagship"]).first()
    return prod or Product.objects.filter(store=ctx.store).order_by("pk").first()


def _plan_campaign(ctx: Ctx, suffix: str):
    from apps.campaigns.models import Campaign

    name = f"{ctx.store.name} — برنامهٔ بازاریابی — {suffix}"[:200]
    c = Campaign.objects.filter(store=ctx.store, name=name).first()
    if c is not None:
        return c
    prod = _owner_product(ctx)
    if prod is None:
        raise NeedsYou("برای ساختنِ کمپین دست‌کم یک محصول ثبت کنید (فروشگاه ⇐ محصولات).")
    return Campaign.objects.create(store=ctx.store, product=prod, name=name, goal=(ctx.plan.goal or "")[:200], audience=ctx.f["audience"][:200],
                                   notes="ساخته‌شده توسط «برنامهٔ بازاریابی»؛ فقط پیش‌نویس است و چیزی خودکار منتشر نمی‌شود.")


def _retime_task(task, when) -> None:
    from apps.campaigns.tasks_board import CampaignTask

    if task.state in (CampaignTask.State.DONE, CampaignTask.State.DROPPED):
        return
    detail = clock.retime_detail(task.detail, when)
    if task.due_at != when or detail != task.detail:
        task.due_at, task.detail = when, detail
        task.save(update_fields=["due_at", "detail", "updated_at"])


def _retime_now(item: PlanItem) -> bool:
    """موعدِ کارِ کمپینِ وصل‌شده فقط وقتی تازه می‌شود که تازه وصل شده یا تاریخِ برنامه عوض شده؛ موعدی که مالک دستی گذاشته هر اجرا پاک نمی‌شود."""
    flag = bool((item.meta or {}).get("retime"))
    if flag:
        item.meta = {k: v for k, v in (item.meta or {}).items() if k != "retime"}
    return flag


def _task_ref(ctx: Ctx, task) -> dict:
    return refs.make("campaign_task", task.pk, task.title, ctx.url("campaigns"))


def _candidate_tasks(ctx: Ctx, item: PlanItem, prefixes: tuple[str, ...], *, skip_words: tuple[str, ...] = ()) -> list:
    from apps.campaigns.tasks_board import CampaignTask

    linked = refs.linked_ids(ctx.plan, "campaign_task", exclude_item=item)
    qs = (CampaignTask.objects.filter(store=ctx.store, kind=CampaignTask.Kind.CONTENT).exclude(state__in=(CampaignTask.State.DONE, CampaignTask.State.DROPPED))
          .select_related("campaign").order_by("campaign_id", "order", "id"))
    out = []
    for t in qs:
        if str(t.pk) in linked or "پروفایل" in t.campaign.name or "تصمیم" in t.campaign.name:
            continue
        if not any(t.title.startswith(p) for p in prefixes) or any(w in t.title for w in skip_words):
            continue
        out.append(t)
    return out


# ----------------------------------------------------------------------------- محتوا: پروفایل، پست، کاروسل، استوری، ریلز

@producer("profile")
def p_profile(ctx: Ctx, item: PlanItem):
    from apps.campaigns.tasks_board import CampaignTask

    existing = list(CampaignTask.objects.filter(store=ctx.store, campaign__name__icontains="پروفایل").order_by("campaign_id", "order", "id")[:12])
    when = item.scheduled_for or clock.when_for("post", clock.today_tehran())
    if existing:
        fresh = not refs.of_type(item, "campaign_task") or _retime_now(item)
        for t in existing:
            refs.add(item, _task_ref(ctx, t))
            if fresh:
                _retime_task(t, clock.at(when.astimezone(clock.TEHRAN).date(), 10, 0))
        item.draft = existing[0].detail
        item.title = f"پروفایل: بایو، هایلایت و پستِ سنجاق‌شده ({fa_digits(str(len(existing)))} کارِ آماده)"
        item.ai_wait = False
        item.message = "پیش‌نویس‌های پروفایل از قبل ساخته شده بود؛ همان‌ها به برنامه وصل و زمان‌شان تازه شد."
        return
    if _alive(item, "campaign_task"):
        return
    from apps.campaigns.tasks_board import CampaignTask as CT

    camp = _plan_campaign(ctx, "راه‌اندازی پروفایل")
    text = item.draft or drafts.profile_draft(ctx.f)
    task = CT.objects.create(campaign=camp, store=ctx.store, kind=CT.Kind.CONTENT, title="بایو و هایلایت‌ها — پیش‌نویس", detail=text, due_at=item.scheduled_for,
                             because="برنامهٔ بازاریابی: پروفایل پیش از اولین پست آماده باشد", order=0)
    refs.add(item, _task_ref(ctx, task))
    _set_draft(ctx, item, text)


_PREFIX = {"carousel": ("کاروسل",), "reel": ("ریلز",), "story": ("استوری",), "post": ("پست",)}
_RESERVED = ("نظرِ واقعی", "ویدیوی واقعی")


@producer("post", "carousel", "story", "reel")
def p_content(ctx: Ctx, item: PlanItem):
    from apps.campaigns.tasks_board import CampaignTask as CT

    _drop_dead(item, "campaign_task")
    live = _alive(item, "campaign_task")
    when = item.scheduled_for
    if live:
        t = CT.objects.filter(pk=live[0]["id"]).first()
        if t is not None:
            if _retime_now(item):
                _retime_task(t, when)
            item.draft = item.draft or t.detail
        return
    cands = _candidate_tasks(ctx, item, _PREFIX[item.kind], skip_words=_RESERVED)
    if cands:
        t = cands[0]
        refs.add(item, _task_ref(ctx, t))
        _retime_task(t, when)
        item.title, item.draft, item.ai_wait = t.title[:240], t.detail, False
        item.meta = {**(item.meta or {}), "adopted": True, "checks": []}
        item.message = "پیش‌نویسِ آماده از کمپین‌های قبلیِ این فروشگاه به برنامه وصل شد."
        return
    pillar = (item.meta or {}).get("pillar") or "intro"
    camp = _plan_campaign(ctx, f"هفتهٔ {clock.fa_digits(str((item.meta or {}).get('week') or 1))}")
    text = item.draft or drafts.content_draft(item.kind, pillar, ctx.f)
    task = CT.objects.create(campaign=camp, store=ctx.store, kind=CT.Kind.CONTENT, title=item.title[:200],
                             detail=f"{text}\n\nموعدِ پیشنهادیِ انتشار: {clock.fa_when(when)} — فقط پیشنهاد؛ چیزی خودکار منتشر نمی‌شود.",
                             due_at=when, because="برنامهٔ بازاریابی", order=item.day * 10 + item.order)
    refs.add(item, _task_ref(ctx, task))
    _set_draft(ctx, item, text)


@producer("testimonial")
def p_testimonial(ctx: Ctx, item: PlanItem):
    from apps.campaigns.tasks_board import CampaignTask as CT

    live = _alive(item, "campaign_task")
    if not live:
        for t in _candidate_tasks(ctx, item, ("ریلز", "پست", "استوری", "کاروسل")):
            if any(w in t.title for w in _RESERVED):
                refs.add(item, _task_ref(ctx, t))
                _retime_task(t, item.scheduled_for)
                item.title = t.title[:240]
                break
    item.draft = item.draft or drafts.testimonial_request(ctx.f)
    item.meta = {**(item.meta or {}), "needs_you": "نظرِ واقعیِ یک مشتری لازم است؛ هیچ نظری ساخته نمی‌شود. متنِ درخواستِ اجازه آماده است."}
    item.message = item.meta["needs_you"]


# ----------------------------------------------------------------------------- راه‌اندازی: ایده، ترند، مأموریت، صندوق

@producer("ideas")
def p_ideas(ctx: Ctx, item: PlanItem):
    from apps.ideabank import bank, fill, generator
    from apps.ideabank.models import StoreIdea

    if _alive(item, "idea"):
        return
    ok_ai, _why = plan_ai.available(ctx.store)
    count = 8 if item.key.endswith(".bank") else 6
    # موضوع = محصولِ اصلی؛ واقعیت‌ها = جملهٔ معرفیِ خودِ فروشگاه (ایده‌ها فقط از همین‌ها می‌آیند، نه از نامِ بسته‌ها و قیمت‌ها)
    facts = [x for x in (ctx.f.get("one_liner"), ctx.f.get("tagline")) if x]
    res = generator.generate_and_save(ctx.store, count=count, use_ai=bool(ok_ai), ctx=fill.context(ctx.store), topic=ctx.f.get("flagship", ""),
                                      facts=facts, variation=0 if item.key.endswith(".bank") else 1)
    keys = [i.get("key") for i in res["ideas"] if i.get("key")]
    for row in StoreIdea.objects.filter(store=ctx.store, key__in=keys):
        refs.add(item, refs.make("idea", row.pk, (row.data or {}).get("title", row.key), ctx.url("ideas")))
    item.draft = "\n".join(f"• {(i.get('filled') or i).get('title', i.get('title', ''))}" for i in res["ideas"])
    item.ai_wait = res["via"] == "formula"
    item.message = res["message"][:280]
    if not keys:
        item.message = "ایده‌های تازه‌ای نماند (همه از قبل در بانکِ ایده هست)؛ بانکِ ایده را ببینید."


@producer("trends")
def p_trends(ctx: Ctx, item: PlanItem):
    from apps.igtrends import dispatch, seeds
    from apps.igtrends.models import IgScanRun, IgSeed

    seeds.apply_defaults(ctx.store)
    n_seeds = IgSeed.objects.filter(store=ctx.store).count()
    if not n_seeds:
        raise NeedsYou("هیچ صفحه یا هشتگی برای خواندنِ ترند ثبت نشده؛ در «بازار ⇐ ترندها» چند پیجِ هم‌حوزه اضافه کنید.")
    last = IgScanRun.objects.filter(store=ctx.store).order_by("-id").first()
    if last is not None and last.state in (IgScanRun.State.OK, IgScanRun.State.QUEUED, IgScanRun.State.RUNNING):
        refs.add(item, refs.make("scan", last.pk, "خواندنِ ترندهای اینستاگرام", ctx.url("trends")))
        item.message = f"{n_seeds} صفحه/هشتگ برای خواندن ثبت است."
        return
    try:
        run = dispatch.request_scan(ctx.store, auto=False)
    except dispatch.ScanRefused as exc:
        raise NodeNotReady(str(exc)) from exc
    refs.add(item, refs.make("scan", run.pk, "خواندنِ ترندهای اینستاگرام", ctx.url("trends")))
    item.message = "خواندنِ ترندها در صفِ سرورِ پردازش (آباگرام) گذاشته شد؛ با روشن‌شدنِ گره خودش اجرا می‌شود."


@producer("finder")
def p_finder(ctx: Ctx, item: PlanItem):
    from apps.growth_engine.crawler.models import CrawlMission

    linked = refs.linked_ids(ctx.plan, "mission", exclude_item=item)
    if not refs.of_type(item, "mission"):
        missions = [m for m in CrawlMission.objects.filter(store=ctx.store, is_archived=False).order_by("id") if str(m.pk) not in linked]
        if not missions:
            missions = list(CrawlMission.objects.filter(store=ctx.store, is_archived=False).order_by("id")[:2])
        for m in missions[:2] if item.key.endswith(".m2") else missions[:1]:
            refs.add(item, refs.make("mission", m.pk, m.name, "/growth/finder"))
    if not refs.of_type(item, "mission"):
        item.draft = (f"پیشنهادِ مأموریت: پیدا کردنِ «{ctx.f['audience_short']}» در شهرِ هدفِ شما.\n"
                      "در «جذب مشتری ⇐ مشتری‌یاب» نوعِ کسب‌وکار، کلیدواژه و شهر را بدهید و «بساز و اجرا کن» را بزنید؛ خودکار چیزی فرستاده نمی‌شود.")
        raise NeedsYou("برای این فروشگاه هنوز مأموریتِ مشتری‌یاب ساخته نشده؛ نوعِ کسب‌وکار و شهر را شما می‌دانید.")
    names = [r["label"] for r in refs.of_type(item, "mission")]
    item.draft = "مأموریت‌ها:\n" + "\n".join(f"• {n}" for n in names) + "\n\nنتیجه در «مشتری‌یاب ⇐ نتایج»؛ هیچ پیامی خودکار نمی‌رود."
    item.message = "مأموریت از قبل ساخته و اجرا شده؛ به برنامه وصل شد."


@producer("leads_review")
def p_leads_review(ctx: Ctx, item: PlanItem):
    from apps.growth_engine.crawler.models import CrawlMission

    ms = list(CrawlMission.objects.filter(store=ctx.store, is_archived=False).order_by("id")[:3])
    for m in ms:
        refs.add(item, refs.make("mission", m.pk, m.name, "/growth/finder/results"))
    if not ms:
        raise NeedsYou("اول در «مشتری‌یاب» یک مأموریت بسازید و اجرا کنید؛ بعد لیدها اینجا بازبینی می‌شود.")
    item.draft = ("بازبینیِ لیدها: در «نتایج مشتری‌یاب» لیدهای با امتیازِ تناسبِ بالا را ببینید، برچسب بزنید و برای مهم‌ترین‌ها «یادآوریِ پیگیری» بگذارید. "
                  "دلیلِ هر امتیاز کنارش نوشته شده است.")


@producer("dm")
def p_dm(ctx: Ctx, item: PlanItem):
    from apps.growth_engine.crawler.models import CrawlMission, OutreachDraft

    mids = list(CrawlMission.objects.filter(store=ctx.store).values_list("pk", flat=True))
    rows = []
    if mids:
        try:
            rows = list(OutreachDraft.objects.filter(mission_id__in=mids).order_by("-id")[:3])
        except Exception:  # noqa: BLE001 — اگر ساختارِ جدول فرق کرد، فقط متنِ آماده می‌ماند
            rows = []
    for r in rows:
        refs.add(item, refs.make("outreach_draft", r.pk, "پیش‌نویسِ پیامِ مشتری‌یاب", "/growth/finder/drafts"))
    _set_draft(ctx, item, drafts.dm_text(ctx.f))
    item.message = ("پیش‌نویس‌های مشتری‌یاب از قبل هست؛ متنِ نمونه هم آماده است." if rows else
                    "متنِ نمونه آماده است؛ بعد از پیدا شدنِ لیدها در «پیش‌نویسِ پیام‌ها» برای هر لید ساخته می‌شود.")


@producer("inbox")
def p_inbox(ctx: Ctx, item: PlanItem):
    from apps.inbox.models import CannedReply, ChannelConnection, InboxSettings

    st, _ = InboxSettings.objects.get_or_create(store=ctx.store)
    base = {
        "معرفی": ctx.f["tagline"] and f"{ctx.f['name']}: {ctx.f['tagline']}" or f"{ctx.f['name']}: {drafts._one_liner(ctx.f) or '[یک جمله دربارهٔ کارتان]'}",
        "شروع": f"برای شروع از این نشانی استفاده کنید: {drafts._site(ctx.f)}",
        "پشتیبانی": "پیامتان را دریافت کردیم؛ همکارانمان در اولین فرصت پاسخ می‌دهند.",
    }
    for short, text in base.items():
        row = CannedReply.objects.filter(store=ctx.store, shortcut=short).first()
        if row is None:
            row = CannedReply.objects.create(store=ctx.store, title=f"[برنامه] {short}", shortcut=short, text=text)
        refs.add(item, refs.make("canned", row.pk, row.title, ctx.url("inbox")))
    conns = ChannelConnection.objects.filter(store=ctx.store, enabled=True).count()
    n_canned = CannedReply.objects.filter(store=ctx.store).count()
    steps = [
        (conns > 0, f"کانال: {fa_digits(conns)} کانالِ فعال" if conns else "کانال: هیچ کانالی وصل نیست — در «کانال‌های صندوق» توکنِ ربات یا ویجتِ سایت را وصل کنید"),
        (bool(st.bot_enabled), "ربات: روشن است" if st.bot_enabled else "ربات: خاموش است — در «ربات و تنظیمات» روشنش کنید"),
        (bool(st.working_hours), "ساعتِ کاری: ثبت شده" if st.working_hours else "ساعتِ کاری: ثبت نشده — در «تیم و SLA» بنویسید"),
        (bool((st.greeting_message or "").strip()), "پیامِ خوش‌آمد: ثبت شده" if (st.greeting_message or "").strip() else "پیامِ خوش‌آمد: ثبت نشده"),
        (n_canned >= 3, f"پاسخ‌های آماده: {fa_digits(n_canned)} مورد"),
    ]
    item.draft = "\n".join(("✓ " if ok else "✗ ") + line for ok, line in steps)
    missing = [line for ok, line in steps if not ok]
    if conns == 0:
        item.meta = {**(item.meta or {}), "needs_you": "هیچ کانالی وصل نیست؛ وصل‌کردنِ ربات و کانال به توکنِ خودتان نیاز دارد."}
        item.message = item.meta["needs_you"]
    else:
        item.meta = {k: v for k, v in (item.meta or {}).items() if k != "needs_you"}
        item.message = ("همه‌چیز آماده است." if not missing else f"{fa_digits(len(missing))} مورد مانده: " + "؛ ".join(missing)[:200])


# ----------------------------------------------------------------------------- طراحی: کاتالوگ، ارائه، صفحهٔ فرود، ویدیو از ارائه

def _scrub_price_text(value, ids: set[int]):
    """قیمتِ «محاسبه‌شده / منتشرنشده» را از اسلایدها برمی‌دارد: بندهای «points» (جدولِ مقایسه) که نوشتهٔ «منتشر نشده» دارند، و خطِ «قیمتِ ثبت‌شده»
    در یادداشتِ گویندهٔ اسلایدِ همان محصول. ⇒ (مقدارِ تازه، آیا چیزی عوض شد)."""
    from .facts import UNCONFIRMED_PRICE

    if isinstance(value, list):
        out, changed = [], False
        for x in value:
            nx, ch = _scrub_price_text(x, ids)
            out.append(nx)
            changed = changed or ch
        return out, changed
    if isinstance(value, dict):
        out, changed = {}, False
        for k, x in value.items():
            if k == "points" and isinstance(x, list):
                nx = [pt for pt in x if not (isinstance(pt, str) and UNCONFIRMED_PRICE.search(pt))]
                ch = len(nx) != len(x)
            elif k == "notes" and isinstance(x, str) and ids and int(value.get("product") or 0) in ids:
                lines = x.splitlines()
                kept = [ln for ln in lines if not ln.strip().startswith("قیمتِ ثبت‌شده")]
                nx, ch = "\n".join(kept), len(kept) != len(lines)
            else:
                nx, ch = _scrub_price_text(x, ids)
            out[k] = nx
            changed = changed or ch
        return out, changed
    return value, False


def _hold_prices(ctx: Ctx, item: PlanItem, doc) -> list[str]:
    """قیمتِ «محاسبه‌شده / منتشرنشده»ی محصول‌ها را از ارائه و کاتالوگ برمی‌دارد و در کارت هشدار می‌دهد.

    مالک هنوز این قیمت‌ها را تأیید نکرده (در سندِ واقعیت‌های چغر: قیمتِ تومانیِ هر برنامه جداگانه منتشر نشده و واحدش تأیید نشده)؛ پس نباید در اسلایدِ
    ارائه، PDFِ کاتالوگ یا ویدیویی که از اسلایدها ساخته می‌شود چاپ شود. فقط **نسخهٔ داخلِ سندِ طراحی** عوض می‌شود (قیمت و ویژگی‌های «معادلِ تومانی» خالی
    می‌شود)؛ خودِ محصول در فروشگاه دست نمی‌خورد. هر اجرا همین را تکرار می‌کند، پس اگر سند دوباره از محصولات همگام شد باز کنار می‌رود؛ وقتی مالک
    نوشتهٔ «منتشر نشده» را از محصول بردارد، دیگر کنار گذاشته نمی‌شود. ⇒ نامِ محصول‌های کنارگذاشته‌شده."""
    meta = dict(item.meta or {})
    names = apply_price_hold(ctx, doc)
    if doc is None or doc.kind not in ("deck", "catalog"):
        return []
    if not names:                                  # مالک قیمت را تأیید کرده؛ هشدارِ قبلی برداشته می‌شود
        if meta.pop("price_hold", None) is not None:
            meta["checks"] = [c for c in (meta.get("checks") or []) if "تأیید نشده" not in c]
            item.meta = meta
        return []
    note = ("قیمتِ «" + "»، «".join(n[:40] for n in names[:3]) + "» هنوز تأیید نشده (فقط از روی قیمتِ بستهٔ توکن محاسبه شده و جداگانه منتشر نشده)؛ "
            "تا تأییدِ شما در این سند و خروجی‌هایش (اسلاید، کاتالوگ، ویدیو) نشان داده نمی‌شود. بعد از تأییدِ قیمت، نوشتهٔ «منتشر نشده» را از محصول بردارید.")
    meta["checks"] = [note] + [c for c in (meta.get("checks") or []) if "تأیید نشده" not in c]
    meta["price_hold"] = names
    item.meta = meta
    return names


def apply_price_hold(ctx: Ctx, doc) -> list[str]:
    """نیمهٔ دادهٔ ``_hold_prices``: قیمتِ تأییدنشده را از خودِ سند برمی‌دارد (اگر لازم بود ``rev`` بالا می‌رود). ⇒ نامِ محصول‌های کنارگذاشته‌شده."""
    from .facts import UNCONFIRMED_PRICE

    held = ctx.f.get("price_review") or []
    if doc is None or doc.kind not in ("deck", "catalog") or not held:
        return []
    ids = {int(h["id"]) for h in held}
    data = copy.deepcopy(doc.data or {})
    changed = False
    for p in data.get("products") or []:
        if int(p.get("id") or 0) not in ids:
            continue
        if p.get("price") is not None or p.get("compare_at") is not None:
            p["price"], p["compare_at"], changed = None, None, True
        attrs = [a for a in (p.get("attrs") or []) if not UNCONFIRMED_PRICE.search(" ".join(str(x) for x in a))]
        if len(attrs) != len(p.get("attrs") or []):
            p["attrs"], changed = attrs, True
    slides, ch = _scrub_price_text(data.get("slides") or [], ids)
    if ch:
        data["slides"], changed = slides, True
    names = [h["name"] for h in held]
    if changed:
        doc.data = data
        doc.rev += 1
        doc.meta = {**(doc.meta or {}), "price_hold": names}
        doc.save(update_fields=["data", "rev", "meta", "updated_at"])
    elif (doc.meta or {}).get("price_hold") != names:
        doc.meta = {**(doc.meta or {}), "price_hold": names}
        doc.save(update_fields=["meta", "updated_at"])
    return names


def _design(ctx: Ctx, item: PlanItem, kind: str, title: str, options: dict):
    from apps.design_studio import services as S
    from apps.design_studio.models import DesignDoc

    live = _alive(item, "design_doc")
    if live:
        doc = DesignDoc.objects.filter(pk=live[0]["id"]).first()
        _hold_prices(ctx, item, doc)
        return doc
    taken = refs.linked_ids(ctx.plan, "design_doc", exclude_item=item)
    docs = [d for d in DesignDoc.objects.filter(store=ctx.store, kind=kind).order_by("id") if str(d.pk) not in taken]
    doc = docs[0] if docs else None
    adopted = doc is not None
    if doc is None:
        try:
            doc = S.create_doc(ctx.store, ctx.owner, kind, title=title, options=options)
        except S.DesignError as exc:
            raise NeedsYou(str(exc)) from exc
    refs.add(item, refs.make("design_doc", doc.pk, doc.title, ctx.url({"catalog": "design_catalog", "deck": "design_deck", "ui": "design_ui"}[kind])))
    _hold_prices(ctx, item, doc)
    item.message = "پیش‌نویسِ آماده از استودیوی طراحی به برنامه وصل شد." if adopted else "پیش‌نویس در استودیوی طراحی ساخته شد."
    return doc


@producer("catalog")
def p_catalog(ctx: Ctx, item: PlanItem):
    _design(ctx, item, "catalog", f"کاتالوگِ {ctx.f['name']} (پیش‌نویس)", {})
    item.draft = item.draft or "خروجی‌ها: PDF چاپی، PDF نمایشی، PNG/JPG و PPTX از «استودیوی طراحی ⇐ کاتالوگ محصولات»."


@producer("deck")
def p_deck(ctx: Ctx, item: PlanItem):
    _design(ctx, item, "deck", f"ارائهٔ کوتاهِ {ctx.f['name']} (پیش‌نویس)",
            {"brief": f"معرفیِ {ctx.f['name']} به {ctx.f['audience_short']}: چه کاری می‌کند و چطور شروع کنیم.", "use_ai": False})
    item.draft = item.draft or "خروجی‌ها: PPTX، PDF، PNG و ویدیو (همین برنامه، روزِ ۶) از «استودیوی طراحی ⇐ ارائه»."


@producer("landing")
def p_landing(ctx: Ctx, item: PlanItem):
    from apps.design_studio import bridges

    doc = _design(ctx, item, "ui", f"طرحِ صفحهٔ فرودِ {ctx.f['name']} (UI/UX)", {"template": "landing"})
    if doc is None:
        return
    site = (doc.meta or {}).get("site") or {}
    if not site.get("project_id"):
        try:
            made = bridges.create_site(doc, ctx.owner, {"name": f"{ctx.f['name']} — پیش‌نویسِ صفحهٔ فرود"})
            site = made if isinstance(made, dict) else {}
            doc.refresh_from_db()
            site = (doc.meta or {}).get("site") or site
        except Exception as exc:  # noqa: BLE001 — بدونِ سایت‌ساز هم طرحِ UI پیش‌نویس است
            item.message = f"طرحِ UI آماده است؛ پیش‌نویسِ سایت ساخته نشد: {str(exc)[:120]}"
    pid = site.get("project_id") or site.get("id")
    if pid:
        refs.add(item, refs.make("site_project", pid, "پیش‌نویسِ صفحهٔ فرود (سایت‌ساز)", "/tools/studio"))
        item.message = "طرحِ UI و پیش‌نویسِ سایت آماده است؛ هیچ‌چیز منتشر نشده."
    item.draft = item.draft or "طرحِ دسکتاپ، تبلت و گوشی با قطعه‌های سایت‌ساز؛ از «ساختِ سایت از این طرح» پیش‌نویسِ سایت ساخته می‌شود (منتشر نمی‌شود)."


@producer("video_edit")
def p_video_edit(ctx: Ctx, item: PlanItem):
    from apps.design_studio import bridges, services as S
    from apps.design_studio.models import DesignDoc, DesignExport

    _drop_dead(item, "design_export")
    deck_item = ctx.sibling((item.meta or {}).get("for"))
    deck_ref = refs.of_type(deck_item, "design_doc") if deck_item else []
    doc = DesignDoc.objects.filter(pk=deck_ref[0]["id"]).first() if deck_ref else DesignDoc.objects.filter(store=ctx.store, kind="deck").order_by("id").first()
    held = apply_price_hold(ctx, doc) if doc is not None else []                 # قیمتِ تأییدنشده پیش از ساختنِ اسلایدهای ویدیو برداشته شود
    meta = dict(item.meta or {})
    if held:
        meta["checks"] = ["اسلایدهای این ویدیو بدونِ قیمتِ تأییدنشده ساخته شد (قیمتِ «" + "»، «".join(n[:40] for n in held[:3]) + "» هنوز تأیید نشده)."]
    else:
        meta.pop("checks", None)
    item.meta = meta
    live = _alive(item, "design_export")
    if live and doc is not None:
        e = DesignExport.objects.filter(pk=live[0]["id"]).first()
        old_id = e.pk if e is not None else None
        if e is not None and e.doc_rev != doc.rev and _cancel_queued_export(e):
            refs.remove(item, "design_export", old_id)           # ویدیوی منتظر با اسلایدهای قدیمی (مثلاً با قیمتِ تأییدنشده) ⇒ دوباره با اسلایدهای فعلی
            live = []
    if live:
        return
    if doc is None:
        raise NeedsYou("اول «ارائه» ساخته شود (روزِ ۶)؛ ویدیو از اسلایدهای آن ساخته می‌شود.")
    old = DesignExport.objects.filter(doc=doc, kind="mp4").exclude(state=DesignExport.State.FAILED).order_by("-id").first()
    try:
        exp = old or bridges.deck_to_video(doc, ctx.owner, {"seconds": 5})
    except S.DesignError as exc:
        raise NodeNotReady(str(exc)) from exc
    refs.add(item, refs.make("design_export", exp.pk, "ویدیو از ارائه", ctx.url("design_deck")))
    item.draft = item.draft or "اسلایدها با گذارِ ملایم به MP4 تبدیل می‌شود؛ ساختنش روی سرورِ پردازش است."
    item.message = "ویدیو در صفِ ماندگارِ سرورِ پردازش است و با روشن‌شدنِ گره خودش ساخته می‌شود."


def _cancel_queued_export(e) -> bool:
    """ویدیوی ارائه‌ای که هنوز در صف است (کار شروع نشده) را لغو و پاک می‌کند تا با اسلایدهای فعلی دوباره ساخته شود. ⇒ True اگر پاک شد."""
    from apps.compute import services as CS
    from apps.compute.models import ComputeJob
    from apps.design_studio.models import DesignExport

    if e.kind != "mp4" or e.state not in (DesignExport.State.QUEUED, DesignExport.State.RUNNING):
        return False
    job = ComputeJob.objects.filter(uid=(e.info or {}).get("job")).first() if (e.info or {}).get("job") else None
    if job is not None and job.state != ComputeJob.State.QUEUED:
        return False                                               # کار شروع شده؛ دست نمی‌زنیم
    if job is not None:
        CS.cancel(job, "اسلایدهای ارائه عوض شد؛ ویدیو با اسلایدهای تازه دوباره ساخته می‌شود")
    e.delete()
    return True


# ----------------------------------------------------------------------------- رسانه (GPU): موشن، گوینده، موسیقی، تامنیل، تصویر، شخصیت، سه‌بعدی

def _script_for(ctx: Ctx, item: PlanItem) -> str:
    """متنِ گوینده: اول همان چیزی که ریلزِ همراه برای گفتن نوشته («متنِ گویندگی (پیشنهادی)» یا خط‌های «نریشن:»)، وگرنه متنِ ساختهٔ زاویه
    (که فقط جمله‌های خواندنی دارد، نه دستورِ نویسنده)."""
    comp = ctx.sibling((item.meta or {}).get("for"))
    if comp is not None and comp.draft:
        said = drafts.narration_from_draft(comp.draft)
        if said:
            return said
    return drafts.reel_script(ctx.f, (item.meta or {}).get("pillar") or "intro")


ZWNJ = chr(0x200C)                                   # نیم‌فاصله
_WORD = re.compile(r"[\w" + ZWNJ + r"]+")
_DIAC = re.compile("[" + chr(0x64B) + "-" + chr(0x65F) + chr(0x670) + "]")      # اعراب (کسره، فتحه، …)؛ «نگرانیِ» با «نگرانی» یکی است
_STOP = {"موشن", "ویدیو", "ویدیوی", "ریلز", "ریلزِ", "پیش‌نویس", "چیست", "برای", "این", "همین", "یک", "با", "از", "در", "به", "که", "را", "کاورِ", "کاور",
         "صدای", "گوینده", "لایهٔ", "تلفظ", "تصویر", "هوش", "مصنوعی", "مصنوعیِ", "پست"}
_STOP = {_DIAC.sub("", w) for w in _STOP}


def _topic_words(text: str, f: dict) -> set[str]:
    """واژه‌های معنادارِ یک متنِ فارسی (بدونِ نامِ فروشگاه و واژه‌های عمومیِ «موشن/ریلز/…»)، برای سنجیدنِ این‌که دو چیز دربارهٔ یک موضوع‌اند."""
    brand = {_DIAC.sub("", w) for w in _WORD.findall(str(f.get("name") or ""))}
    out = set()
    for w in _WORD.findall(str(text or "")):
        w = _DIAC.sub("", w).strip(ZWNJ)
        if len(w) >= 3 and w not in _STOP and w not in brand and not w.isdigit():
            out.add(w)
    return out


def _motion_fits(render, item: PlanItem, ctx: Ctx) -> bool:
    """رندرِ موشنِ دورهای قبل فقط وقتی به این کار وصل می‌شود که هم‌قاب (۹:۱۶) و هم‌موضوع باشد؛ وگرنه عنوانِ کار یک چیز می‌گوید و ویدیو چیزِ دیگر."""
    if render.aspect != "9:16":
        return False
    want = _topic_words(item.title, ctx.f)
    have = _topic_words(f"{render.title} {render.spec}", ctx.f)
    return bool(want & have)


@producer("motion")
def p_motion(ctx: Ctx, item: PlanItem):
    from apps.motion import services as M
    from apps.motion.models import MotionRender as R

    for r in refs.of_type(item, "motion_render"):                     # رندرِ قدیمیِ ناهم‌موضوع/ناهم‌قاب که پیش‌تر وصل شده بود جدا می‌شود (خودِ رندر دست‌نخورده می‌ماند)
        old = R.objects.filter(pk=r["id"]).first()
        if old is not None and old.created_at < ctx.plan.created_at and not _motion_fits(old, item, ctx):
            refs.remove(item, "motion_render", old.pk)
    _drop_dead(item, "motion_render")
    if _alive(item, "motion_render"):
        return
    for r in refs.of_type(item, "motion_render"):                     # رندرِ ناموفق: خودش در بخش «موشن» می‌ماند، ولی این کار دوباره می‌سازد و پیوندِ کهنه نمی‌ماند
        refs.remove(item, "motion_render", r["id"])
    taken = refs.linked_ids(ctx.plan, "motion_render", exclude_item=item)
    spare = [r for r in R.objects.filter(store=ctx.store, target=R.Target.NODE).exclude(state__in=(R.State.FAILED, R.State.CANCELLED)).order_by("id")
             if str(r.pk) not in taken and _motion_fits(r, item, ctx)]
    if spare:
        render = spare[0]
        item.message = "رندرِ موشنِ آماده از قبل (هم‌موضوع و هم‌قاب) به برنامه وصل شد."
    else:
        spec = drafts.motion_spec(ctx.f, (item.meta or {}).get("pillar") or "intro")
        try:
            render = M.create(ctx.store, ctx.owner, mode=R.Mode.TEMPLATE, title=item.title[:120], spec=spec, quality="720", target="node")
            render = M.start(render)
        except M.MotionError as exc:
            raise NodeNotReady(str(exc)) from exc
        if render.state == R.State.FAILED:           # مثلاً «فروشگاه لوگو ندارد»: خطای کار می‌شود و بعد از چند بار تلاش متوقف می‌شود (نه هر ده دقیقه یک رندرِ ناموفقِ تازه)
            raise RuntimeError((render.error or render.message or "رندرِ موشن شروع نشد")[:200])
        item.message = "رندرِ موشن در صفِ سرورِ پردازش گذاشته شد؛ با روشن‌شدنِ گره خودش رندر می‌شود."
    refs.add(item, refs.make("motion_render", render.pk, render.title, ctx.url("motion")))
    item.draft = item.draft or f"سبک: {render.style} · قاب: {render.aspect}"


@producer("voiceover")
def p_voiceover(ctx: Ctx, item: PlanItem):
    from apps.ai.models import AudioAsset
    from services.audio import studio

    _drop_dead(item, "audio_asset")
    meta = dict(item.meta or {})
    auto = _script_for(ctx, item)
    # متنی که مالک خودش در کارت عوض کرده (با آخرین متنِ خودکار فرق دارد) همان می‌ماند؛ وگرنه هر اجرا متنِ درستِ روز را از ریلزِ همراه می‌گیرد
    edited = bool(item.draft) and meta.get("auto_script") is not None and item.draft != meta["auto_script"]
    script = item.draft if edited else auto
    item.draft = script
    item.meta = {**meta, "auto_script": auto}
    _checks(item, script, ctx.f)
    live = _alive(item, "audio_asset")
    if live:
        asset = AudioAsset.objects.filter(pk=live[0]["id"]).first()
        if asset is None or asset.status != AudioAsset.Status.PENDING or " ".join(str(asset.text).split()) == " ".join(script.split()):
            return
        old_id = asset.pk
        _retire_pending_voice(asset)              # صدایی که هنوز ساخته نشده و متنش با متنِ درست فرق دارد (مثلاً دستورِ نویسنده یا نشانیِ خراب) ⇒ با متنِ درست دوباره
        refs.remove(item, "audio_asset", old_id)
    voices = [v for v in studio.voices(ctx.store) if v.get("engine") == "moss-fa"]
    if not voices:
        raise NodeNotReady("صداهای MOSS هنوز از سرورِ پردازش گزارش نشده؛ با روشن‌شدنِ گره ساخته می‌شود.")
    try:
        asset = studio.create_speech(ctx.store, ctx.owner, text=script, voice_id=voices[0]["id"], title=item.title[:100])
    except studio.StudioError as exc:
        raise NodeNotReady(str(exc)) from exc
    if isinstance(asset, AudioAsset):
        refs.add(item, refs.make("audio_asset", asset.pk, asset.title or "گوینده", ctx.url("audio_speech")))
    item.message = "صدا با لایهٔ تلفظِ فارسی در صفِ سرورِ پردازش گذاشته شد؛ با روشن‌شدنِ گره ساخته می‌شود."


def _retire_pending_voice(asset) -> None:
    """صدای ساخته‌نشده را با کارِ صفش کنار می‌گذارد: کارِ منتظر لغو می‌شود و ردیفِ صدا پاک (جایش را صدای تازه با متنِ درست می‌گیرد)."""
    from apps.compute import services as CS
    from apps.compute.models import ComputeJob

    job = ComputeJob.objects.filter(uid=asset.job_uid).first() if asset.job_uid else None
    if job is not None and not job.final:
        CS.cancel(job, "متنِ گوینده اصلاح شد؛ صدا با متنِ درست دوباره ساخته می‌شود")
    asset.delete()


@producer("music")
def p_music(ctx: Ctx, item: PlanItem):
    from apps.ai.models import AudioAsset
    from services.audio import studio

    _drop_dead(item, "audio_asset")
    #: «موسیقیِ آغازین» (starter) نمونهٔ CC0 ِ خودِ سامانه است، نه موسیقیِ ساخته‌شده با ACE-Step که این کار می‌خواهد؛ فقط برای شنیدنِ فوری کنارش می‌ماند
    music_rows = {a.pk: a for a in AudioAsset.objects.filter(pk__in=[r["id"] for r in _alive(item, "audio_asset")])}
    if any(a.kind == AudioAsset.Kind.MUSIC and a.engine != "starter" for a in music_rows.values()):
        return
    taken = refs.linked_ids(ctx.plan, "audio_asset", exclude_item=item)
    spare = [a for a in AudioAsset.objects.filter(store=ctx.store, kind=AudioAsset.Kind.MUSIC).exclude(status=AudioAsset.Status.FAILED).exclude(engine="starter").order_by("id")
             if str(a.pk) not in taken]
    tone = ctx.f.get("tone", "")
    style, word = ("calm", "آرام") if "آرام" in tone else ("corporate", "رسمی") if "رسمی" in tone else ("upbeat", "شاد")
    if spare:
        asset = next((a for a in spare if word in (a.title or "")), spare[0])
    else:
        try:
            asset = studio.create_music(ctx.store, ctx.owner, style=style, seconds=30, title=f"موسیقیِ زمینهٔ {ctx.f['name']}"[:100])
        except studio.StudioError as exc:
            raise NodeNotReady(str(exc)) from exc
    refs.add(item, refs.make("audio_asset", asset.pk, asset.title or "موسیقی", ctx.url("audio_music")))
    starter = next((a for a in music_rows.values() if a.engine == "starter"), None)
    item.draft = item.draft or ("موسیقیِ بی‌کلام (ACE-Step) برای زیرِ ریلز و ویدیو" + (
        f"؛ تا ساخته‌شدنش «{(starter.title or 'موسیقیِ آغازین')[:50]}» (نمونهٔ بی‌حق‌نشرِ سامانه) را می‌شود شنید." if starter else "."))
    item.message = "موسیقیِ ACE-Step در صفِ سرورِ پردازش است و با روشن‌شدنِ گره ساخته می‌شود."


_THUMB_STYLE = {"intro": "magazine_cover", "how": "number_list", "objection": "question_hook", "faq": "question_hook", "offer": "product_hero",
                "process": "split_ba", "behind": "minimal_luxury", "series": "quote_card"}


def _thumb(ctx: Ctx, item: PlanItem, fmt: str, label: str):
    from apps.thumbs import aibg, services as T
    from apps.thumbs.models import Thumbnail

    for r in refs.of_type(item, "thumbnail"):                          # تامنیلِ دورهای قبل که قابش با این کار نمی‌خواند (مثلاً ۴:۵ برای «کاورِ ۹:۱۶») جدا می‌شود
        old = Thumbnail.objects.filter(pk=r["id"]).first()
        if old is not None and old.created_at < ctx.plan.created_at and old.format != fmt:
            refs.remove(item, "thumbnail", old.pk)
    _drop_dead(item, "thumbnail")
    if _alive(item, "thumbnail"):
        return
    taken = refs.linked_ids(ctx.plan, "thumbnail", exclude_item=item)
    waiting = [t for t in Thumbnail.objects.filter(store=ctx.store, state=Thumbnail.State.WAITING_BG, format=fmt).order_by("id") if str(t.pk) not in taken]
    if waiting and item.kind == "thumbnail":
        made = [waiting[0]]
        item.message = "تامنیلِ هم‌قابِ منتظرِ پس‌زمینهٔ هوش مصنوعی از قبل به برنامه وصل شد."
    else:
        if aibg._active_count(ctx.store) >= aibg.MAX_ACTIVE:
            raise NodeNotReady("چند پس‌زمینهٔ هوش مصنوعی در صف است؛ بعد از اجرای آن‌ها این یکی ساخته می‌شود.")
        pillar = (item.meta or {}).get("pillar") or "intro"
        spec = {"format": fmt, "style": _THUMB_STYLE.get(pillar, "question_hook"), "content": drafts.thumb_content(ctx.f, pillar),
                "background": {"kind": "ai", "job": ""}}
        try:
            made = T.create(ctx.store, ctx.owner, spec, variants=1, title=f"{ctx.f['name']} — {label}"[:150],
                            ai={"text": "", "preset": drafts.bg_preset(ctx.f, pillar), "prompt_en": ""})
        except T.ThumbError as exc:
            raise NodeNotReady(str(exc)) from exc
        item.message = "نسخهٔ خودکار همین حالا آماده است؛ پس‌زمینهٔ هوش مصنوعی (FLUX) با روشن‌شدنِ گره جایگزین می‌شود."
    for t in made:
        refs.add(item, refs.make("thumbnail", t.pk, t.title, ctx.url("thumbnail_maker")))


@producer("thumbnail")
def p_thumbnail(ctx: Ctx, item: PlanItem):
    _thumb(ctx, item, "story", "کاورِ ریلز")
    item.draft = item.draft or "کاورِ ۹:۱۶ با تیترِ قلاب‌دار؛ بعد از آماده شدن در ادیتورِ عکس هم قابل‌ویرایش است."


@producer("image")
def p_image(ctx: Ctx, item: PlanItem):
    from apps.campaigns.tasks_board import CampaignTask as CT

    # کارِ «تصویرِ زمینهٔ هوش مصنوعی» که کمپین‌های قبلی نوشته‌اند به همین کار وصل می‌شود
    if not _alive(item, "campaign_task"):
        for t in _candidate_tasks(ctx, item, ("تصویرِ زمینهٔ هوش مصنوعی",)):
            refs.add(item, _task_ref(ctx, t))
            _retime_task(t, item.scheduled_for)
            item.draft = item.draft or t.detail
            break
    _thumb(ctx, item, "ig_portrait", "تصویرِ هوش مصنوعیِ پست")
    item.draft = item.draft or "پس‌زمینهٔ FLUX بی‌متن؛ در «ادیتور عکس ⇐ طراحِ خودکار» لوگو و متنِ فارسی رویش می‌نشیند."


def _cancel_char_job(row) -> None:
    """کارِ ساختِ تصویرِ شخصیتِ تکراری (هنوز در صف) را لغو می‌کند."""
    from apps.brandchar import ai_render
    from apps.brandchar.models import CharacterAIJob
    from apps.compute import services as CS

    job = ai_render._job_of(row)
    if job is not None and not job.final:
        CS.cancel(job, "ژستِ تکراریِ برنامه؛ لغو شد")
    row.state, row.message = CharacterAIJob.State.FAILED, "لغو شد (ژستِ تکراریِ برنامه)"
    row.save(update_fields=["state", "message", "updated_at"])


@producer("character")
def p_character(ctx: Ctx, item: PlanItem):
    from apps.brandchar import ai_render, services as S
    from apps.brandchar.models import BrandCharacter, CharacterAIJob

    _drop_dead(item, "character_job")
    char = S.primary(ctx.store) or BrandCharacter.objects.filter(store=ctx.store).order_by("id").first()
    if char is None:
        char = S.create(ctx.store, ctx.owner)
    try:
        S.ensure_cover(char, ctx.owner)               # تصویرِ برداریِ فوری (بدونِ GPU) تا گالری خالی نماند
    except Exception as exc:  # noqa: BLE001
        logger.info("mktplan: cover render skipped: %s", exc)
    refs.add(item, refs.make("character", char.pk, char.name, ctx.url("brandchar_gallery")))
    # «کاور» همان ژستِ ایستاده است؛ «ژست‌های بیشتر» فقط ژست‌های دیگر (ایستاده را دوباره با seedِ دیگر نمی‌سازد)
    poses = ["wave", "think", "cheer"] if item.key.endswith(".poses") else ["stand"]
    have_poses = set()
    for r in _alive(item, "character_job"):
        j = CharacterAIJob.objects.filter(pk=r["id"]).first()
        if j is not None and j.pose not in poses and j.created_at >= ctx.plan.created_at and j.state == CharacterAIJob.State.QUEUED:
            refs.remove(item, "character_job", j.pk)       # تکرارِ «ایستاده»ی همین برنامه (هنوز شروع نشده) لغو می‌شود
            _cancel_char_job(j)
        elif j is not None and j.pose in poses:
            have_poses.add(j.pose)
    taken = refs.linked_ids(ctx.plan, "character_job", exclude_item=item)
    spare = [j for j in CharacterAIJob.objects.filter(store=ctx.store).exclude(state=CharacterAIJob.State.FAILED).order_by("id") if str(j.pk) not in taken]
    for pose in poses:
        if pose in have_poses:
            continue
        job = next((j for j in spare if j.pose == pose and j.mode == "illustrated"), None)
        if job is not None:
            spare.remove(job)
        else:
            try:
                job = ai_render.start(char, ctx.owner, mode="illustrated", pose=pose, expression="happy")
            except ai_render.AIRenderError as exc:
                raise NodeNotReady(str(exc)) from exc
        refs.add(item, refs.make("character_job", job.pk, f"تصویرِ هوش مصنوعیِ شخصیت ({job.pose or pose})", ctx.url("brandchar_gallery")))
    item.draft = item.draft or "تصویرهای FLUX از شخصیتِ برند (ژست‌های مختلف)؛ در «شخصیتِ برند ⇐ گالری» دیده و در موشن و تامنیل استفاده می‌شود."
    item.message = "کارِ ساختِ تصویر در صفِ ماندگارِ سرورِ پردازش است."


#: پروفایلِ رندرِ ویدیوی سه‌بعدیِ برنامه: «standard» (۱۲۸۰ پیکسل، کلاسِ GPU)؛ کارِ GPU در صفِ پردازش کمترین اولویت را دارد (۱۵۰) و بعد از کارهای دیگرِ برنامه اجرا می‌شود
RENDER_PROFILE = "standard"
MAX_RENDER_FAILS = 3


def _up3d_brief(ctx: Ctx) -> dict:
    """خلاصهٔ پروژهٔ سه‌بعدی از واقعیت‌های فروشگاه. «cta» و «cta_short» را عمداً می‌دهیم: قالبِ «showcase» بدونِ آن‌ها می‌گوید «همین حالا از آپ‌مارکت
    سفارش بدید!» و روی صفحه می‌نویسد «سفارش در آپ‌مارکت»؛ یعنی ادعایی که دربارهٔ هیچ فروشگاهِ دیگری درست نیست."""
    cta = (ctx.f.get("cta") or "همین حالا شروع کنید").strip()
    return {"product_name": ctx.f["flagship"] or ctx.f["name"], "description": drafts._one_liner(ctx.f)[:300], "brand": ctx.f["name"],
            "audience": ctx.f["audience"][:160], "cta": cta[:80], "cta_short": cta[:30]}


def _fix_default_cta(ctx: Ctx, proj) -> bool:
    """پروژه‌ای که صحنه‌اش هنوز دعوتِ پیش‌فرضِ قالب («آپ‌مارکت») را دارد دوباره از قالب با دعوتِ خودِ برند ساخته می‌شود (نسخهٔ تازه؛ نسخهٔ قبلی می‌ماند). ⇒ True اگر عوض شد."""
    import json

    from apps.up3d import services as U

    default = "آپ" + ZWNJ + "مارکت"
    v = proj.current
    if v is None or default in str(ctx.f.get("name") or "") or default not in json.dumps(v.document, ensure_ascii=False):
        return False
    brief = {**(proj.brief or {}), **_up3d_brief(ctx)}
    plan_job = proj.jobs.filter(kind="plan").order_by("created").first()
    template = ((plan_job.params or {}).get("template") if plan_job is not None else None) or "showcase"
    doc = U.templates.build(template, brief, U.reg())
    proj.brief = brief
    proj.save(update_fields=["brief"])
    new = U.new_version(proj, doc, source="template", note="اصلاح: دعوتِ آخر از برندِ فروشگاه، نه قالبِ «آپ‌مارکت»")
    for j in proj.jobs.exclude(state__in=("COMPLETED", "FAILED", "CANCELLED")).filter(kind="render").exclude(version=new):
        U.cancel(j)                                                       # رندری که هنوز با صحنهٔ قدیمی در صف بود
    return True


@producer("up3d")
def p_up3d(ctx: Ctx, item: PlanItem):
    from apps.up3d import services as U
    from apps.up3d.models import Project

    _drop_dead(item, "up3d_job")
    live = _alive(item, "up3d_project")
    proj = Project.objects.filter(pk=live[0]["id"]).first() if live else None
    if proj is None:
        taken = refs.linked_ids(ctx.plan, "up3d_project", exclude_item=item)
        title = f"{ctx.f['name']} — ویدیوی سه‌بعدیِ کوتاه"
        proj = Project.objects.filter(owner=ctx.owner, title=title).first()
        if proj is None:
            proj, _job = U.create_project(ctx.owner, _up3d_brief(ctx), mode="template", template="showcase", title=title)
        if str(proj.pk) in taken:
            return
        refs.add(item, refs.make("up3d_project", proj.pk, proj.title, "/tools/3d"))
    if _fix_default_cta(ctx, proj):                                   # صحنه‌ای که با دعوتِ آماده‌ٔ قالب («سفارش در آپ‌مارکت») ساخته شده بود از نو با دعوتِ خودِ برند ساخته می‌شود
        item.message = "دعوتِ آخرِ ویدیوی سه‌بعدی (قالب «آپ‌مارکت» می‌گفت) با دعوتِ خودِ برند عوض شد."
    item.draft = item.draft or "پیش‌نویسِ پروژه ساخته شد؛ رندرِ نهایی همین حالا در صفِ سرورِ پردازش است و با روشن‌شدنِ کارتِ گرافیک خودش ساخته می‌شود."
    # رندرِ نهایی هم همین‌جا در صفِ ماندگار گذاشته می‌شود (پیش‌تر فقط پیش‌نویسِ پروژه بود و رندر یک کلیکِ دستی می‌خواست)
    if _alive(item, "up3d_job"):
        return
    for r in refs.of_type(item, "up3d_job"):                          # رندرِ ناموفق: خودش در صفحهٔ سه‌بعدی می‌ماند؛ این کار از نو صف می‌شود
        refs.remove(item, "up3d_job", r["id"])
    existing = proj.jobs.filter(kind="render").exclude(state__in=("FAILED", "CANCELLED")).order_by("-created").first()
    if existing is not None:
        job = existing
    else:
        # فقط شکست‌های رندرهایی که با «silent_fallback» خواسته شده‌اند حساب می‌شوند؛ رندرهای قدیمیِ بی‌پرچم (که با خطای ۴۰۲ی صدا همان لحظه می‌شکستند) نه
        failed = [j for j in proj.jobs.filter(kind="render", state="FAILED").order_by("-created")[:20] if (j.params or {}).get("silent_fallback")][:MAX_RENDER_FAILS]
        if len(failed) >= MAX_RENDER_FAILS:           # بارها ناموفق بوده؛ هر ده دقیقه یک رندرِ ناموفقِ تازه نمی‌سازیم (خطا به کارت می‌رسد و تلاش‌ها بعد از چند بار متوقف می‌شود)
            raise RuntimeError(f"رندرِ سه‌بعدی {fa_digits(str(len(failed)))} بار ناموفق بود: {(failed[0].message or failed[0].error or '')[:160]}")
        try:
            # silent_fallback: اگر سرویسِ صدای آنلاین (اعتبارِ متیس) جواب نداد رندر بی‌صدا ادامه می‌دهد، نه این‌که از همان اول بشکند
            job = U.request_job(proj, "render", RENDER_PROFILE, {"silent_fallback": True})
        except ValueError as exc:                    # پروژه هنوز صحنه ندارد (برنامه‌ریزیِ قالب چند ثانیه می‌گیرد) ⇒ تیکِ بعد دوباره
            item.meta = {**(item.meta or {}), "retry_soon": True}
            item.message = f"پروژهٔ سه‌بعدی ساخته شد؛ رندرش چند لحظهٔ دیگر در صف می‌رود ({str(exc)[:80]})."
            return
    item.meta = {k: v for k, v in (item.meta or {}).items() if k != "retry_soon"}
    refs.add(item, refs.make("up3d_job", job.pk, "رندرِ ویدیوی سه‌بعدی", "/tools/3d"))
    item.message = "رندرِ ویدیوی سه‌بعدی در صفِ ماندگارِ سرورِ پردازش است و با روشن‌شدنِ گره خودش ساخته می‌شود."


# ----------------------------------------------------------------------------- پیام‌ها: ایمیل، پیامک، بازبینی

@producer("email")
def p_email(ctx: Ctx, item: PlanItem):
    _set_draft(ctx, item, drafts.email_draft(ctx.f, (item.meta or {}).get("pillar") or "intro"))
    item.message = "متنِ ایمیل آماده است؛ چیزی نرفته است. موضوع و متن را بخوانید و از همین‌جا کپی کنید."


@producer("sms")
def p_sms(ctx: Ctx, item: PlanItem):
    from apps.inbox.models import Broadcast

    text = item.draft or drafts.sms_text(ctx.f)
    _set_draft(ctx, item, text)
    name = f"[برنامه] {item.title}"[:120]
    b = Broadcast.objects.filter(store=ctx.store, name=name).first()
    if b is None:
        b = Broadcast.objects.create(store=ctx.store, name=name, text=item.draft, channels=["SMS"], status=Broadcast.Status.DRAFT, created_by=ctx.owner)
    refs.add(item, refs.make("broadcast", b.pk, b.name, ctx.url("inbox_broadcasts")))
    item.message = "پیش‌نویسِ ارسالِ گروهی ساخته شد؛ تا «پیش‌نمایش ← ارسال برای تأیید ← تأییدِ مالک» چیزی نمی‌رود."


@producer("review")
def p_review(ctx: Ctx, item: PlanItem):
    wk = (item.meta or {}).get("week") or 1
    lo, hi = (1, 7) if wk == 1 else (8, 14)
    items = [i for i in ctx.plan.items.all() if lo <= i.day <= hi and i.kind != "review"]
    done = sum(1 for i in items if i.decision in ("approved", "done"))
    item.draft = (f"هفتهٔ {clock.fa_digits(str(wk))}: {clock.fa_digits(str(len(items)))} کار در برنامه بود، {clock.fa_digits(str(done))} کار تأیید یا منتشر شد.\n"
                  "برای بازبینی: «کمپین‌ها ⇐ چه چیزی جواب داد» را ببینید؛ هر پستی که منتشر شد را آنجا ثبت کنید تا NM یاد بگیرد چه چیزی جواب می‌دهد. "
                  "بعد تصمیم بگیرید: کدام زاویه را تکرار کنیم و کدام را کنار بگذاریم؟")
    item.meta = {**(item.meta or {}), "needs_you": "این بازبینی با نتیجهٔ واقعیِ پست‌ها انجام می‌شود؛ فقط شما می‌توانید ثبتش کنید."}
    item.message = item.meta["needs_you"]


def run_one(ctx: Ctx, item: PlanItem) -> dict:
    """یک کار را می‌سازد. ⇒ {"ok": bool, "error": str, "waiting": bool}؛ هیچ‌وقت استثنا نمی‌دهد."""
    fn = PRODUCERS.get(item.kind)
    meta = dict(item.meta or {})
    for k in ("waiting_node", "needs_you"):          # هر تولیدکننده اگر هنوز لازم باشد دوباره می‌گذاردشان
        meta.pop(k, None)
    item.meta = meta
    if fn is None:
        return {"ok": False, "error": "تولیدکنندهٔ این نوع کار ثبت نشده", "waiting": False}
    try:
        fn(ctx, item)
        item.last_error = ""
        return {"ok": True, "error": "", "waiting": False}
    except NeedsYou as exc:
        item.meta = {**(item.meta or {}), "needs_you": str(exc)}
        item.message, item.last_error = str(exc)[:290], ""
        return {"ok": True, "error": "", "waiting": False}
    except NodeNotReady as exc:
        item.meta = {**(item.meta or {}), "waiting_node": str(exc)}
        item.message, item.last_error = str(exc)[:290], ""
        return {"ok": True, "error": "", "waiting": True}
    except Exception as exc:  # noqa: BLE001 — خرابیِ یک کار نباید برنامه را متوقف کند
        logger.exception("mktplan: producer %s failed for %s", item.kind, item.key)
        item.last_error = f"{exc.__class__.__name__}: {exc}"[:500]
        item.message = "ساخته نشد؛ در اجرای بعدی دوباره امتحان می‌شود."
        return {"ok": False, "error": item.last_error, "waiting": False}

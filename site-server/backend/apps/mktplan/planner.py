"""سازندهٔ «برنامهٔ بازاریابی» — یک برنامهٔ دو‌هفته‌ای عمومی برای هر فروشگاه.

هیچ چیزِ مخصوصِ یک فروشگاه این‌جا نیست: قالبِ روزها (``SLOTS``) و «زاویه‌ها» (``PILLARS``) برای همهٔ فروشگاه‌ها یکی است و جای‌گیرهای
{فروشگاه} {محصول} {مخاطب} {حوزه} از پروفایلِ همان فروشگاه پر می‌شوند (همان جای‌گیرهای بانکِ ایده). هر کار به بخشِ پنلی که می‌سازدش وصل است
و وضعیتِ خودش را دارد؛ ساختنِ واقعیِ محتوا کارِ ``runner`` است، نه این‌جا.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction

from apps.ideabank import fill as idea_fill

from . import clock, facts as facts_mod, kinds
from .models import MarketingPlan, PlanItem

DAYS = 14

#: زاویه‌های محتوا: کلید ⇒ (عنوان، توضیحِ زاویه). متن‌ها ادعا ندارند؛ هرجا داده‌ای از خودِ مالک لازم است «[…]» می‌ماند.
PILLARS: dict[str, tuple[str, str]] = {
    "intro": ("معرفی: {فروشگاه} چیست؟", "در یک جمله بگویید {فروشگاه} چیست و به {مخاطب} چه کمکی می‌کند؛ بعد یک دعوتِ روشن."),
    "how": ("چطور کار می‌کند؟", "مسیرِ ساده‌یِ استفاده از {محصول} در چند قدمِ کوتاه؛ هر قدم یک جمله."),
    "objection": ("پاسخ به یک نگرانیِ رایج", "رایج‌ترین نگرانیِ {مخاطب} را صادقانه جواب دهید؛ بدونِ وعدهٔ اغراق‌آمیز و بدونِ مقایسه با رقیب."),
    "faq": ("پرسش‌های پرتکرار", "سه پرسشِ پرتکرار دربارهٔ {محصول} و پاسخِ کوتاهِ هرکدام (از متنِ پروفایل و قوانینِ فروشگاه)."),
    "offer": ("دعوت به شروع", "پیشنهادِ واقعیِ شما: [پیشنهادِ واقعیِ شما] — فقط آنچه واقعاً دارید؛ قیمت و تخفیف را خودتان بنویسید."),
    "behind": ("پشتِ صحنه", "کوتاه نشان دهید {فروشگاه} چطور ساخته و اداره می‌شود؛ بدونِ ادعا و بدونِ آمار."),
    "process": ("قبل و بعدِ روندِ کار", "مقایسهٔ روندِ کار (نه نتیجه): کارِ تکراری در برابرِ مسیرِ ساده‌تر با {محصول}."),
    "series": ("مجموعهٔ استوریِ تعاملی", "چند فریمِ پرسش، نظرسنجی و جعبهٔ سؤال تا مخاطب جواب بدهد."),
}

#: (روز، نوع، زاویه، پسوندِ کلید، کارِ همراه) — «کارِ همراه» کلیدِ کاری است که این کار برایش ساخته می‌شود (مثلاً گوینده برای ریلزِ ۱).
SLOTS: list[tuple[int, str, str, str, str]] = [
    (1, "profile", "", "bio", ""),
    (1, "ideas", "", "bank", ""),
    (1, "trends", "", "scan", ""),
    (1, "finder", "", "m1", ""),
    (1, "inbox", "", "setup", ""),
    (1, "character", "", "cover", ""),
    (1, "music", "", "bed", ""),
    (2, "landing", "", "draft", ""),
    (2, "carousel", "intro", "1", ""),
    (2, "story", "intro", "1", ""),
    (2, "thumbnail", "intro", "reel1", "d03.reel.1"),
    (3, "reel", "intro", "1", ""),
    (3, "voiceover", "intro", "reel1", "d03.reel.1"),
    (3, "motion", "intro", "reel1", "d03.reel.1"),
    (4, "post", "how", "1", ""),
    (4, "image", "how", "post1", "d04.post.1"),
    (4, "catalog", "", "1", ""),
    (5, "story", "series", "2", ""),
    (5, "dm", "", "1", ""),
    (5, "leads_review", "", "1", ""),
    (6, "carousel", "how", "2", ""),
    (6, "deck", "", "1", ""),
    (6, "video_edit", "", "deck1", "d06.deck.1"),
    (7, "review", "", "week1", ""),
    (7, "email", "intro", "1", ""),
    (8, "reel", "objection", "2", ""),
    (8, "voiceover", "objection", "reel2", "d08.reel.2"),
    (8, "motion", "objection", "reel2", "d08.reel.2"),
    (8, "thumbnail", "objection", "reel2", "d08.reel.2"),
    (9, "post", "faq", "2", ""),
    (9, "up3d", "", "1", ""),
    (9, "sms", "offer", "1", ""),
    (10, "carousel", "process", "3", ""),
    (10, "image", "process", "post2", "d09.post.2"),
    (10, "character", "", "poses", ""),
    (11, "reel", "offer", "3", ""),
    (11, "voiceover", "offer", "reel3", "d11.reel.3"),
    (11, "motion", "offer", "reel3", "d11.reel.3"),
    (12, "story", "faq", "3", ""),
    (12, "email", "offer", "2", ""),
    (13, "post", "behind", "3", ""),
    (13, "testimonial", "", "1", ""),
    (14, "review", "", "week2", ""),
    (14, "ideas", "", "next", ""),
    (14, "finder", "", "m2", ""),
]

#: عنوان و توضیحِ کارهایی که «زاویه» ندارند. {…} با جای‌گیرهای پروفایل پر می‌شود.
FIXED: dict[str, tuple[str, str]] = {
    "profile": ("پروفایل: بایو، هایلایت و پستِ سنجاق‌شده", "پیش از اولین پست: بایو (چند نسخه)، دسته‌های هایلایت، پستِ سنجاق‌شده و پاسخ‌های آمادهٔ کامنت و دایرکت."),
    "ideas": ("بانکِ ایده: ایده‌های این دو هفته", "ایده‌های آمادهٔ فارسی با جای‌گیرهای پروفایل؛ ستاره بزنید و «از این ایده شروع کن» را بزنید."),
    "trends": ("ترند و رقبا: دیدنِ آنچه همین حالا می‌گیرد", "هشتگ‌ها و پیج‌های حوزهٔ {حوزه} را بخوانید و ایده‌های ترند را با محصولِ خودتان جور کنید؛ خواندنِ اینستاگرام روی سرورِ پردازش است."),
    "finder": ("مشتری‌یاب: پیدا کردنِ مشتریِ بالقوه", "مأموریتِ پیدا کردنِ {مخاطب} در شهرِ هدف؛ لیدِ امتیازدار، راهِ تماس و پیش‌نویسِ پیام. چیزی خودکار فرستاده نمی‌شود."),
    "inbox": ("صندوقِ پیام: آماده کردنِ پاسخ‌گویی", "کانال‌ها، ربات، ساعتِ کاری و پاسخ‌های آماده؛ تا اولین پیامِ مشتری بی‌پاسخ نماند."),
    "character": ("شخصیتِ برند: تصویرِ هوش مصنوعی", "چهرهٔ دیداریِ برند (FLUX روی سرورِ پردازش) برای کاور و استوری؛ در صفِ ماندگار می‌ماند."),
    "music": ("موسیقیِ زمینه برای ویدیوها", "یک موسیقیِ بی‌کلام (روی سرورِ پردازش) برای زیرِ ریلز و ویدیو."),
    "landing": ("صفحهٔ فرود: پیش‌نویس در سایت‌ساز", "طرحِ صفحهٔ فرود با دادهٔ واقعیِ فروشگاه؛ هرگز منتشر نمی‌شود، فقط پیش‌نویس."),
    "catalog": ("کاتالوگِ محصولات (PDF و تصویر)", "کاتالوگِ چندصفحه‌ای از محصول‌های فروشگاه برای ارسال به مشتری و چاپ."),
    "deck": ("ارائهٔ کوتاه (اسلاید)", "ارائهٔ کوتاهِ معرفی برای جلسه یا ارسال؛ یادداشتِ گوینده دارد."),
    "video_edit": ("ویدیو از ارائه (روی سرورِ پردازش)", "اسلایدها با گذارِ ملایم، گوینده و موسیقی به ویدیو تبدیل می‌شود."),
    "up3d": ("ویدیوی سه‌بعدی: نمایشِ شخصیت/محصول", "پیش‌نویسِ یک ویدیوی سه‌بعدی کوتاه؛ رندر روی کارتِ گرافیکِ سرورِ پردازش."),
    "dm": ("پیش‌نویسِ دایرکت و پیامِ مشتری‌یاب", "برای لیدهای پیداشده پیام بنویسید؛ ارسال فقط بعد از تأییدِ شما."),
    "leads_review": ("بازبینیِ لیدهای مشتری‌یاب", "لیدهای دارای امتیازِ بالا را ببینید، برچسب بزنید و یادآوریِ پیگیری بگذارید."),
    "email": ("ایمیلِ پیش‌نویس", "یک ایمیلِ کوتاه با لحنِ برند (موضوع + متن)؛ فقط پیش‌نویس است."),
    "sms": ("پیامکِ پیش‌نویس (ارسالِ گروهی)", "یک پیامکِ کوتاه با جملهٔ لغو؛ در «ارسال گروهی» به‌صورتِ پیش‌نویس می‌ماند و فقط با تأییدِ شما می‌رود."),
    "review": ("بازبینی: چه چیزی جواب داد؟", "نتیجهٔ این هفته را از «چه چیزی جواب داد» بخوانید و تصمیمِ هفتهٔ بعد را بگیرید."),
    "testimonial": ("نظرِ واقعیِ یک مشتری (از شما)", "با اجازهٔ یک مشتریِ واقعی نظرش را بگیرید؛ نظرِ ساختگی هرگز ساخته نمی‌شود."),
    "thumbnail": ("کاورِ ریلز", "کاورِ ریلز با پس‌زمینهٔ هوش مصنوعی (روی سرورِ پردازش)؛ تا آماده شدن نسخهٔ خودکار دارد."),
    "voiceover": ("صدای گوینده (با لایهٔ تلفظ)", "متنِ گوینده با صدای MOSS و لایهٔ تلفظِ فارسی روی سرورِ پردازش."),
    "motion": ("ویدیوی موشن", "ویدیوی موشن‌گرافیکِ ریلز؛ رندرِ نهایی روی کارتِ گرافیک."),
    "image": ("تصویرِ هوش مصنوعی برای پست", "پس‌زمینهٔ تصویر با FLUX؛ بعد در ادیتورِ عکس لوگو و متن می‌گیرد."),
}


#: عنوانِ کارهایی که یک «نوع» را چند بار دارند ولی هر بار برای کاری دیگر (کلید: «نوع.پسوند»)
OVERRIDE: dict[str, tuple[str, str]] = {
    "ideas.next": ("بانکِ ایده: ایده‌های دو هفتهٔ بعد", "با دیدنِ آنچه جواب داد، ایده‌های تازه برای دو هفتهٔ بعد بسازید؛ ستاره‌ها جلو می‌افتند."),
    "finder.m2": ("مشتری‌یاب: دورِ دوم و پیگیری", "مأموریت را دوباره اجرا کنید (یا تکرارِ هفتگی بگذارید)؛ لیدِ قبلی دوباره ساخته نمی‌شود. یادآوری‌های عقب‌افتاده را انجام دهید."),
    "review.week1": ("بازبینیِ هفتهٔ ۱: چه چیزی جواب داد؟", FIXED["review"][1]),
    "review.week2": ("بازبینیِ دو هفته: چه چیزی جواب داد و بعد چه؟", "نتیجهٔ دو هفته را بخوانید و تصمیم بگیرید: کدام زاویه تکرار شود، کدام کنار برود و برنامهٔ دو هفتهٔ بعد چه باشد."),
    "character.poses": ("شخصیتِ برند: ژست‌های بیشتر", "چند ژستِ دیگر (دست‌تکان‌دادن، فکر، شادی) با FLUX برای استوری و کاور."),
}


def _fill(text: str, f: dict) -> str:
    return idea_fill.fill_text(text, {"values": f["placeholders"]})


def week_of(day: int) -> int:
    return 1 if day <= 7 else 2


def slot_items(f: dict, start: dt.date) -> list[dict[str, Any]]:
    """قالبِ ۴۶ کارِ دو هفته با جای‌گیرهای پرشده؛ ترتیبِ هر روز همان ترتیبِ ``SLOTS``."""
    out: list[dict[str, Any]] = []
    order: dict[int, int] = {}
    for day, kind, pillar, suffix, companion in SLOTS:
        order[day] = order.get(day, 0) + 1
        if pillar and kind in ("post", "carousel", "story", "reel"):
            title = f"{kinds.label(kind)}: {_fill(PILLARS[pillar][0], f)}"
            brief = _fill(PILLARS[pillar][1], f)
        elif kind in FIXED:
            title, brief = _fill(FIXED[kind][0], f), _fill(FIXED[kind][1], f)
            if f"{kind}.{suffix}" in OVERRIDE:
                title, brief = (_fill(x, f) for x in OVERRIDE[f"{kind}.{suffix}"])
            elif pillar:                                                  # گوینده/موشن/کاور/ایمیل/پیامک: عنوان به زاویه می‌چسبد
                title = f"{title} — {_fill(PILLARS[pillar][0], f)}"
        else:
            title, brief = kinds.label(kind), ""
        date = clock.day_date(start, day)
        out.append({
            "key": f"d{day:02d}.{kind}.{suffix}", "day": day, "order": order[day], "kind": kind, "section": kinds.default_section(kind),
            "title": title[:240], "brief": brief, "needs_node": kinds.needs_node(kind),
            "meta": {"pillar": pillar, "week": week_of(day), "for": companion, "date": date.isoformat()},
            "scheduled_for": clock.when_for(kind, date),
        })
    return out


def default_goal(f: dict) -> str:
    return (f"در دو هفته {f['name'] or 'فروشگاه'} را به {f['audience_short']} معرفی کنیم، اعتماد بسازیم و اولین خریدهای واقعی را بگیریم. "
            "همه‌چیز پیش‌نویس است؛ انتشار و ارسال فقط با تأییدِ شما انجام می‌شود.")


@transaction.atomic
def ensure_plan(store, user=None, *, start: dt.date | None = None, restart: bool = False, key: str = "starter") -> tuple[MarketingPlan, dict]:
    """برنامه را می‌سازد یا به‌روز می‌کند — اجرای دوباره هرگز کارِ موجود را پاک یا دوبرابر نمی‌کند.

    ⇒ (plan, {"created": bool, "added": n, "restarted": bool}). ``restart`` فقط تاریخِ شروع را به فردا می‌برد و ساعتِ کارها را دوباره می‌چیند؛
    تصمیم‌های مالک و چیزهای ساخته‌شده می‌ماند.
    """
    f = facts_mod.store_facts(store)
    plan = MarketingPlan.objects.select_for_update().filter(store=store, key=key).first()
    created = plan is None
    restarted = False
    if created:
        plan = MarketingPlan.objects.create(store=store, key=key, name=f"برنامهٔ بازاریابیِ {f['name'] or 'فروشگاه'} — دو هفتهٔ آغازین",
                                            goal=default_goal(f), start_date=start or clock.default_start(), days=DAYS,
                                            created_by=user if getattr(user, "is_authenticated", False) else None)
    elif restart or start is not None:
        new_start = start or clock.default_start()
        if new_start != plan.start_date:
            plan.start_date, restarted = new_start, True
    plan.summary = {**(plan.summary or {}), "facts": facts_mod.summary_public(f), "built_at": clock.today_tehran().isoformat()}
    plan.save()

    have = {i.key: i for i in plan.items.all()}
    added = 0
    for spec in slot_items(f, plan.start_date):
        row = have.get(spec["key"])
        if row is None:
            PlanItem.objects.create(plan=plan, **spec)
            added += 1
            continue
        changed = []
        meta = {**(row.meta or {}), "date": spec["meta"]["date"]}
        if row.scheduled_for != spec["scheduled_for"]:
            row.scheduled_for = spec["scheduled_for"]
            changed.append("scheduled_for")
            meta["retime"] = True                       # تاریخ عوض شد: کارِ کمپینِ وصل‌شده در اجرای بعدی به موعدِ تازه می‌رود
        if meta != row.meta:
            row.meta = meta
            changed.append("meta")
        if changed:
            row.save(update_fields=[*changed, "updated_at"])
    return plan, {"created": created, "added": added, "restarted": restarted}

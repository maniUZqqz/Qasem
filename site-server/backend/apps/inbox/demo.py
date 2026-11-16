"""«چغر» روی صندوق پیام: پیش‌نویسِ تنظیمات + گفتگوهای آزمایشی (علامت‌دار).

`seed(store)` یک فروشگاه را برای دیدنِ صندوق آماده می‌کند **بدون این‌که چیزی بیرون برود**:

* هیچ کانالی روشن نمی‌شود و هیچ توکنی گذاشته نمی‌شود - کانال‌ها «وصل نشده» می‌مانند؛
* همهٔ گفتگوها، مخاطب‌ها، پیگیری و ارسال گروهی `is_test` هستند: در هیچ آماری، هیچ بخشی و هیچ ارسالی نمی‌آیند،
  وب‌هوک نمی‌فرستند و ساعتِ SLA ندارند؛
* متن‌ها فقط از `docs/chagher/brand-facts-fa.md` آمده‌اند - قیمت و آمار نیست، چون آن سند همین‌ها را «تأییدنشده» می‌داند؛
* نام‌ها ساختگی‌اند (هیچ آدم واقعی در مخزن نیست).

دوبار اجرا کردن چیزی را دو برابر نمی‌کند (هر ردیف با نشانهٔ `demo-` شناخته می‌شود).
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message

from . import contacts, segments, team
from .models import (
    Broadcast, CannedReply, ChannelConnection, Contact, ConversationMeta, FollowUp, InboxSettings, MessageMeta,
)

BRAND = {"color": "#126F85", "title": "گفتگو با چغر", "subtitle": "پیامتان را بنویسید",
         "welcome": "سلام! دستیارِ چغر هستم. دربارهٔ چغر و برنامه‌سازیِ هوشمند برای مربی‌ها هر چه می‌خواهید بپرسید.",
         "position": "left", "auto_open": False}

CANNED = [
    ("چغر چیست؟", "chist",
     "چغر دستیار هوش مصنوعیِ مربی‌هاست؛ برنامهٔ ورزشی و غذاییِ هر ورزشکار را پیش‌نویس می‌کند و تصمیم نهایی همیشه با مربی است."),
    ("شروع رایگان", "start",
     "ثبت‌نام کمتر از یک دقیقه طول می‌کشد و شروعش رایگان است؛ کارت اعتباری نمی‌خواهد. از chagher.ir شروع کنید."),
    ("قیمت", "price",
     "قیمت و بسته‌های توکن در سایت chagher.ir منتشر شده است. اگر سؤال دقیق‌تری دارید یکی از همکاران پاسخ می‌دهد."),
    # «جایگزینِ مربی» is on the brand's never-say list (brand-facts-fa.md): say what the product
    # does next to the coach, not what it replaces.
    ("آیا مربی لازم است؟", "coach",
     "بله؛ چغر کنار مربی کار می‌کند: پیش‌نویس برنامه را سریع می‌سازد و مربی آن را بازبینی و نهایی می‌کند."),
    # Response hours are not published (brand-facts-fa.md §6.9): promise no hours.
    ("ساعت پاسخ‌گویی", "hours",
     "پیام شما ثبت شد و یکی از همکاران ما در اولین فرصت پاسخ می‌دهد."),
]

#: (channel, sender, name, phone, messages[(role, text)], state, tags)
CONVERSATIONS = [
    ("BALE", "demo-b1", "مربی نمونه ۱", "09120000001",
     [("CUSTOMER", "سلام، چغر دقیقاً چه کاری برای مربی‌ها انجام می‌دهد؟"),
      ("AI", "سلام! چغر دستیار هوش مصنوعیِ مربی‌هاست و برنامهٔ ورزشی و غذاییِ هر ورزشکار را پیش‌نویس می‌کند؛ تصمیم نهایی با مربی است.")],
     "AI", ["سؤال محصول"]),
    ("TELEGRAM", "demo-t1", "مربی نمونه ۲", "09120000002",
     [("CUSTOMER", "می‌خوام با یک نفر از تیم صحبت کنم، سؤال درباره بسته‌های توکن دارم"),
      ("AI", "گفتگو را به یکی از همکاران می‌سپارم؛ به‌زودی پاسخ می‌دهند.")],
     "ESCALATED", ["توکن"]),
    ("RUBIKA", "demo-r1", "ورزشکار نمونه", "",
     [("CUSTOMER", "برنامه غذایی هم می‌سازه؟"),
      ("HUMAN", "بله، چغر هم برنامهٔ ورزشی و هم غذایی را پیش‌نویس می‌کند و مربی نهایی‌اش می‌کند."),
      ("CUSTOMER", "ممنون، پس از همین‌جا شروع می‌کنم")],
     "HUMAN", []),
    ("SMS", "989120000003", "مربی نمونه ۳", "09120000003",
     [("CUSTOMER", "سلام، حساب من فعال نشد"),
      ("HUMAN", "سلام، لطفاً شمارهٔ ثبت‌نام را بفرستید تا بررسی کنیم.")],
     "HUMAN", ["پشتیبانی فنی"]),
    ("WEBCHAT", "demo-w1", "بازدیدکنندهٔ نمونه", "",
     [("CUSTOMER", "سلام، ثبت‌نام رایگان است؟"),
      ("AI", "ثبت‌نام کمتر از یک دقیقه طول می‌کشد و شروعش رایگان است؛ کارت اعتباری نمی‌خواهد.")],
     "AI", []),
    ("EITAA", "demo-e1", "مربی نمونه ۴", "",
     [("CUSTOMER", "نظرتون درباره هوش مصنوعی برای مربی‌ها چیه؟"),
      ("AI", "چغر کنار مربی کار می‌کند؛ پیش‌نویس می‌سازد و مربی بازبینی و نهایی می‌کند.")],
     "RESOLVED", []),
]


def seed(store, *, owner=None) -> dict:
    """Idempotent. Returns counts for the command's report."""
    from . import signals

    with transaction.atomic(), signals.suppressed():
        return _seed(store, owner)


def _seed(store, owner) -> dict:
    made = {"conversations": 0, "canned": 0, "contacts": 0}
    cfg = team.settings_for(store)
    if not cfg.widget:
        # First seed only: running it again must never overwrite what the owner changed since.
        # No working hours and no off-hours text on purpose - the brand has not published its
        # hours (brand-facts-fa.md §6.9), so the inbox is «always open» until the owner says otherwise.
        cfg.assignment_mode = InboxSettings.Assignment.ROUND_ROBIN
        cfg.bot_enabled = True
        cfg.bot_min_confidence = 0.55
        cfg.greeting_message = BRAND["welcome"]
        cfg.survey_enabled = True
        cfg.widget = dict(BRAND)
        cfg.save()

    # Channels exist but stay OFF and token-less: a draft, never a live bot.
    for kind in ("TELEGRAM", "BALE", "EITAA", "RUBIKA", "WEBCHAT", "SMS", "WHATSAPP"):
        ChannelConnection.objects.get_or_create(store=store, kind=kind, defaults={"title": kind, "enabled": False})

    segments.ensure_builtin(store)

    for title, shortcut, text in CANNED:
        _, new = CannedReply.objects.get_or_create(
            store=store, shortcut=shortcut, defaults={"title": title, "text": text, "created_by": owner},
        )
        made["canned"] += int(new)

    now = timezone.now()
    for index, (channel, sender, name, phone, lines, state, tags) in enumerate(CONVERSATIONS):
        if Customer.objects.filter(store=store, channel=channel.lower(), external_id=sender).exists():
            continue
        customer = Customer.objects.create(
            store=store, name=name, channel=channel.lower(), external_id=sender, phone=phone,
            metadata={"demo": True},
        )
        conversation = Conversation.objects.create(
            store=store, customer=customer, channel=channel, external_id=sender, state=Conversation.State.AI, tags=tags,
        )
        # The flag goes on first: from this moment no clock, no event, no webhook.
        ConversationMeta.objects.create(conversation=conversation, store=store, is_test=True)
        contact = contacts.identify(customer, phone=phone, name=name, source="demo", is_test=True)
        contact.tags = ["نمونه"] + tags
        contact.save(update_fields=["tags", "updated_at"])
        made["contacts"] += 1
        stamp = now - timedelta(minutes=30 * (len(CONVERSATIONS) - index))
        last_customer_at = stamp
        for role, text in lines:
            message = Message(conversation=conversation, role=getattr(Message.Role, role), text=text)
            message._inbox_skip = True
            message.save()
            Message.objects.filter(pk=message.pk).update(created_at=stamp)
            if role == "HUMAN":
                MessageMeta.objects.create(message=message, author=owner, kind=MessageMeta.Kind.REPLY, delivered=True)
            if role == "CUSTOMER":
                last_customer_at = stamp  # when the customer last wrote - not after the last line
            stamp += timedelta(minutes=2)
        conversation.state = state
        conversation.last_customer_at = last_customer_at
        conversation.save()
        Conversation.objects.filter(pk=conversation.pk).update(last_customer_at=last_customer_at)
        if state == "ESCALATED":
            meta = ConversationMeta.objects.get(conversation=conversation)
            meta.handoff_reason = "مشتری آدم خواست («صحبت با»)"
            meta.unread_count = 1
            meta.save(update_fields=["handoff_reason", "unread_count"])
        made["conversations"] += 1

    if not Broadcast.objects.filter(store=store, name__startswith="[نمونه]").exists():
        Broadcast.objects.create(
            store=store, name="[نمونه] معرفی چغر به مربی‌ها", is_test=True, created_by=owner, channels=[],
            text="سلام {name}! چغر دستیار هوش مصنوعیِ مربی‌هاست و برنامهٔ ورزشی و غذاییِ ورزشکاران را پیش‌نویس می‌کند؛ ثبت‌نامش رایگان شروع می‌شود.",
        )
    first = Conversation.objects.filter(store=store, external_id="demo-r1").first()
    if first is not None and not FollowUp.objects.filter(store=store, conversation=first).exists():
        FollowUp.objects.create(
            store=store, conversation=first, text="[نمونه] پیگیریِ شروعِ کار با چغر", due_at=now + timedelta(days=1),
            created_by=owner, is_test=True,
        )
    return made


def is_demo(contact: Contact) -> bool:
    return contact.source == "demo"

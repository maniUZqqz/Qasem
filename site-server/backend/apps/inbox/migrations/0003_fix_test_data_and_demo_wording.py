"""Data fixes for what the first release left behind (all idempotent, all conservative).

1. **Test contacts.** The customer panel of a test chat used to create a *real-looking*
   CRM contact («مشتری آزمایشی», channel WEB-TEST). Such a contact shows up in segments
   and in the «all contacts» audience. Every contact whose people are all test customers is
   marked `is_test` (and so hidden until «show test» is switched on).
2. **Demo wording that was an invention.** The Chagher draft set working hours, an off-hours
   text and a widget subtitle that promise a schedule the brand never published, and two
   canned lines said «جایگزین مربی» (the brand's never-say list). A row is changed ONLY while it
   still holds exactly the text the seed wrote - an owner's own edit is never touched.
3. **Demo clocks.** The seed stamped `last_customer_at` *after* the team's answer, so an
   answered demo thread looked as if the customer was still waiting.
4. **Stale channel errors.** A channel whose last health check / poll succeeded after its
   last error no longer shows that error.
"""
from django.db import migrations

OLD_SUBTITLE = "معمولاً در چند دقیقه پاسخ می‌دهیم"
NEW_SUBTITLE = "پیامتان را بنویسید"
OLD_HOURS = {"days": [5, 6, 0, 1, 2], "start": "09:00", "end": "18:00"}
OLD_OFFHOURS = "الان خارج از ساعت کاری هستیم؛ پیامتان ثبت شد و صبح که برگشتیم جواب می‌دهیم."

CANNED = {
    "coach": (
        ("جایگزین مربی؟", "نه؛ چغر جایگزین مربی نیست. فقط پیش‌نویس برنامه را سریع می‌سازد و مربی آن را بازبینی و نهایی می‌کند."),
        ("آیا مربی لازم است؟", "بله؛ چغر کنار مربی کار می‌کند: پیش‌نویس برنامه را سریع می‌سازد و مربی آن را بازبینی و نهایی می‌کند."),
    ),
    "hours": (
        ("ساعت پاسخ‌گویی", "همکاران ما در ساعت کاری پاسخ می‌دهند؛ پیام شما ثبت شد و در اولین فرصت جواب می‌گیرید."),
        ("ساعت پاسخ‌گویی", "پیام شما ثبت شد و یکی از همکاران ما در اولین فرصت پاسخ می‌دهد."),
    ),
}
LINES = {
    "نظرتون درباره جایگزین شدن مربی با هوش مصنوعی چیه؟": "نظرتون درباره هوش مصنوعی برای مربی‌ها چیه؟",
    "چغر جایگزین مربی نیست؛ پیش‌نویس می‌سازد و مربی بازبینی می‌کند.":
        "چغر کنار مربی کار می‌کند؛ پیش‌نویس می‌سازد و مربی بازبینی و نهایی می‌کند.",
}


def fix(apps, schema_editor):
    Contact = apps.get_model("inbox", "Contact")
    ContactLink = apps.get_model("inbox", "ContactLink")
    ConversationMeta = apps.get_model("inbox", "ConversationMeta")
    CannedReply = apps.get_model("inbox", "CannedReply")
    InboxSettings = apps.get_model("inbox", "InboxSettings")
    ChannelConnection = apps.get_model("inbox", "ChannelConnection")
    Customer = apps.get_model("customers", "Customer")
    Conversation = apps.get_model("customers", "Conversation")
    Message = apps.get_model("customers", "Message")

    # 1. contacts made of test customers only
    test_customers = set(Customer.objects.filter(channel="web-test").values_list("pk", flat=True))
    test_customers |= set(
        Conversation.objects.filter(pk__in=ConversationMeta.objects.filter(is_test=True).values("conversation_id"))
        .values_list("customer_id", flat=True)
    )
    for contact in Contact.objects.filter(is_test=False):
        owners = list(ContactLink.objects.filter(contact=contact).values_list("customer_id", flat=True))
        if owners and all(pk in test_customers for pk in owners):
            contact.is_test = True
            contact.save(update_fields=["is_test"])

    # 2. wording nobody published
    for shortcut, (old, new) in CANNED.items():
        for row in CannedReply.objects.filter(shortcut=shortcut):
            if (row.title, row.text) == old:
                row.title, row.text = new
                row.save(update_fields=["title", "text"])
    for cfg in InboxSettings.objects.all():
        changed = False
        widget = dict(cfg.widget or {})
        if widget.get("subtitle") == OLD_SUBTITLE:
            widget["subtitle"] = NEW_SUBTITLE
            cfg.widget = widget
            changed = True
        if cfg.working_hours == OLD_HOURS and cfg.offhours_message == OLD_OFFHOURS:
            cfg.working_hours = {}
            cfg.offhours_message = ""
            if cfg.bot_offhours == "MESSAGE":
                cfg.bot_offhours = "BOT"
            changed = True
        if changed:
            cfg.save()
    for old_text, new_text in LINES.items():
        Message.objects.filter(text=old_text, conversation__customer__metadata__demo=True).update(text=new_text)

    # 3. demo threads: «the customer last wrote at ...», not «after the last line»
    for conversation in Conversation.objects.filter(customer__metadata__demo=True):
        last = (
            Message.objects.filter(conversation=conversation, role="CUSTOMER").order_by("-created_at", "-id").first()
        )
        if last is not None and conversation.last_customer_at != last.created_at:
            Conversation.objects.filter(pk=conversation.pk).update(last_customer_at=last.created_at)

    # 4. an error that a later successful check has already answered
    for connection in ChannelConnection.objects.filter(health_ok=True).exclude(last_error=""):
        if connection.last_error_at is None or (
            connection.health_checked_at is not None and connection.last_error_at <= connection.health_checked_at
        ):
            connection.last_error = ""
            connection.last_error_at = None
            connection.save(update_fields=["last_error", "last_error_at"])


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0002_inboxsettings_handoff_message'),
        ('customers', '0013_backfill_ai_failure'),
    ]

    operations = [
        migrations.RunPython(fix, migrations.RunPython.noop),
    ]

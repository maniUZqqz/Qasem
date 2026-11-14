from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def flag_unanswered(apps, schema_editor):
    """Mark the threads whose last message is still the customer's.

    Before `ai_failed_at` existed a failed agent turn left no trace on the
    conversation: state AI, the customer's message last, nobody told. Those
    that are recent enough to matter (14 days) are flagged now, so the inbox
    counts them instead of saying «۰ نفر منتظر». Older ones stay as they were —
    flagging a month-old test chat would only add noise.
    """
    Conversation = apps.get_model("customers", "Conversation")
    Message = apps.get_model("customers", "Message")
    since = timezone.now() - timedelta(days=14)
    rows = Conversation.objects.filter(
        state="AI", ai_failed_at__isnull=True, last_customer_at__isnull=False,
        last_customer_at__gte=since,
    )
    for conversation in rows:
        last = (
            Message.objects.filter(conversation=conversation)
            .order_by("-created_at", "-id").first()
        )
        if last is None or last.role != "CUSTOMER":
            continue
        grounding = last.grounding or {}
        if grounding.get("receipt_filed") or (grounding.get("image") and last.text == "[تصویر]"):
            continue   # a bare photo: a payment slip is filed and acknowledged, no reply is written
        Conversation.objects.filter(pk=conversation.pk).update(
            ai_failed_at=conversation.last_customer_at,
            ai_failed_reason="پاسخی برای این پیام ثبت نشد (پیش از ثبتِ خطای AI).",
        )


def repair_notification_links(apps, schema_editor):
    """Point the notifications already in the bell at pages that exist.

    New ones are built by `apps.customers.links`; the rows written before that
    still carry `/stores/<id>/settings` (a blank page), the bare section
    overview `/sales`, or `/chat` with the conversation id only in `context`.
    """
    Notification = apps.get_model("customers", "Notification")
    Conversation = apps.get_model("customers", "Conversation")
    tab = {"ORDER": "orders", "TICKET": "tickets", "RECEIPT": "receipts"}
    for note in Notification.objects.all():
        link, sid = note.link or "", note.store_id
        new = link
        if link == f"/stores/{sid}/settings":
            new = f"/stores/{sid}/data"
        elif link in (f"/stores/{sid}/sales", f"/stores/{sid}/sales/") and note.type in tab:
            new = f"/stores/{sid}/sales/{tab[note.type]}"
        elif link in (f"/stores/{sid}/chat", f"/stores/{sid}/inbox") and note.type in ("AI_ERROR", "ESCALATION"):
            cid = (note.context or {}).get("conversation_id")
            conversation = (
                Conversation.objects.filter(pk=cid, store_id=sid).select_related("customer").first()
                if cid else None
            )
            if conversation is not None:
                page = "chat" if conversation.customer.channel == "web-test" else "inbox"
                new = f"/stores/{sid}/{page}?c={conversation.pk}"
        if new != link:
            Notification.objects.filter(pk=note.pk).update(link=new)


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0012_conversation_ai_failure"),
    ]

    operations = [
        migrations.RunPython(flag_unanswered, migrations.RunPython.noop),
        migrations.RunPython(repair_notification_links, migrations.RunPython.noop),
    ]

"""JSON shapes for the inbox API - plain dicts, built in one place.

Hand-built rather than DRF `ModelSerializer`: every shape here is a join across
two or three tables (a conversation + its meta + its contact + its last visible
message), and a serializer per model would mean the list view runs a query per
field. These functions take what the view already loaded.
"""
from __future__ import annotations

from apps.customers import ai_retry
from apps.customers.models import Conversation, Message

from . import dispatch, sla
from .owed import OWED
from .models import (
    AgentProfile, Broadcast, CannedReply, ChannelConnection, Contact, FollowUp, InternalNote,
    Segment, WebhookEndpoint,
)


def _meta(conversation: Conversation):
    return getattr(conversation, "inbox_meta", None)


def _waiting_minutes(conversation: Conversation, meta, owed: bool) -> int | None:
    """How long the customer has been waiting for *us* - nothing unless they are owed an answer.

    `owed` is `owed.OWED` (the one definition every tab and tile uses): a person has the
    thread and has not answered since the customer wrote, or the bot failed to answer.
    The SLA clock (`meta.waiting_since`) is the truth while it runs; without it (a thread
    from before the inbox, a demo thread) the customer waits since they last wrote.
    """
    from django.utils import timezone

    if not owed:
        return None
    since = meta.waiting_since if meta is not None and meta.waiting_since is not None else None
    since = since or conversation.last_customer_at or (conversation.ai_failed_at if conversation.ai_failed else None)
    if since is None:
        return None
    return max(0, int((timezone.now() - since).total_seconds() // 60))


def user_json(user) -> dict | None:
    if user is None:
        return None
    return {"username": user.username, "name": user.get_full_name() or user.username}


_LOOK = object()  # «ask the database yourself» - the single-row callers (thread, assign, close)


def last_visible_messages(conversation_ids) -> dict[int, Message | None]:
    """`ai_retry.last_visible_message` for many conversations in ONE query.

    The list used to ask once per row (181 queries for 53 conversations, every six
    seconds per open tab). A window function numbers each conversation's newest
    messages; the first one that is not our own acknowledgement wins - the same
    rule, `ai_retry`'s, applied to six messages per thread.
    """
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber

    ids = list(conversation_ids)
    out: dict[int, Message | None] = {i: None for i in ids}
    if not ids:
        return out
    newest = (
        Message.objects.filter(conversation_id__in=ids)
        .annotate(_n=Window(
            expression=RowNumber(), partition_by=[F("conversation_id")],
            order_by=[F("created_at").desc(), F("id").desc()],
        ))
        .filter(_n__lte=6)
        .order_by("conversation_id", "-created_at", "-id")
    )
    for message in newest:
        if out.get(message.conversation_id) is None and not ai_retry._is_ack(message):  # noqa: SLF001
            out[message.conversation_id] = message
    return out


def conversation_row(
    conversation: Conversation, *, me=None, last=_LOOK, cfg=None, now=None, owed=_LOOK,
) -> dict:
    meta = _meta(conversation)
    customer = conversation.customer
    if last is _LOOK:
        last = ai_retry.last_visible_message(conversation)
    if owed is _LOOK:
        owed = Conversation.objects.filter(pk=conversation.pk).filter(OWED).exists()
    link = getattr(customer, "inbox_link", None)
    contact = link.contact if link is not None else None
    waiting = _waiting_minutes(conversation, meta, bool(owed))
    return {
        "id": conversation.id,
        "channel": conversation.channel,
        "channel_title": dispatch.TITLES.get(conversation.channel, conversation.channel),
        "state": conversation.state,
        "customer": {
            "id": customer.id,
            "name": customer.name or (contact.name if contact else "") or "مشتری",
            "phone": customer.phone or (contact.phone if contact else ""),
        },
        "contact_id": contact.id if contact else None,
        "assigned_to": user_json(conversation.assigned_to),
        "mine": bool(me is not None and conversation.assigned_to_id == getattr(me, "pk", None)),
        "tags": conversation.tags or [],
        "unread": meta.unread_count if meta else 0,
        "waiting_minutes": waiting,
        "sla": sla.status_of(meta, now, cfg=cfg),
        "sla_due_at": meta.sla_due_at if meta else None,
        "is_test": bool(conversation.is_test or (meta and meta.is_test)),
        "ai_failed": conversation.ai_failed,
        "priority": meta.priority if meta else 0,
        "handoff_reason": meta.handoff_reason if meta else "",
        "bot_confidence": meta.bot_confidence if meta else None,
        "last_message": (
            {"role": last.role, "text": (last.text or "")[:140], "at": last.created_at} if last else None
        ),
        "last_customer_at": conversation.last_customer_at,
        "updated_at": conversation.updated_at,
    }


def message_json(message: Message) -> dict:
    meta = getattr(message, "inbox_meta", None)
    return {
        "id": message.id,
        "type": "message",
        "role": message.role,
        "text": message.text,
        "at": message.created_at,
        "kind": meta.kind if meta else "",
        "author": meta.author.username if meta and meta.author_id else "",
        "delivered": meta.delivered if meta else None,
        "delivery_error": meta.delivery_error if meta else "",
        "image": bool((message.grounding or {}).get("image")),
        #: a bot answer that was NOT sent because the bot was unsure - shown to
        #: the team as a draft they may use or throw away.
        "withheld": bool((message.grounding or {}).get("withheld")),
    }


def note_json(note: InternalNote) -> dict:
    return {
        "id": note.id, "type": "note", "role": "NOTE", "text": note.text, "at": note.created_at,
        "author": note.author.username if note.author_id else "", "mentions": note.mentions or [],
    }


def contact_json(contact: Contact, *, detail: bool = False) -> dict:
    data = {
        "id": contact.id, "name": contact.name, "phone": contact.phone,
        "usernames": contact.usernames or [], "tags": contact.tags or [],
        "orders_count": contact.orders_count, "total_spent": float(contact.total_spent or 0),
        "last_purchase_at": contact.last_purchase_at, "last_activity_at": contact.last_activity_at,
        "first_seen_at": contact.first_seen_at, "opt_out": contact.opt_out or {},
        "source": contact.source, "is_test": contact.is_test,
    }
    if detail:
        data.update({"email": contact.email, "notes": contact.notes, "extra": contact.extra or {}})
    return data


#: Config keys that are credentials even though the guide does not mark them `secret`
#: (WhatsApp's verify token is the shared secret of Meta's webhook handshake).
_SECRET_CONFIG = {"app_secret", "verify_token"}


def channel_json(connection: ChannelConnection, guide: dict, hook_url: str, ready: bool, *, reveal: bool = True) -> dict:
    """The connect-page card for one channel.

    `reveal` is «this reader may change settings»: only then do the webhook URL (it carries
    the channel's secret - whoever has it can post fake customer messages), the saved
    config and the token's masked tail go out. A support agent or a viewer sees the channel's
    state, never its keys.
    """
    config = {k: v for k, v in (connection.config or {}).items() if k != "app_secret"}
    if not reveal:
        public_keys = {f["key"] for f in guide.get("fields", []) if not f.get("secret") and f["key"] not in _SECRET_CONFIG}
        config = {k: v for k, v in config.items() if k in public_keys}
    return {
        "kind": connection.kind,
        "title": guide.get("title", connection.get_kind_display()),
        "summary": guide.get("summary", ""),
        "fields": guide.get("fields", []),
        "steps": guide.get("steps", []),
        "limits": guide.get("limits", ""),
        "docs": guide.get("docs", ""),
        "needs_owner_account": guide.get("needs_owner_account", False),
        "mode_hint": guide.get("mode", ""),
        "enabled": connection.enabled,
        "ready": ready,
        "mode": connection.mode,
        "masked_token": connection.masked_token if reveal else "",
        "has_token": bool(connection.token),
        "config": config,
        "has_app_secret": bool((connection.config or {}).get("app_secret")),
        "has_verify_token": bool((connection.config or {}).get("verify_token")),
        "hook_url": hook_url if reveal else "",
        "can_see_keys": reveal,
        "health": {
            "ok": connection.health_ok, "detail": connection.health_detail,
            "checked_at": connection.health_checked_at, "account": connection.account_label,
        },
        "last_inbound_at": connection.last_inbound_at,
        "last_outbound_at": connection.last_outbound_at,
        "last_poll_at": connection.last_poll_at,
        "last_error": connection.last_error,
        "last_error_at": connection.last_error_at,
        "inbound_count": connection.inbound_count,
        "outbound_count": connection.outbound_count,
    }


def canned_json(row: CannedReply) -> dict:
    return {"id": row.id, "title": row.title, "shortcut": row.shortcut, "text": row.text,
            "channels": row.channels or [], "use_count": row.use_count}


def segment_json(row: Segment, count: int | None = None) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description, "rules": row.rules,
            "builtin": bool(row.builtin_key), "builtin_key": row.builtin_key, "count": count}


def broadcast_json(row: Broadcast, user=None) -> dict:
    data = {
        "id": row.id, "name": row.name, "text": row.text, "channels": row.channels or [],
        "segment_id": row.segment_id, "segment_name": row.segment.name if row.segment_id else "همهٔ مخاطبان",
        "status": row.status, "status_title": row.get_status_display(), "dedupe": row.dedupe,
        "is_test": row.is_test, "created_by": row.created_by.username if row.created_by_id else "",
        "approved_by": row.approved_by.username if row.approved_by_id else "",
        "approved_at": row.approved_at, "review_note": row.review_note,
        "scheduled_at": row.scheduled_at, "started_at": row.started_at, "finished_at": row.finished_at,
        "stats": row.stats or {}, "created_at": row.created_at,
    }
    if user is not None:
        # The same rule `approve` enforces, so the button is only shown to someone it will work for
        # (an admin who is not the owner cannot approve what they wrote themselves).
        from . import broadcast as broadcast_rules

        ok, why = broadcast_rules.can_approve(user, row)
        data["can_approve"] = ok
        data["cannot_approve_reason"] = "" if ok else why
    return data


def followup_json(row: FollowUp) -> dict:
    return {
        "id": row.id, "kind": row.kind, "kind_title": row.get_kind_display(), "target": row.target,
        "text": row.text, "due_at": row.due_at, "status": row.status, "status_title": row.get_status_display(),
        "conversation_id": row.conversation_id, "order_id": row.order_id,
        "assigned_to": row.assigned_to.username if row.assigned_to_id else "",
        "error": row.error, "is_test": row.is_test, "sent_at": row.sent_at,
        "customer": row.conversation.customer.name if row.conversation_id else "",
    }


def webhook_json(row: WebhookEndpoint) -> dict:
    return {
        "id": row.id, "url": row.url, "events": row.events or [], "active": row.active,
        "failure_count": row.failure_count, "last_status": row.last_status,
        "last_delivery_at": row.last_delivery_at,
    }


def agent_json(profile: AgentProfile) -> dict:
    return {
        "username": profile.user.username, "name": profile.name, "status": profile.effective_status,
        "status_note": profile.status_note, "accepts_chats": profile.accepts_chats,
        "channels": profile.channels or [], "skills": profile.skills or [], "max_open": profile.max_open,
    }

"""The team: who can take a conversation, who gets the next one, how fast they are.

Three questions live here and nowhere else, because three views and two Celery
tasks all ask them and an answer that differs between the inbox and the report
is how a team stops trusting the numbers:

* **Who is eligible?**  A member who may answer customers (`access.CONVERSATIONS`
  write), has not turned "accepts chats" off, covers this channel, is not over
  their open-conversation limit, and - when the store says so - is actually
  online right now.
* **Who gets it?**  Round-robin is *least recently assigned*, not a counter:
  a counter needs a lock and drifts when a member joins; a timestamp needs
  neither and a new person simply goes first.
* **How are they doing?**  First response and average response time are measured
  from the moment a *person* started owing the customer an answer
  (`ConversationMeta.waiting_since`), to the member's reply - not from the
  customer's first ever message, which would blame a human for the AI's hours.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Avg, OuterRef, Subquery
from django.utils import timezone

from apps.customers.models import Conversation, Message
from apps.stores import access
from apps.stores.models import Membership

from . import norm
from .models import AgentProfile, ConversationMeta, InboxSettings, MessageMeta

OPEN_STATES = (Conversation.State.HUMAN, Conversation.State.ESCALATED)


def settings_for(store) -> InboxSettings:
    row, _ = InboxSettings.objects.get_or_create(store=store)
    return row


def members(store) -> list[User]:
    """Owner + active members who may answer customers."""
    users = [store.owner]
    for membership in Membership.objects.filter(store=store, is_active=True).select_related("user"):
        if membership.user_id != store.owner_id:
            users.append(membership.user)
    return [u for u in users if access.can(u, store, access.CONVERSATIONS, write=True)]


def profile_for(store, user) -> AgentProfile:
    row, _ = AgentProfile.objects.get_or_create(store=store, user=user)
    return row


def open_load(store, user) -> int:
    return Conversation.objects.filter(store=store, assigned_to=user, state__in=OPEN_STATES).count()


def eligible(store, conversation: Conversation | None = None, *, only_online: bool | None = None):
    """Profiles that may be handed `conversation` right now."""
    cfg = settings_for(store)
    if only_online is None:
        only_online = cfg.assign_only_online
    out = []
    for user in members(store):
        profile = profile_for(store, user)
        if not profile.accepts_chats:
            continue
        if only_online and profile.effective_status != AgentProfile.Status.ONLINE:
            continue
        if conversation is not None and profile.channels and conversation.channel not in profile.channels:
            continue
        if open_load(store, user) >= profile.max_open:
            continue
        out.append(profile)
    return out


def _least_recent(profiles: list[AgentProfile]) -> AgentProfile | None:
    if not profiles:
        return None
    epoch = timezone.now() - timedelta(days=36500)
    return min(profiles, key=lambda p: (p.last_assigned_at or epoch, p.pk))


#: A skill is a word the store chose («پرداخت»، «ثبت‌نام»), so it may wear an ending when the
#: customer writes it: «پرداختم»، «ثبت‌نامش».
SKILL_SUFFIXES = norm.WORD_SUFFIXES + ("ی", "م", "ت", "ش", "مون", "تون", "شون")


def _customer_words(conversation: Conversation, limit: int = 5) -> str:
    """The customer's last few messages, plus why the bot handed over - what a skill is matched against."""
    texts = list(
        conversation.messages.filter(role=Message.Role.CUSTOMER).order_by("-created_at", "-id")
        .values_list("text", flat=True)[:limit]
    )
    meta = getattr(conversation, "inbox_meta", None)
    if meta is not None and meta.handoff_reason:
        texts.append(meta.handoff_reason)
    return "\n".join(texts)


def _skill_pool(profiles: list[AgentProfile], conversation: Conversation) -> list[AgentProfile]:
    """Members whose skills match this conversation: a tag on it or on its contact, or a
    skill word the customer actually wrote («مشکل پرداخت دارم» -> the «پرداخت» person)."""
    wanted = {str(t).lower() for t in (conversation.tags or [])}
    link = getattr(conversation.customer, "inbox_link", None)
    if link is not None:
        wanted |= {str(t).lower() for t in (link.contact.tags or [])}
    said = _customer_words(conversation)
    meta = getattr(conversation, "inbox_meta", None)
    if meta is not None and meta.handoff_reason:
        wanted.add(meta.handoff_reason.lower())
    matching = []
    for profile in profiles:
        for skill in profile.skills or []:
            skill = str(skill).strip()
            if skill and (skill.lower() in wanted or norm.has_phrase(said, skill, suffixes=SKILL_SUFFIXES)):
                matching.append(profile)
                break
    return matching


def pick(store, conversation: Conversation) -> AgentProfile | None:
    """Choose a member for this conversation by the store's rule, or None."""
    cfg = settings_for(store)
    if cfg.assignment_mode == InboxSettings.Assignment.MANUAL:
        return None
    pool = eligible(store, conversation)
    if cfg.assignment_mode == InboxSettings.Assignment.BY_CHANNEL:
        # Someone who named this channel beats someone who covers everything.
        dedicated = [p for p in pool if p.channels and conversation.channel in p.channels]
        pool = dedicated or pool
    elif cfg.assignment_mode == InboxSettings.Assignment.BY_SKILL:
        pool = _skill_pool(pool, conversation) or pool
    return _least_recent(pool)


def assign(conversation: Conversation, *, by=None) -> User | None:
    """Apply the store's rule to one conversation. Never overrides a person."""
    if conversation.assigned_to_id:
        return conversation.assigned_to
    profile = pick(conversation.store, conversation)
    if profile is None:
        return None
    conversation.assigned_to = profile.user
    conversation.save(update_fields=["assigned_to", "updated_at"])
    profile.last_assigned_at = timezone.now()
    profile.save(update_fields=["last_assigned_at", "updated_at"])
    return profile.user


def transfer(conversation: Conversation, to_user, *, by, note: str = "") -> None:
    """Hand a conversation to a colleague, with a note they will see."""
    from .models import InternalNote

    conversation.assigned_to = to_user
    conversation.save(update_fields=["assigned_to", "updated_at"])
    if to_user is not None:
        profile = profile_for(conversation.store, to_user)
        profile.last_assigned_at = timezone.now()
        profile.save(update_fields=["last_assigned_at", "updated_at"])
    who = to_user.username if to_user else "هیچ‌کس"
    InternalNote.objects.create(
        conversation=conversation, author=by,
        text=f"انتقال به «{who}»" + (f": {note}" if note else ""),
        mentions=[to_user.username] if to_user else [],
    )


def set_status(store, user, status: str, note: str = "") -> AgentProfile:
    profile = profile_for(store, user)
    profile.status = status
    profile.status_note = note[:120]
    profile.last_seen_at = timezone.now()
    profile.save(update_fields=["status", "status_note", "last_seen_at", "updated_at"])
    return profile


def heartbeat(store, user) -> AgentProfile:
    """The panel says "this person is looking at the inbox"."""
    profile = profile_for(store, user)
    profile.last_seen_at = timezone.now()
    fields = ["last_seen_at", "updated_at"]
    # Opening the inbox after a night offline should not leave them "OFFLINE"
    # while they are clearly there - but a deliberate BUSY stays BUSY.
    if profile.status == AgentProfile.Status.OFFLINE:
        profile.status = AgentProfile.Status.ONLINE
        fields.append("status")
    profile.save(update_fields=fields)
    return profile


def performance(store, *, days: int = 30) -> list[dict]:
    """First-response and average response time per member (test threads out).

    Credit goes to **whoever answered**, not to whoever the thread was assigned to: a
    colleague who picks up a waiting thread owns that response time (and its
    `replies` count). An SLA breach is different - it is the *assignee's* miss (they
    had the thread and nobody answered in time), so it stays with the assignee.
    """
    since = timezone.now() - timedelta(days=days)
    rows = []
    role_titles = dict(Membership.Role.choices)
    # Who wrote the first reply of each conversation (one query, not one per member).
    first_author = Subquery(
        MessageMeta.objects.filter(
            message__conversation=OuterRef("conversation"), kind=MessageMeta.Kind.REPLY, author__isnull=False,
        ).order_by("message__created_at", "id").values("author_id")[:1]
    )
    first_by_user: dict[int, list[int]] = {}
    for author_id, seconds in (
        ConversationMeta.objects.filter(
            store=store, is_test=False, first_human_reply_at__gte=since, first_response_seconds__isnull=False,
        ).annotate(_first_author=first_author).values_list("_first_author", "first_response_seconds")
    ):
        if author_id is not None:
            first_by_user.setdefault(author_id, []).append(seconds)
    for user in members(store):
        profile = profile_for(store, user)
        role = access.role_of(user, store)
        replies = MessageMeta.objects.filter(
            author=user, kind=MessageMeta.Kind.REPLY,
            message__conversation__store=store, message__created_at__gte=since,
        ).exclude(message__conversation__inbox_meta__is_test=True)
        agg = replies.exclude(response_seconds__isnull=True).aggregate(avg=Avg("response_seconds"))
        mine = first_by_user.get(user.pk, [])
        breaches = ConversationMeta.objects.filter(
            store=store, conversation__assigned_to=user, is_test=False,
            sla_breached_at__gte=since,
        ).count()
        rows.append({
            "username": user.username,
            "name": profile.name,
            "role": role,
            #: «مالک / مدیر / پشتیبانی» - the panel shows this, never the code
            "role_title": role_titles.get(role, role or ""),
            "status": profile.effective_status,
            "status_note": profile.status_note,
            "open": open_load(store, user),
            "max_open": profile.max_open,
            "replies": replies.count(),
            "avg_response_seconds": int(agg["avg"]) if agg["avg"] is not None else None,
            "avg_first_response_seconds": int(sum(mine) / len(mine)) if mine else None,
            "conversations_answered": len(mine),
            "sla_breaches": breaches,
            "accepts_chats": profile.accepts_chats,
            "channels": profile.channels,
            "skills": profile.skills,
            "last_seen_at": profile.last_seen_at,
        })
    return rows

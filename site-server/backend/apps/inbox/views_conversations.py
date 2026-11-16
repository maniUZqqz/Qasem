"""The three-pane inbox API: list, thread, reply, note, transfer, close, follow-up.

Everything is scoped by `access.get_store(..., CONVERSATIONS)` first - the only
tenant-isolation check - and every conversation is looked up *inside* that
store, never by bare id.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.utils import with_tag
from apps.customers import ai_retry
from apps.customers.models import Conversation, Message
from apps.stores import access

from . import contacts as contacts_mod
from . import followups, replies, serializers as ser, sla, team
from .models import CannedReply, ConversationMeta, InternalNote, MessageMeta

OPEN_STATES = [Conversation.State.AI, Conversation.State.HUMAN, Conversation.State.ESCALATED]
OWED_BY_PERSON = Q(state=Conversation.State.HUMAN) | Q(state=Conversation.State.ESCALATED)
OWED_BY_AI = Q(state=Conversation.State.AI, ai_failed_at__isnull=False)


def fail(code: str, message: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=http)


def store_of(request, store_id, *, write=False):
    return access.get_store(request.user, store_id, access.CONVERSATIONS, write=write)


def conversation_of(store, pk) -> Conversation:
    return get_object_or_404(
        Conversation.objects.select_related("customer", "assigned_to", "store"), pk=pk, store=store,
    )


class ListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        qp = request.query_params
        base = Conversation.objects.filter(store=store)
        show_tests = qp.get("test") in ("1", "true", "only")
        if qp.get("test") == "only":
            base = base.filter(Q(inbox_meta__is_test=True) | Q(customer__channel="web-test"))
        elif not show_tests:
            base = base.exclude(Q(inbox_meta__is_test=True) | Q(customer__channel="web-test"))

        rows = base.select_related("customer", "assigned_to", "store", "inbox_meta")

        channels = [c.upper() for c in qp.get("channel", "").split(",") if c]
        if channels:
            rows = rows.filter(channel__in=channels)

        state = qp.get("state", "")
        if state == "open":
            rows = rows.filter(state__in=OPEN_STATES)
        elif state == "waiting":
            rows = rows.filter(OWED_BY_PERSON | OWED_BY_AI)
        elif state in ("AI", "HUMAN", "ESCALATED", "RESOLVED"):
            rows = rows.filter(state=state)

        assigned = qp.get("assigned", "")
        if assigned == "me":
            rows = rows.filter(assigned_to=request.user)
        elif assigned == "nobody":
            rows = rows.filter(assigned_to__isnull=True)
        elif assigned:
            rows = rows.filter(assigned_to__username=assigned)

        if qp.get("unread") in ("1", "true"):
            rows = rows.filter(inbox_meta__unread_count__gt=0)
        sla_filter = qp.get("sla")
        if sla_filter == "breached":
            rows = rows.filter(inbox_meta__sla_breached_at__isnull=False, inbox_meta__waiting_since__isnull=False)
        elif sla_filter == "warning":
            rows = rows.filter(
                inbox_meta__sla_warned_at__isnull=False, inbox_meta__sla_breached_at__isnull=True,
                inbox_meta__waiting_since__isnull=False,
            )
        if qp.get("tag"):
            rows = with_tag(rows, qp["tag"])
        term = (qp.get("q") or "").strip()
        if term:
            rows = rows.filter(
                Q(customer__name__icontains=term) | Q(customer__phone__icontains=term)
                | Q(customer__inbox_link__contact__phone__icontains=term)
                | Q(customer__inbox_link__contact__name__icontains=term)
                | Q(messages__text__icontains=term)
            ).distinct()

        owed = OWED_BY_PERSON | OWED_BY_AI
        limit = min(int(qp.get("limit", 80) or 80), 200)
        # «Longest waiting first» for everyone owed an answer - a person's clock if it is
        # running, otherwise when the customer last wrote (an AI failure has no clock).
        waiting = list(
            rows.filter(owed)
            .annotate(_since=Coalesce("inbox_meta__waiting_since", "last_customer_at", "updated_at"))
            .order_by("_since", "id")[:limit]
        )
        rest = list(rows.exclude(owed).order_by("-updated_at")[: max(0, limit - len(waiting))])
        ordered = waiting + rest

        everything = base
        now = timezone.now()
        counts = {
            "waiting": everything.filter(owed).count(),
            "unread": everything.filter(inbox_meta__unread_count__gt=0).count(),
            "unassigned": everything.filter(OWED_BY_PERSON, assigned_to__isnull=True).count(),
            "mine": everything.filter(assigned_to=request.user, state__in=OPEN_STATES).count(),
            "breached": everything.filter(
                inbox_meta__sla_breached_at__isnull=False, inbox_meta__waiting_since__isnull=False,
            ).count(),
            "tests": Conversation.objects.filter(store=store).filter(
                Q(inbox_meta__is_test=True) | Q(customer__channel="web-test")).count(),
        }
        by_channel: dict[str, int] = {}
        for channel in everything.filter(state__in=OPEN_STATES).values_list("channel", flat=True):
            by_channel[channel] = by_channel.get(channel, 0) + 1
        members = [
            {"username": u.username, "name": team.profile_for(store, u).name,
             "status": team.profile_for(store, u).effective_status}
            for u in team.members(store)
        ]
        return Response({
            "conversations": [ser.conversation_row(c, me=request.user) for c in ordered],
            "counts": counts,
            "by_channel": by_channel,
            "now": now,
            "me": {
                "username": request.user.username,
                "can_write": access.can(request.user, store, access.CONVERSATIONS, write=True),
                "can_settings": access.can(request.user, store, access.SETTINGS, write=True),
                "is_staff": bool(request.user.is_staff),
            },
            "members": members,
        })


class ThreadView(APIView):
    """One conversation: messages + internal notes, oldest first. Reading marks it read."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = store_of(request, store_id)
        conversation = conversation_of(store, pk)
        messages = list(
            conversation.messages.select_related("inbox_meta", "inbox_meta__author").order_by("-created_at", "-id")[:200]
        )
        notes = list(conversation.inbox_notes.select_related("author").order_by("-created_at")[:100])
        thread = [ser.message_json(m) for m in messages] + [ser.note_json(n) for n in notes]
        thread.sort(key=lambda item: (item["at"], item["id"]))
        if request.query_params.get("read", "1") != "0" and access.can(request.user, store, access.CONVERSATIONS, write=True):
            replies.mark_read(conversation)
        meta = getattr(conversation, "inbox_meta", None)
        return Response({
            "conversation": ser.conversation_row(conversation, me=request.user),
            "thread": thread,
            "followups": [
                ser.followup_json(f) for f in conversation.followups.filter(status="PENDING").select_related("assigned_to", "conversation__customer")
            ],
            "meta": {
                "first_response_seconds": meta.first_response_seconds if meta else None,
                "reopened_count": meta.reopened_count if meta else 0,
                "survey_sent_at": meta.survey_sent_at if meta else None,
            },
        })


class ReplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        conversation = conversation_of(store, pk)
        text = str(request.data.get("text", "")).strip()
        if not text:
            return fail("empty", "متن پیام خالی است.")
        if len(text) > 4000:
            return fail("too_long", "پیام بیش از ۴۰۰۰ نویسه است.")
        canned = None
        if request.data.get("canned_id"):
            canned = CannedReply.objects.filter(pk=request.data["canned_id"], store=store).first()
        result = replies.reply(conversation, request.user, text, canned=canned)
        return Response({
            "message": ser.message_json(result["message"]),
            "delivered": bool(result["outcome"].get("sent")),
            "reason": result["outcome"].get("reason", ""),
            "response_seconds": result["response_seconds"],
        })


class NoteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        conversation = conversation_of(store, pk)
        text = str(request.data.get("text", "")).strip()
        if not text:
            return fail("empty", "متن یادداشت خالی است.")
        note = replies.add_note(conversation, request.user, text[:4000])
        return Response(ser.note_json(note), status=status.HTTP_201_CREATED)


class AssignView(APIView):
    """Take it, hand it over (transfer, with a note), or put it back in the queue."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        conversation = conversation_of(store, pk)
        username = request.data.get("username")
        note = str(request.data.get("note", ""))[:300]
        if username in (None, "", "nobody"):
            team.transfer(conversation, None, by=request.user, note=note)
        else:
            person = request.user if username == "me" else User.objects.filter(username=username).first()
            if person is None or not access.can(person, store, access.CONVERSATIONS, write=True):
                return fail("not_a_member", "این شخص عضو تیم پاسخ‌گویی این فروشگاه نیست.")
            team.transfer(conversation, person, by=request.user, note=note)
        conversation.refresh_from_db()
        return Response(ser.conversation_row(conversation, me=request.user))


class StateView(APIView):
    """`action`: close | reopen | take_from_ai | give_to_ai."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        conversation = conversation_of(store, pk)
        action = request.data.get("action")
        if action == "close":
            replies.close(conversation, request.user)
        elif action == "reopen":
            conversation.state = Conversation.State.HUMAN
            conversation.save(update_fields=["state", "updated_at"])
            meta = sla.meta_for(conversation)
            meta.resolved_at = None
            meta.save(update_fields=["resolved_at"])
        elif action == "take_from_ai":
            conversation.state = Conversation.State.HUMAN
            conversation.assigned_to = conversation.assigned_to or request.user
            conversation.save(update_fields=["state", "assigned_to", "updated_at"])
        elif action == "give_to_ai":
            conversation.state = Conversation.State.AI
            conversation.save(update_fields=["state", "updated_at"])
            meta = sla.meta_for(conversation)
            meta.waiting_since = None
            meta.sla_due_at = None
            meta.save(update_fields=["waiting_since", "sla_due_at"])
        else:
            return fail("bad_action", "کار نامعتبر است.")
        conversation.refresh_from_db()
        return Response(ser.conversation_row(conversation, me=request.user))


class TagsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        conversation = conversation_of(store, pk)
        tags = request.data.get("tags")
        if not isinstance(tags, list):
            return fail("bad_tags", "برچسب‌ها باید فهرست باشند.")
        cleaned: list[str] = []
        for tag in tags[:60]:
            text = str(tag).strip()[:40]
            if text and text not in cleaned:
                cleaned.append(text)
        cleaned = cleaned[:12]
        conversation.tags = cleaned
        conversation.save(update_fields=["tags", "updated_at"])
        return Response(ser.conversation_row(conversation, me=request.user))


class FollowUpCreateView(APIView):
    """«فردا یادآوری کن» from inside a conversation."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        conversation = conversation_of(store, pk)
        text = str(request.data.get("text", "")).strip()
        due = parse_datetime(str(request.data.get("due_at", ""))) if request.data.get("due_at") else None
        if due is None and request.data.get("in_hours") not in (None, ""):
            try:
                due = timezone.now() + timedelta(hours=float(request.data["in_hours"]))
            except (TypeError, ValueError):
                due = None
        if due is None:
            return fail("bad_due", "زمان پیگیری را مشخص کنید.")
        if timezone.is_naive(due):
            due = timezone.make_aware(due)
        target = "AGENT" if request.data.get("target") == "AGENT" else "CUSTOMER"
        if target == "CUSTOMER" and not text:
            return fail("empty", "متن پیام پیگیری خالی است.")
        row = followups.create(
            store, conversation=conversation, text=text or "پیگیری این گفتگو", due_at=due,
            by=request.user, target=target,
        )
        return Response(ser.followup_json(row), status=status.HTTP_201_CREATED)


class CannedListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        rows = CannedReply.objects.filter(store=store)
        channel = (request.query_params.get("channel") or "").upper()
        data = [ser.canned_json(r) for r in rows if not channel or not r.channels or channel in r.channels]
        return Response({"replies": data})

    def post(self, request, store_id):
        store = store_of(request, store_id, write=True)
        title = str(request.data.get("title", "")).strip()[:80]
        text = str(request.data.get("text", "")).strip()
        if not title or not text:
            return fail("empty", "عنوان و متن پاسخ آماده لازم است.")
        shortcut = str(request.data.get("shortcut", "")).strip().lstrip("/")[:30]
        row = CannedReply.objects.create(
            store=store, title=title, text=text, shortcut=shortcut,
            channels=[c.upper() for c in (request.data.get("channels") or []) if c], created_by=request.user,
        )
        return Response(ser.canned_json(row), status=status.HTTP_201_CREATED)


class CannedDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        row = get_object_or_404(CannedReply, pk=pk, store=store)
        for field, limit in (("title", 80), ("text", 4000), ("shortcut", 30)):
            if field in request.data:
                setattr(row, field, str(request.data[field]).strip().lstrip("/")[:limit] if field == "shortcut"
                        else str(request.data[field]).strip()[:limit])
        if "channels" in request.data:
            row.channels = [c.upper() for c in (request.data.get("channels") or []) if c]
        row.save()
        return Response(ser.canned_json(row))

    def delete(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        get_object_or_404(CannedReply, pk=pk, store=store).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MentionsView(APIView):
    """Notes where a colleague @-mentioned me, newest first."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        mine = []
        notes = (
            InternalNote.objects.filter(conversation__store=store).select_related("author", "conversation__customer")
            .order_by("-created_at")[:300]
        )
        for note in notes:
            if request.user.username in (note.mentions or []):
                mine.append({**ser.note_json(note), "conversation_id": note.conversation_id,
                             "customer": note.conversation.customer.name})
            if len(mine) >= 30:
                break
        return Response({"mentions": mine})

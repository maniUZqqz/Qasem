"""Developers: outgoing webhooks, the documented API, and the public API itself.

**API keys are not re-invented here.** A store's keys already live in
`apps.api_platform` - hashed, scoped, metered, with a panel page
(`/stores/<id>/api`) and a sandbox mode. The inbox API is three more *scopes*
on those same keys (`inbox_read`, `inbox_write`), documented on that same page
(see `register_endpoint_docs`), so a shop has one key page, not two.

The public API deliberately cannot approve a broadcast or send marketing: it can
read, push inbound messages, reply and create *drafts*. A test key
(`is_test`) goes through every check and then returns a shaped example without
touching anything - the platform's sandbox rule, honoured on every write here.
"""
from __future__ import annotations

from pathlib import Path

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api_platform.views import PublicAPIView
from apps.customers import webhooks as legacy_webhooks
from apps.customers.models import Conversation
from apps.stores import access

from . import contacts as contacts_mod
from . import events, ingest, norm, publicurl, replies, segments, serializers as ser, sla
from .models import Broadcast, Contact, Segment, WebhookDelivery, WebhookEndpoint
from .views_conversations import fail

DOC_PATH = Path(__file__).parent / "docs" / "api-fa.md"


def _admin(request, store_id):
    return access.get_store(request.user, store_id, access.SETTINGS)


# ---------------------------------------------------------------- panel


class WebhookListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _admin(request, store_id)
        return Response({
            "webhooks": [ser.webhook_json(w) for w in WebhookEndpoint.objects.filter(store=store)],
            "events": [{"key": k, "title": v} for k, v in events.EVENTS.items()],
        })

    def post(self, request, store_id):
        store = _admin(request, store_id)
        url = str(request.data.get("url", "")).strip()
        try:
            events.check_url(url)
        except events.UnsafeURL as exc:
            return fail("bad_url", str(exc))
        wanted = [e for e in (request.data.get("events") or []) if e in events.EVENTS]
        if WebhookEndpoint.objects.filter(store=store).count() >= 10:
            return fail("too_many", "حداکثر ۱۰ نشانی وب‌هوک مجاز است.")
        row = WebhookEndpoint.objects.create(store=store, url=url, events=wanted, created_by=request.user)
        data = ser.webhook_json(row)
        data["secret"] = row.secret  # the receiver needs it to verify signatures
        return Response(data, status=status.HTTP_201_CREATED)


class WebhookDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _admin(request, store_id)
        row = get_object_or_404(WebhookEndpoint, pk=pk, store=store)
        data = ser.webhook_json(row)
        data["secret"] = row.secret
        data["deliveries"] = list(row.deliveries.values(
            "id", "event", "status", "attempts", "response_code", "error", "created_at")[:30])
        return Response(data)

    def patch(self, request, store_id, pk):
        store = _admin(request, store_id)
        row = get_object_or_404(WebhookEndpoint, pk=pk, store=store)
        if "url" in request.data:
            try:
                row.url = events.check_url(str(request.data["url"]).strip())
            except events.UnsafeURL as exc:
                return fail("bad_url", str(exc))
        if "events" in request.data:
            row.events = [e for e in (request.data["events"] or []) if e in events.EVENTS]
        if "active" in request.data:
            row.active = bool(request.data["active"])
            if row.active:
                row.failure_count = 0
        row.save()
        return Response(ser.webhook_json(row))

    def delete(self, request, store_id, pk):
        store = _admin(request, store_id)
        get_object_or_404(WebhookEndpoint, pk=pk, store=store).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WebhookTestView(APIView):
    """Send a `ping` right now and report what the receiver said."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _admin(request, store_id)
        row = get_object_or_404(WebhookEndpoint, pk=pk, store=store)
        delivery = WebhookDelivery.objects.create(
            endpoint=row, event="message.received", event_id="evt_test_" + timezone.now().strftime("%H%M%S"),
            payload={"id": "evt_test", "event": "ping", "store_id": store.id,
                     "created_at": timezone.now().isoformat(), "data": {"note": "این یک آزمایش است."}},
            status=WebhookDelivery.Status.PENDING,
        )
        ok = events.deliver_one(delivery)
        return Response({"ok": ok, "response_code": delivery.response_code, "error": delivery.error})


class ApiDocsView(APIView):
    """The documentation text the developers page renders (Markdown, Persian)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _admin(request, store_id)
        base = publicurl.build(request, store, "/api/v1/inbox-api/")
        text = DOC_PATH.read_text(encoding="utf-8").replace("{{BASE}}", base) if DOC_PATH.exists() else ""
        return Response({"markdown": text, "base": base, "header": "X-Api-Key",
                         "scopes": ["inbox_read", "inbox_write"],
                         "events": [{"key": k, "title": v} for k, v in events.EVENTS.items()]})


# ------------------------------------------------------------ public API

#: Shown on the platform's own key page next to the other endpoints.
ENDPOINT_DOCS = [
    {
        "scope": "inbox_read", "title": "صندوق پیام - خواندن", "method": "GET",
        "path": "/api/v1/inbox-api/conversations/", "sync": True, "body": None,
        "note": "فهرست گفتگوها، پیام‌ها، مخاطبان و بخش‌ها. جزئیات کامل در بخش «توسعه‌دهندگان» صندوق پیام.",
    },
    {
        "scope": "inbox_write", "title": "صندوق پیام - نوشتن", "method": "POST",
        "path": "/api/v1/inbox-api/messages/", "sync": True,
        "body": {"sender_id": "user-42", "name": "نمونه", "phone": "09120000000", "text": "سلام"},
        "note": "پیام مشتری را از سیستم خودتان به صندوق می‌آورد؛ پاسخ، پیش‌نویس ارسال گروهی و ثبت مخاطب هم با همین دسترسی است. تأییدِ ارسال گروهی فقط از پنل است.",
    },
]


def register_endpoint_docs() -> None:
    """Append our endpoints to the platform's key page (idempotent)."""
    try:
        from apps.api_platform import views_keys
    except Exception:  # noqa: BLE001
        return
    have = {e.get("scope") for e in views_keys.ENDPOINTS}
    for doc in ENDPOINT_DOCS:
        if doc["scope"] not in have:
            views_keys.ENDPOINTS.append(doc)


class _InboxAPI(PublicAPIView):
    """Key auth + throttle + call log from the platform; scope = read or write."""

    write = False

    def initial(self, request, *args, **kwargs):
        self.endpoint = "inbox_write" if self.write else "inbox_read"
        super().initial(request, *args, **kwargs)

    def get_throttles(self):
        # The platform throttle reads `request.user.api_key`; fine for key auth.
        return super().get_throttles()


class ApiConversations(_InboxAPI):
    def get(self, request):
        denied = self.check_scope()
        if denied:
            return denied
        qp = request.query_params
        rows = Conversation.objects.filter(store=self.store).select_related("customer", "assigned_to", "inbox_meta")
        if qp.get("state"):
            rows = rows.filter(state=qp["state"].upper())
        if qp.get("channel"):
            rows = rows.filter(channel=qp["channel"].upper())
        limit = min(int(qp.get("limit", 50) or 50), 200)
        return Response({"conversations": [ser.conversation_row(c) for c in rows.order_by("-updated_at")[:limit]]})


class ApiMessages(_InboxAPI):
    def get(self, request, pk):
        denied = self.check_scope()
        if denied:
            return denied
        conversation = get_object_or_404(Conversation, pk=pk, store=self.store)
        rows = conversation.messages.select_related("inbox_meta", "inbox_meta__author").order_by("created_at")[:500]
        return Response({"messages": [ser.message_json(m) for m in rows]})


class ApiReply(_InboxAPI):
    write = True

    def post(self, request, pk):
        denied = self.check_scope()
        if denied:
            return denied
        conversation = get_object_or_404(Conversation.objects.select_related("customer", "store"), pk=pk, store=self.store)
        text = str(request.data.get("text", "")).strip()
        if not text:
            return fail("empty", "متن پیام خالی است.")
        if self.is_sandbox:
            return Response({"sandbox": True, "delivered": True, "reason": ""})
        outcome = replies.system_reply(conversation, text[:4000], kind="REPLY")
        sla.stop(conversation)  # an integration that answers has answered: the clock stops
        return Response({"delivered": bool(outcome["outcome"].get("sent")), "reason": outcome["outcome"].get("reason", "")})


class ApiInbound(_InboxAPI):
    """Push a customer message in from your own system (a form, a CRM, a shop)."""

    write = True

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied
        sender = str(request.data.get("sender_id", "")).strip()[:100]
        text = str(request.data.get("text", "")).strip()
        if not sender or not text:
            return fail("empty", "sender_id و text لازم است.")
        if self.is_sandbox:
            return Response({"sandbox": True, "conversation_id": 0, "message_id": 0}, status=status.HTTP_201_CREATED)
        name = str(request.data.get("name", "")).strip()[:100]
        phone = norm.normalize_phone(str(request.data.get("phone", "")))
        message = legacy_webhooks.deliver(self.store, "API", legacy_webhooks.Inbound(
            external_id=str(request.data.get("message_id", "")), thread_id=sender, sender_id=sender,
            name=name, text=text,
        ))
        if message is None:
            return Response({"duplicate": True})
        contacts_mod.identify(message.conversation.customer, phone=phone, name=name, source="api")
        ingest.answer_later(ingest.Received(message, message.conversation, message.conversation.customer))
        return Response({"conversation_id": message.conversation_id, "message_id": message.id},
                        status=status.HTTP_201_CREATED)


class ApiContacts(_InboxAPI):
    def get(self, request):
        denied = self.check_scope()
        if denied:
            return denied
        rows = Contact.objects.filter(store=self.store, is_test=False).order_by("-last_activity_at")[:200]
        return Response({"contacts": [ser.contact_json(c) for c in rows]})


class ApiContactUpsert(_InboxAPI):
    write = True

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied
        phone = norm.normalize_phone(str(request.data.get("phone", "")))
        if not phone:
            return fail("bad_phone", "شمارهٔ موبایل معتبر لازم است.")
        if self.is_sandbox:
            return Response({"sandbox": True, "phone": phone}, status=status.HTTP_201_CREATED)
        contact, created = Contact.objects.get_or_create(
            store=self.store, phone=phone, defaults={"name": str(request.data.get("name", ""))[:200], "source": "api"},
        )
        tags = request.data.get("tags")
        if isinstance(tags, list):
            contact.tags = sorted(set(contact.tags or []) | {str(t).strip()[:40] for t in tags if str(t).strip()})
            contact.save(update_fields=["tags", "updated_at"])
        return Response(ser.contact_json(contact), status=status.HTTP_201_CREATED if created else 200)


class ApiSegments(_InboxAPI):
    def get(self, request):
        denied = self.check_scope()
        if denied:
            return denied
        segments.ensure_builtin(self.store)
        return Response({"segments": [ser.segment_json(s) for s in Segment.objects.filter(store=self.store)]})


class ApiBroadcastDraft(_InboxAPI):
    """Drafts only. Approval is a person's decision in the panel - never an API call."""

    write = True

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied
        name, text = str(request.data.get("name", "")).strip()[:120], str(request.data.get("text", "")).strip()
        if not name or not text:
            return fail("empty", "name و text لازم است.")
        segment = None
        if request.data.get("segment_id"):
            segment = get_object_or_404(Segment, pk=request.data["segment_id"], store=self.store)
        if self.is_sandbox:
            return Response({"sandbox": True, "name": name}, status=status.HTTP_201_CREATED)
        row = Broadcast.objects.create(
            store=self.store, name=name, text=text, segment=segment, created_by=None,
            channels=[c.upper() for c in (request.data.get("channels") or []) if c],
        )
        return Response({**ser.broadcast_json(row), "notice": "پیش‌نویس ساخته شد؛ تأیید و ارسال فقط از پنل و توسط مالک ممکن است."},
                        status=status.HTTP_201_CREATED)

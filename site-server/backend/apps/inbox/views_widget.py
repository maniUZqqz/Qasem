"""The site-chat widget's public API (`/api/v1/widget/<key>/...`) and its script.

Public means *anyone on the internet can call it*, so the rules are strict:

* the key (`connection.secret`) is public by nature - it is in the page source -
  so it only identifies the store; it grants nothing but "start/continue a chat";
* a chat is continued with a **session token** the server minted, kept in the
  visitor's localStorage. Without it nobody can read anyone's messages;
* the optional **allowed origins** list is enforced on every call, so a store
  can pin the widget to its own site (a copied snippet then does nothing);
* writes are rate-limited per session and per IP, and bodies are capped;
* no cookies, so `Access-Control-Allow-Origin: *` is safe - there are no
  ambient credentials for a hostile page to ride on.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.customers.models import Conversation, Customer, Message

from . import contacts, hours, ingest, norm, team
from .adapters.base import Incoming
from .models import AgentProfile, ChannelConnection, ConversationMeta, WidgetSession

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).parent / "widget" / "widget.js"
MAX_TEXT = 2000
SEND_PER_MINUTE = 12
SEND_PER_MINUTE_IP = 40
SESSIONS_PER_HOUR_IP = 20

DEFAULTS = {
    "title": "گفتگو با ما", "subtitle": "معمولاً در چند دقیقه پاسخ می‌دهیم",
    "offline_subtitle": "خارج از ساعت کاری هستیم؛ پیام بگذارید",
    "welcome": "سلام! چطور می‌توانیم کمک کنیم؟", "color": "#2563eb", "position": "left", "auto_open": False,
}


def _cors(response, request=None):
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type"
    response["Access-Control-Max-Age"] = "600"
    return response


def _json(data, status=200):
    return _cors(JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False}))


def _error(code, message, status=400):
    return _json({"error": {"code": code, "message": message}}, status)


def _ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")) or "?"


def _limited(bucket: str, limit: int, window: int = 60) -> bool:
    key = f"widget:{bucket}:{int(timezone.now().timestamp() // window)}"
    cache.add(key, 0, window + 30)
    try:
        return cache.incr(key) > limit
    except ValueError:
        return False


def _connection(key: str) -> ChannelConnection | None:
    if len(key or "") < 16:
        return None
    return ChannelConnection.objects.filter(
        kind=ChannelConnection.Kind.WEBCHAT, secret=key, enabled=True,
    ).select_related("store").first()


def _origin_ok(connection: ChannelConnection, request) -> bool:
    allowed = [o.rstrip("/").lower() for o in (connection.config or {}).get("allowed_origins", []) if o]
    if not allowed:
        return True
    origin = (request.headers.get("Origin") or request.headers.get("Referer") or "").lower()
    return any(origin == a or origin.startswith(a + "/") for a in allowed)


@method_decorator(csrf_exempt, name="dispatch")
class ScriptView(View):
    def get(self, request, key):
        connection = _connection(key)
        body = SCRIPT.read_text(encoding="utf-8") if connection else "/* widget disabled */"
        response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
        response["Cache-Control"] = "public, max-age=300"
        return _cors(response)


class _Base(View):
    def dispatch(self, request, *args, **kwargs):
        if request.method == "OPTIONS":
            return _cors(HttpResponse(status=204))
        return super().dispatch(request, *args, **kwargs)


@method_decorator(csrf_exempt, name="dispatch")
class ConfigView(_Base):
    def get(self, request, key):
        connection = _connection(key)
        if connection is None or not _origin_ok(connection, request):
            return _json({"enabled": False})
        cfg = team.settings_for(connection.store)
        look = {**DEFAULTS, **(cfg.widget or {})}
        if cfg.greeting_message and "welcome" not in (cfg.widget or {}):
            look["welcome"] = cfg.greeting_message
        online = any(
            p.effective_status == AgentProfile.Status.ONLINE
            for p in AgentProfile.objects.filter(store=connection.store, accepts_chats=True)
        )
        return _json({
            "enabled": True, **look, "open_now": hours.is_open(cfg.working_hours),
            "agent_online": online, "store": connection.store.name,
        })


@method_decorator(csrf_exempt, name="dispatch")
class SessionView(_Base):
    def post(self, request, key):
        connection = _connection(key)
        if connection is None or not _origin_ok(connection, request):
            return _error("disabled", "گفتگو فعال نیست.", 403)
        if _limited("sess:" + _ip(request), SESSIONS_PER_HOUR_IP, 3600):
            return _error("rate", "درخواست‌ها زیاد است؛ کمی بعد دوباره امتحان کنید.", 429)
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            body = {}
        name = str(body.get("name", "")).strip()[:80]
        phone = norm.normalize_phone(str(body.get("phone", "")))
        visitor = "v_" + uuid.uuid4().hex[:20]
        store = connection.store
        customer = Customer.objects.create(
            store=store, channel="webchat", external_id=visitor, name=name or "بازدیدکنندهٔ سایت", phone=phone,
        )
        conversation = Conversation.objects.create(
            store=store, customer=customer, channel="WEBCHAT", external_id=visitor, state=Conversation.State.AI,
        )
        contacts.identify(customer, phone=phone, name=name, source="webchat")
        token = WidgetSession.new_token()
        WidgetSession.objects.create(
            connection=connection, token=token, customer=customer, conversation=conversation,
            origin=(request.headers.get("Origin") or "")[:200],
        )
        return _json({"token": token})


def _session(request, token: str) -> WidgetSession | None:
    if not token:
        return None
    return WidgetSession.objects.filter(token=token).select_related(
        "connection", "connection__store", "conversation", "customer",
    ).first()


def _message(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "text": m.text, "at": m.created_at.isoformat()}


@method_decorator(csrf_exempt, name="dispatch")
class SendView(_Base):
    def post(self, request, key):
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            return _error("bad_json", "درخواست نامعتبر است.")
        session = _session(request, str(body.get("token", "")))
        if session is None or session.connection.secret != key or not session.connection.enabled:
            return _error("no_session", "نشست پیدا نشد.", 404)
        if not _origin_ok(session.connection, request):
            return _error("disabled", "گفتگو فعال نیست.", 403)
        text = str(body.get("text", "")).strip()
        if not text:
            return _error("empty", "پیام خالی است.")
        if len(text) > MAX_TEXT:
            return _error("too_long", "پیام بیش از ۲۰۰۰ نویسه است.")
        if _limited(f"s:{session.pk}", SEND_PER_MINUTE) or _limited("ip:" + _ip(request), SEND_PER_MINUTE_IP):
            return _error("rate", "کمی آهسته‌تر؛ چند لحظه بعد دوباره بفرستید.", 429)

        phone = norm.normalize_phone(str(body.get("phone", ""))) if body.get("phone") else ""
        incoming = Incoming(
            external_id="w" + uuid.uuid4().hex[:18], thread_id=session.conversation.external_id,
            sender_id=session.customer.external_id, name=str(body.get("name", "")).strip()[:80],
            phone=phone, text=text,
        )
        outcome = ingest.receive(session.connection, incoming)
        if outcome.message is None:
            return _error("duplicate", "این پیام قبلاً ثبت شده است.", 409)
        ingest.answer_later(outcome)
        WidgetSession.objects.filter(pk=session.pk).update(last_seen_at=timezone.now())
        return _json({"message": _message(outcome.message)})


@method_decorator(csrf_exempt, name="dispatch")
class MessagesView(_Base):
    def get(self, request, key):
        session = _session(request, request.GET.get("token", ""))
        if session is None or session.connection.secret != key:
            return _error("no_session", "نشست پیدا نشد.", 404)
        if not _origin_ok(session.connection, request):
            return _error("disabled", "گفتگو فعال نیست.", 403)
        try:
            after = int(request.GET.get("after", 0) or 0)
        except ValueError:
            after = 0
        rows = session.conversation.messages.filter(id__gt=after).order_by("id")[:100]
        WidgetSession.objects.filter(pk=session.pk).update(last_seen_at=timezone.now())
        return _json({"messages": [_message(m) for m in rows]})

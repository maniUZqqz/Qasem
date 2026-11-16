"""The site-chat widget's public API (`/api/v1/widget/<key>/...`) and its script.

Public means *anyone on the internet can call it*, so the rules are strict:

* the key (`connection.secret`) is public by nature - it is in the page source -
  so it only identifies the store; it grants nothing but "start/continue a chat";
* a chat is continued with a **session token** the server minted, kept in the
  visitor's localStorage. Without it nobody can read anyone's messages;
* the optional **allowed origins** list is enforced on every call, so a store
  can pin the widget to its own site (a copied snippet then does nothing);
* writes are rate-limited per session and per IP, and bodies are capped;
* **opening a session writes nothing**: the token is a signed ticket, and the
  customer, the conversation and the CRM contact are created by the *first real
  message*. Anyone can call `/session/` (the key is public), so it must cost the
  shop nothing - an empty session never reaches the team's inbox or the CRM;
* the visitor's IP comes from `X-Real-IP` set by our own reverse proxy, never
  from a client-supplied `X-Forwarded-For` (see `client_ip`);
* no cookies, so `Access-Control-Allow-Origin: *` is safe - there are no
  ambient credentials for a hostile page to ride on.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import uuid
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
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
#: New chats (a first message from a visitor we have not met) per hour. Cheap
#: protection against someone typing into the widget in a loop: one address can
#: open a few chats, and one store never gets flooded by the whole internet.
NEW_CHATS_PER_HOUR_IP = 10
NEW_CHATS_PER_HOUR_STORE = 150

#: The widget promises nothing the store has not said (no «در چند دقیقه»): the
#: store writes its own subtitle on the Bot page.
DEFAULTS = {
    "title": "گفتگو با ما", "subtitle": "پیامتان را بنویسید",
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


def _valid_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _is_local_proxy(address: str) -> bool:
    """The TCP peer is on this machine / the private network: that is our own nginx."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def client_ip(request) -> str:
    """The visitor's address, for rate limits - and only an address we can trust.

    Behind nginx the TCP peer is the proxy, and nginx *overwrites* `X-Real-IP`
    with `$remote_addr`. `X-Forwarded-For` is the opposite: `$proxy_add_x_forwarded_for`
    **appends** to whatever the client sent, so its first entry is attacker-controlled
    (the bypass that let one machine open a thousand sessions). So:

    * the peer is a local proxy  -> use `X-Real-IP` (the proxy's own measurement);
    * anything else (no proxy, or a request that skipped it) -> the peer itself;
    * `X-Forwarded-For` is never read.
    """
    peer = (request.META.get("REMOTE_ADDR") or "").strip()
    if _is_local_proxy(peer):
        real = (request.META.get("HTTP_X_REAL_IP") or "").strip()
        if _valid_ip(real):
            return real
    return peer or "?"


def _ip(request) -> str:
    return client_ip(request)


# ---- the session ticket ----------------------------------------------------
#
# `w_<visitor>_<mac>` - 47 characters, so it fits `WidgetSession.token`. The mac
# binds it to this store's widget (connection id) and to this server's secret, so
# a ticket cannot be invented, and one store's ticket is worthless on another's
# key. It is a bearer ticket for «start a chat», nothing more: whoever holds it can
# send messages into *one* conversation and read that conversation back.


def _mac(connection_id: int, visitor: str) -> str:
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"widget:{connection_id}:{visitor}".encode(), hashlib.sha256).hexdigest()[:24]


def new_ticket(connection: ChannelConnection) -> str:
    visitor = uuid.uuid4().hex[:20]
    return f"w_{visitor}_{_mac(connection.pk, visitor)}"


def ticket_visitor(connection: ChannelConnection, token: str) -> str:
    """The visitor id inside a genuine ticket for this connection, else ''."""
    parts = (token or "").split("_")
    if len(parts) != 3 or parts[0] != "w" or len(parts[1]) != 20:
        return ""
    return parts[1] if hmac.compare_digest(parts[2], _mac(connection.pk, parts[1])) else ""


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
        # Nothing is written here: the conversation, customer and CRM contact are
        # created by the visitor's first message (`SendView`). A name/phone the
        # caller wants kept travels with that message.
        return _json({"token": new_ticket(connection)})


def _session(request, token: str) -> WidgetSession | None:
    if not token:
        return None
    return WidgetSession.objects.filter(token=token).select_related(
        "connection", "connection__store", "conversation", "customer",
    ).first()


def _message(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "text": m.text, "at": m.created_at.isoformat()}


def _open_chat(connection: ChannelConnection, token: str, visitor: str, request, name: str, phone: str) -> WidgetSession:
    """The visitor's first message: now - and only now - the chat exists."""
    store = connection.store
    external = "v_" + visitor
    try:
        with transaction.atomic():
            customer = Customer.objects.create(
                store=store, channel="webchat", external_id=external, name=name or "بازدیدکنندهٔ سایت", phone=phone,
            )
            conversation = Conversation.objects.create(
                store=store, customer=customer, channel="WEBCHAT", external_id=external,
                state=Conversation.State.AI,
            )
            contacts.identify(customer, phone=phone, name=name, source="webchat")
            return WidgetSession.objects.create(
                connection=connection, token=token, customer=customer, conversation=conversation,
                origin=(request.headers.get("Origin") or "")[:200],
            )
    except IntegrityError:
        # Two first messages from the same tab raced: the other one won.
        existing = _session(request, token)
        if existing is None:
            raise
        return existing


@method_decorator(csrf_exempt, name="dispatch")
class SendView(_Base):
    def post(self, request, key):
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            return _error("bad_json", "درخواست نامعتبر است.")
        token = str(body.get("token", ""))
        session = _session(request, token)
        pending: ChannelConnection | None = None
        if session is None:
            connection = _connection(key)
            if connection is not None and ticket_visitor(connection, token):
                pending = connection
        elif session.connection.secret != key or not session.connection.enabled:
            session = None
        if session is None and pending is None:
            return _error("no_session", "نشست پیدا نشد.", 404)
        connection = pending or session.connection
        if not _origin_ok(connection, request):
            return _error("disabled", "گفتگو فعال نیست.", 403)
        text = str(body.get("text", "")).strip()
        if not text:
            return _error("empty", "پیام خالی است.")
        if len(text) > MAX_TEXT:
            return _error("too_long", "پیام بیش از ۲۰۰۰ نویسه است.")
        bucket = "tok:" + token[:64]  # one budget per visitor, before and after the chat row exists
        if _limited(bucket, SEND_PER_MINUTE) or _limited("ip:" + _ip(request), SEND_PER_MINUTE_IP):
            return _error("rate", "کمی آهسته‌تر؛ چند لحظه بعد دوباره بفرستید.", 429)

        name = str(body.get("name", "")).strip()[:80]
        phone = norm.normalize_phone(str(body.get("phone", ""))) if body.get("phone") else ""
        if session is None:
            if _limited("newchat:" + _ip(request), NEW_CHATS_PER_HOUR_IP, 3600) or _limited(
                f"newchat-store:{connection.pk}", NEW_CHATS_PER_HOUR_STORE, 3600,
            ):
                return _error("rate", "گفتگوهای تازه زیاد است؛ کمی بعد دوباره امتحان کنید.", 429)
            session = _open_chat(connection, token, ticket_visitor(connection, token), request, name, phone)
        incoming = Incoming(
            external_id="w" + uuid.uuid4().hex[:18], thread_id=session.conversation.external_id,
            sender_id=session.customer.external_id, name=name, phone=phone, text=text,
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
        token = request.GET.get("token", "")
        session = _session(request, token)
        if session is None:
            # A ticket that has not sent anything yet: valid, and nothing to show.
            connection = _connection(key)
            if connection is not None and ticket_visitor(connection, token):
                if not _origin_ok(connection, request):
                    return _error("disabled", "گفتگو فعال نیست.", 403)
                return _json({"messages": []})
            return _error("no_session", "نشست پیدا نشد.", 404)
        if session.connection.secret != key:
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

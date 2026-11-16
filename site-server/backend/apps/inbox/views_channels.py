"""Connect pages (API) and the inbound doors for the platforms that POST to us."""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.customers import webhooks as legacy_webhooks
from apps.stores import access
from services.publishing import channels as legacy_channels

from . import adapters, dispatch, guides, ingest, team
from .models import ChannelConnection
from .views_conversations import fail

logger = logging.getLogger(__name__)

#: The channels a store can open a connect page for, in page order.
KINDS = guides.CHANNEL_ORDER


def ensure_connections(store) -> list[ChannelConnection]:
    """One row per channel, so the page always has something to show."""
    rows = {c.kind: c for c in ChannelConnection.objects.filter(store=store)}
    out = []
    for kind in KINDS:
        row = rows.get(kind)
        if row is None:
            row = ChannelConnection.objects.create(store=store, kind=kind, title=guides.GUIDES[kind]["title"])
            # A shop that connected Telegram before this page existed is already
            # connected - do not make them paste the token again.
            if kind == "TELEGRAM" and legacy_channels.telegram_token(store):
                row.enabled = True
                row.save(update_fields=["enabled", "updated_at"])
        out.append(row)
    return out


def hook_url(request, connection: ChannelConnection) -> str:
    if connection.kind == "TELEGRAM":
        return request.build_absolute_uri(
            f"/api/v1/webhooks/telegram/{legacy_webhooks.secret_for(connection.store)}/"
        )
    if connection.kind == "INSTAGRAM":
        return request.build_absolute_uri(
            f"/api/v1/webhooks/instagram/{legacy_webhooks.secret_for(connection.store)}/"
        )
    cls = adapters.adapter_class(connection.kind)
    if cls is None or not (cls.can_receive_webhook):
        return ""
    return request.build_absolute_uri(f"/api/v1/inbox/hook/{cls.slug}/{connection.secret}/")


def widget_snippet(request, connection: ChannelConnection) -> str:
    src = request.build_absolute_uri(f"/api/v1/widget/{connection.secret}.js")
    return f'<script src="{src}" async></script>'


def _row(request, connection: ChannelConnection) -> dict:
    from .serializers import channel_json

    data = channel_json(
        connection, guides.guide_for(connection.kind),
        hook_url(request, connection), dispatch.is_ready(connection),
    )
    if connection.kind == "WEBCHAT":
        data["snippet"] = widget_snippet(request, connection)
        data["widget_key"] = connection.secret
    if connection.kind == "INSTAGRAM":
        data["ready"] = legacy_channels.configured(legacy_channels.INSTAGRAM, connection.store)
        data["enabled"] = data["ready"]
    return data


class ChannelsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)
        rows = ensure_connections(store)
        data = [_row(request, c) for c in rows]
        for item in data:
            if item["kind"] == "SMS":
                from . import sms_gateway

                item["sms"] = sms_gateway.status(store)
                item["can_toggle_forwarding"] = bool(request.user.is_staff)
        return Response({"channels": data})


def _public_url(request) -> bool:
    host = request.get_host().split(":")[0]
    return request.is_secure() and host not in ("localhost", "127.0.0.1")


class ChannelDetailView(APIView):
    """Save credentials, switch on/off, choose the mode. Enabling requires a green check."""

    permission_classes = [IsAuthenticated]

    def put(self, request, store_id, kind):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        kind = kind.upper()
        if kind not in KINDS:
            return fail("unknown_channel", "کانال ناشناخته است.")
        connection = get_object_or_404(ensure_and_get(store, kind))
        data = request.data
        guide = guides.GUIDES[kind]
        if kind == "INSTAGRAM":
            return fail("managed_elsewhere", "اینستاگرام از صفحهٔ «اتصال‌ها» با توکن نوین‌هاب تنظیم می‌شود.")

        token = str(data.get("token", "") or "").strip()
        if token and not token.startswith("••••"):
            connection.token = token[:400]
            if kind == "TELEGRAM":
                # The legacy sender reads the store profile; keep one truth.
                profile = getattr(store, "profile", None)
                if profile is not None:
                    profile.telegram_bot_token = token[:200]
                    profile.save(update_fields=["telegram_bot_token"])
        config = dict(connection.config or {})
        for field in guide.get("fields", []):
            key = field["key"]
            if key == "token" or key not in data:
                continue
            value = data[key]
            if field.get("kind") == "bool":
                value = bool(value)
            elif field.get("kind") == "list":
                value = [str(v).strip().rstrip("/")[:200] for v in (value or []) if str(v).strip()][:20]
            else:
                value = str(value or "").strip()[:300]
                if field.get("secret") and (not value or value.startswith("••••")):
                    continue  # blank/masked = keep the stored secret
            config[key] = value
        connection.config = config
        if data.get("mode") in ChannelConnection.Mode.values:
            connection.mode = data["mode"]
        connection.save()

        want = data.get("enabled")
        message = ""
        if want is True:
            problem = self._can_enable(connection)
            if problem:
                connection.enabled = False
                connection.save(update_fields=["enabled", "updated_at"])
                return Response({"channel": _row(request, connection), "enabled_refused": problem}, status=200)
            connection.enabled = True
            connection.save(update_fields=["enabled", "updated_at"])
            if connection.kind == "SMS":
                from . import sms_gateway

                sms_gateway.start(connection)
                message = "پیامک روشن شد؛ فقط پیام‌های تازه وارد صندوق می‌شوند."
            else:
                message = self._start_receiving(request, connection)
        elif want is False:
            connection.enabled = False
            connection.save(update_fields=["enabled", "updated_at"])
        elif token:
            dispatch.check_health(connection)  # saving a token always tells you if it works
        return Response({"channel": _row(request, connection), "message": message})

    @staticmethod
    def _can_enable(connection: ChannelConnection) -> str:
        cls = adapters.adapter_class(connection.kind)
        if connection.kind == "WEBCHAT":
            return ""
        if connection.kind == "SMS":
            return "" if sms_available(connection.store) else (
                "هیچ گوشی پیامکی آنلاین نیست؛ اول برنامهٔ پیامک را روی گوشی وصل کنید."
            )
        if cls is not None and cls.needs_token and not dispatch.token_for(connection):
            return "اول توکن را وارد کنید."
        if connection.kind == "WHATSAPP":
            cfg = connection.config or {}
            missing = [k for k in ("phone_number_id", "app_secret", "verify_token") if not cfg.get(k)]
            if missing:
                return "برای واتساپ شناسهٔ شماره، App Secret و رمز تأیید لازم است."
        result = dispatch.check_health(connection)
        return "" if result["ok"] else f"کانال هنوز سالم نیست: {result['detail']}"

    @staticmethod
    def _start_receiving(request, connection: ChannelConnection) -> str:
        """Webhook when we are reachable from the internet, polling otherwise."""
        adapter = dispatch.adapter_for(connection)
        if adapter is None or not (adapter.can_receive_webhook or adapter.can_poll):
            return ""
        cfg = dict(connection.config or {})
        mode = connection.mode
        if mode in (ChannelConnection.Mode.AUTO, ChannelConnection.Mode.WEBHOOK) and adapter.can_receive_webhook \
                and connection.kind not in ("WHATSAPP",):
            if _public_url(request) or mode == ChannelConnection.Mode.WEBHOOK:
                result = adapter.register_webhook(hook_url(request, connection))
                if result.ok:
                    cfg["webhook_registered"] = True
                    connection.config = cfg
                    connection.save(update_fields=["config", "updated_at"])
                    return "وب‌هوک ثبت شد؛ پیام‌ها همان لحظه می‌رسند."
                if mode == ChannelConnection.Mode.WEBHOOK:
                    return f"ثبت وب‌هوک نشد: {result.reason}"
        if adapter.can_poll:
            clear = getattr(adapter, "clear_webhook", None)
            if clear is not None and cfg.get("webhook_registered"):
                clear()
            cfg["webhook_registered"] = False
            connection.config = cfg
            connection.save(update_fields=["config", "updated_at"])
            return "پیام‌ها هر نیم دقیقه از ربات گرفته می‌شود (پرسش دوره‌ای)."
        return ""


def ensure_and_get(store, kind):
    ensure_connections(store)
    return ChannelConnection.objects.filter(store=store, kind=kind)


def sms_available(store) -> bool:
    from . import sms_gateway

    return sms_gateway.available(store)


class ChannelCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, kind):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        connection = ensure_and_get(store, kind.upper()).first()
        if connection is None:
            return fail("unknown_channel", "کانال ناشناخته است.")
        if connection.kind in ("INSTAGRAM",):
            ok = legacy_channels.configured(legacy_channels.INSTAGRAM, store)
            return Response({"ok": ok, "detail": "توکن نوین‌هاب ثبت شده است." if ok else "توکن نوین‌هاب ثبت نشده است."})
        if connection.kind == "WEBCHAT":
            return Response({"ok": True, "detail": "ویجت نیازی به بررسی ندارد."})
        if connection.kind == "SMS":
            ok = sms_available(store)
            return Response({"ok": ok, "detail": "گوشی پیامکی آنلاین است." if ok else "هیچ گوشی پیامکی آنلاین نیست."})
        return Response(dispatch.check_health(connection))


class SmsForwardingView(APIView):
    """Staff only: the phone gateway's global «save incoming SMS» switch.

    Global and privacy-sensitive (it stores *every* SMS a paired phone receives),
    so it is never flipped by a store owner and never automatically - only a
    service administrator, deliberately.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        access.get_store(request.user, store_id, access.SETTINGS)
        if not request.user.is_staff:
            return fail("staff_only", "این کلید را فقط مدیر سرویس می‌تواند عوض کند.", 403)
        from apps.mobile.models import MobileSettings

        row = MobileSettings.get()
        row.forward_incoming_sms = bool(request.data.get("on"))
        row.save(update_fields=["forward_incoming_sms"])
        return Response({"forwarding": row.forward_incoming_sms})


class ChannelWebhookView(APIView):
    """Register (or clear) the webhook with the platform."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, kind):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        connection = ensure_and_get(store, kind.upper()).first()
        adapter = dispatch.adapter_for(connection) if connection else None
        if adapter is None or not adapter.can_receive_webhook or connection.kind == "WHATSAPP":
            return fail("no_webhook", "این کانال ثبت خودکار وب‌هوک ندارد؛ نشانی را دستی بدهید.")
        if request.data.get("clear"):
            clear = getattr(adapter, "clear_webhook", None)
            result = clear() if clear else adapters.SendResult(False, "پاک‌کردن وب‌هوک پشتیبانی نمی‌شود.")
        else:
            result = adapter.register_webhook(hook_url(request, connection))
        cfg = dict(connection.config or {})
        cfg["webhook_registered"] = bool(result.ok and not request.data.get("clear"))
        connection.config = cfg
        connection.save(update_fields=["config", "updated_at"])
        return Response({"ok": result.ok, "detail": result.reason or "انجام شد."})


class ChannelPollView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, kind):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        connection = ensure_and_get(store, kind.upper()).first()
        if connection is None:
            return fail("unknown_channel", "کانال ناشناخته است.")
        return Response(ingest.poll_connection(connection))


# ----------------------------------------------------------- inbound hooks


@method_decorator(csrf_exempt, name="dispatch")
class HookView(View):
    """`/api/v1/inbox/hook/<slug>/<secret>/` - Bale, Eitaa, Rubika, WhatsApp post here.

    Same rules as the legacy webhook: always 200 for anything we do not
    understand (a platform that gets errors disables the hook), 403 only for a
    caller that failed verification, and never wait for the AI.
    """

    def _connection(self, slug, secret):
        cls = adapters.by_slug(slug)
        if cls is None or len(secret or "") < 16:
            return None
        return ChannelConnection.objects.filter(
            kind=cls.key, secret=secret, enabled=True,
        ).select_related("store", "store__profile").first()

    def get(self, request, slug, secret):
        connection = self._connection(slug, secret)
        if connection is None or connection.kind != "WHATSAPP":
            return HttpResponse(status=404)
        challenge = dispatch.adapter_for(connection).handshake(request.GET)
        if challenge is None:
            return HttpResponse(status=403)
        return HttpResponse(challenge, content_type="text/plain")

    def post(self, request, slug, secret):
        connection = self._connection(slug, secret)
        if connection is None:
            return HttpResponse(status=404)
        adapter = dispatch.adapter_for(connection)
        body = request.body
        if not adapter.verify(body, request.headers):
            logger.warning("inbox hook refused on %s", slug)
            return HttpResponse(status=403)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return JsonResponse({"ok": True, "ignored": "unparseable"})
        accepted = 0
        for incoming in adapter.parse(payload):
            outcome = ingest.receive(connection, incoming)
            if outcome.message is None:
                continue
            accepted += 1
            ingest.answer_later(outcome)
        return JsonResponse({"ok": True, "accepted": accepted})

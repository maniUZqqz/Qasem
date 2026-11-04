"""Panel side of NM-Mobile («دستگاه‌های موبایل»): devices, SMS queue, opt-outs, approvals, calls, prices, settings, Telegram link.

Staff login (JWT/session) only — a paired phone cannot call these.
"""
from __future__ import annotations

import os
from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response

from . import calls, lookups, monitor, phone, products, sms, telegram_provider
from .base import MobileAPIView, MobileError, log_action, require_fields
from .models import (LOOKUP_PLATFORMS, MobileActionLog, MobileCall, MobileCallConsent, MobileDevice, MobileSettings, ProductPricing,
                     ProfileLookup, SmsCampaignApproval, SmsMessage, SmsOptOut)
from .views import _limit, device_dict, settings_payload, sms_dict


class PanelView(MobileAPIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.device is not None:
            raise MobileError("panel_only", "این بخش از پنل است، نه از گوشی.", 403)


# ------------------------------------------------------------------ overview + devices

class OverviewView(PanelView):
    def get(self, request):
        s = MobileSettings.get()
        devices = list(MobileDevice.objects.filter(revoked_at__isnull=True).select_related("user"))
        server = os.getenv("PUBLIC_BASE_URL") or request.build_absolute_uri("/").rstrip("/")
        return Response({
            "server_url": server,
            "pairing_steps": [
                "برنامهٔ NM Mobile را روی گوشی نصب کنید.", "در صفحهٔ «اتصال به NM» آدرسِ بالا را بنویسید.",
                "نام کاربری و رمزِ کارمندیِ خودتان را وارد کنید و یک نام برای گوشی بنویسید.", "روی «اتصال و جفت‌سازی» بزنید؛ گوشی همین‌جا در فهرست می‌آید.",
            ],
            "counts": {"devices": len(devices), "devices_online": sum(1 for d in devices if d.online),
                       "sms_queued": SmsMessage.objects.filter(state=SmsMessage.State.QUEUED).count(),
                       "calls": MobileCall.objects.count(), "optouts": SmsOptOut.objects.count()},
            "settings": _settings_full(s),
            "telegram": telegram_provider.status(),
        })


def _device_row(d: MobileDevice) -> dict:
    row = device_dict(d)
    row.update({"token_prefix": d.token_prefix, "online": d.online, "revoked_at": d.revoked_at, "last_ip": d.last_ip,
                "battery_percent": d.battery_percent, "charging": d.charging, "network": d.network, "sims": d.sims,
                "sms_ready": d.sms_ready, "heartbeat_at": d.heartbeat_at, "sms_sent_today": d.sms.filter(
                    state__in=[SmsMessage.State.SENT, SmsMessage.State.DELIVERED], sent_at__gte=timezone.now() - timedelta(days=1)).count()})
    return row


class DevicesView(PanelView):
    def get(self, request):
        rows = MobileDevice.objects.select_related("user").order_by("revoked_at", "-last_seen_at", "-created_at")
        return Response({"count": rows.count(), "results": [_device_row(d) for d in rows]})


class DeviceDetailView(PanelView):
    def _get(self, uid):
        d = MobileDevice.objects.filter(uid=uid).select_related("user").first()
        if d is None:
            raise MobileError("not_found", "گوشی پیدا نشد.", 404)
        return d

    def patch(self, request, uid):
        d = self._get(uid)
        if "name" in request.data and str(request.data["name"]).strip():
            d.name = str(request.data["name"]).strip()[:120]
        if "sms_enabled" in request.data:
            d.sms_enabled = bool(request.data["sms_enabled"])
        d.save()
        log_action(request, "device.edit", str(d.uid), {"name": d.name, "sms_enabled": d.sms_enabled})
        return Response(_device_row(d))

    def delete(self, request, uid):
        return DeviceRevokeView().revoke(request, self._get(uid))


class DeviceRevokeView(PanelView):
    def revoke(self, request, d: MobileDevice):
        d.revoked_at, d.revoked_by = timezone.now(), request.user
        d.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
        log_action(request, "device.revoke", str(d.uid), {"name": d.name}, message=f"دسترسیِ «{d.name}» لغو شد")
        return Response(_device_row(d))

    def post(self, request, uid):
        d = MobileDevice.objects.filter(uid=uid).select_related("user").first()
        if d is None:
            raise MobileError("not_found", "گوشی پیدا نشد.", 404)
        return self.revoke(request, d)


# ------------------------------------------------------------------ SMS: cancel, opt-outs, approvals

class SmsCancelView(PanelView):
    def post(self, request, uid):
        return Response(monitor.run_action(request, "sms.cancel", str(uid)))


class OptOutsView(PanelView):
    def get(self, request):
        limit, offset = _limit(request, 50, 200)
        qs = SmsOptOut.objects.select_related("created_by")
        q = phone.ascii_digits(request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(number__contains=q.lstrip("0"))
        return Response({"count": qs.count(), "results": [{
            "id": o.pk, "number": phone.national(o.number), "normalized": o.number, "reason": o.reason, "reason_label": o.get_reason_display(),
            "source_text": o.source_text, "created_at": o.created_at, "by": o.created_by.get_username() if o.created_by else None}
            for o in qs[offset:offset + limit]]})

    def post(self, request):
        require_fields(request.data, "number")
        obj, created = sms.add_opt_out(request.data["number"], SmsOptOut.Reason.MANUAL, str(request.data.get("note") or ""), request.user)
        log_action(request, "optout.add", obj.number, message="به فهرستِ لغو اضافه شد")
        return Response({"id": obj.pk, "number": phone.national(obj.number), "created": created}, status=201 if created else 200)


class OptOutDetailView(PanelView):
    def delete(self, request, pk):
        obj = SmsOptOut.objects.filter(pk=pk).first()
        if obj is None:
            raise MobileError("not_found", "پیدا نشد.", 404)
        number = obj.number
        obj.delete()
        log_action(request, "optout.remove", number, message="از فهرستِ لغو برداشته شد (به درخواستِ خودِ شخص و با مسئولیتِ شما)")
        return Response({"ok": True})


def _approval_dict(a: SmsCampaignApproval) -> dict:
    return {"id": a.pk, "ref": a.ref, "title": a.title, "source": a.source, "approved_by": a.approved_by.get_username() if a.approved_by else None,
            "approved_at": a.approved_at, "valid_until": a.valid_until, "max_messages": a.max_messages, "sent_count": a.sent_count,
            "revoked_at": a.revoked_at, "active": a.active}


class ApprovalsView(PanelView):
    def get(self, request):
        return Response({"results": [_approval_dict(a) for a in SmsCampaignApproval.objects.select_related("approved_by")[:100]]})

    def post(self, request):
        d = request.data
        require_fields(d, "ref", "title")
        mx = d.get("max_messages")
        a = sms.register_campaign_approval(d["ref"], d["title"], request.user, calls.parse_time(d["valid_until"]) if d.get("valid_until") else None,
                                           int(mx) if str(mx or "").isdigit() else None, "manual")
        log_action(request, "campaign.approve", a.ref, {"title": a.title}, message="کمپینِ پیامکی تأیید شد")
        return Response(_approval_dict(a), status=201)


class ApprovalRevokeView(PanelView):
    def post(self, request, pk):
        a = SmsCampaignApproval.objects.filter(pk=pk).first()
        if a is None:
            raise MobileError("not_found", "پیدا نشد.", 404)
        sms.revoke_campaign(a.ref)
        a.refresh_from_db()
        log_action(request, "campaign.revoke", a.ref, message="تأییدِ کمپین پس گرفته شد")
        return Response(_approval_dict(a))


class ConsentsListView(PanelView):
    def get(self, request):
        rows = MobileCallConsent.objects.select_related("declared_by").order_by("-obtained_at")[:200]
        return Response({"results": [{"number": phone.national(c.number), "normalized": c.number, "granted": c.granted, "active": c.active, "how": c.how,
                                      "obtained_how": c.obtained_how, "obtained_at": c.obtained_at, "revoked_at": c.revoked_at,
                                      "by": c.declared_by.get_username() if c.declared_by else None} for c in rows]})


# ------------------------------------------------------------------ settings

_BOOLS = ["sms_enabled", "forward_incoming_sms", "calls_upload_enabled", "asr_enabled", "otp_ignores_opt_out"]
_INTS = ["max_sms_per_hour", "max_sms_per_day", "max_marketing_per_hour", "claim_batch", "poll_interval_s", "lease_seconds",
         "quiet_start_hour", "quiet_end_hour", "max_audio_mb", "lookup_cache_days", "lookup_min_refresh_minutes",
         "lookup_per_device_hour", "lookup_per_device_day", "lookup_per_platform_day", "lookup_manual_per_user_day",
         "lookup_burst_numbers_per_hour"]


def _settings_full(s: MobileSettings) -> dict:
    out = {k: getattr(s, k) for k in _BOOLS + _INTS}
    out["default_store"] = s.default_store_id
    out["lookup_platforms"] = {k: s.platform_enabled(k) for k in LOOKUP_PLATFORMS}
    out["lookup_labels"] = lookups.LABELS
    out["lookup_methods"] = {k: ("server" if k in lookups.SERVER_PLATFORMS else "webview") for k in LOOKUP_PLATFORMS}
    out["lookup_warning"] = lookups.WARNING
    out["lookup_rules"] = lookups.RULES
    return out


class SettingsView(PanelView):
    def get(self, request):
        return Response(_settings_full(MobileSettings.get()))

    def patch(self, request):
        s, data, changed = MobileSettings.get(), request.data, {}
        for k in _BOOLS:
            if k in data:
                setattr(s, k, bool(data[k]))
                changed[k] = bool(data[k])
        for k in _INTS:
            if k in data:
                try:
                    v = int(data[k])
                except (TypeError, ValueError):
                    raise MobileError("invalid", f"{k} باید عدد باشد.", 400)
                if v < 0 or v > 100000:
                    raise MobileError("invalid", f"{k} خارج از بازه است.", 400)
                setattr(s, k, v)
                changed[k] = v
        if "default_store" in data:
            s.default_store_id = int(data["default_store"]) if str(data["default_store"] or "").isdigit() else None
            changed["default_store"] = s.default_store_id
        if isinstance(data.get("lookup_platforms"), dict):
            plat = dict(s.lookup_platforms or {})
            for k, v in data["lookup_platforms"].items():
                if k in LOOKUP_PLATFORMS:
                    plat[k] = bool(v)
            s.lookup_platforms = plat
            changed["lookup_platforms"] = plat
        s.save()
        log_action(request, "settings.edit", "", changed, message="تنظیماتِ موبایل تغییر کرد")
        return Response(_settings_full(s))


# ------------------------------------------------------------------ products / prices

class AdminProductsView(PanelView):
    def get(self, request):
        q = request.query_params.get("q") or ""
        limit, _ = _limit(request, 30, 100)
        from apps.products.models import Product

        if q.strip():
            rows = products.search(request.user, q, limit)
        else:
            qs = Product.objects.filter(store__in=products.scope_stores(request.user)).select_related("store", "mobile_pricing") \
                .prefetch_related("images", "attributes", "variants")[:limit]
            rows = [products.serialize(p) for p in qs]
        for r in rows:
            pr = ProductPricing.objects.filter(product_id=r["id"]).first()
            r["pricing"] = {"extra_unit_cost": _n(pr.extra_unit_cost) if pr else None, "min_margin_percent": _n(pr.min_margin_percent) if pr else None,
                            "floor_price_override": _n(pr.floor_price_override) if pr else None, "note": pr.note if pr else ""}
        return Response({"count": len(rows), "results": rows})


def _n(v):
    return None if v is None else (int(v) if v == v.to_integral_value() else float(v))


class ProductPricingView(PanelView):
    def patch(self, request, pk):
        from apps.products.models import Product

        product = Product.objects.filter(pk=pk, store__in=products.scope_stores(request.user)).select_related("store").first()
        if product is None:
            raise MobileError("not_found", "محصول پیدا نشد.", 404)
        try:
            out = products.set_pricing(request.user, product, request.data)
        except ValueError as exc:
            raise MobileError("invalid", str(exc), 400)
        log_action(request, "product.pricing", str(product.pk), {k: request.data.get(k) for k in request.data if k != "note"},
                   message=f"قیمت‌های «{product.name}» ویرایش شد")
        return Response(out)


# ------------------------------------------------------------------ lookups (panel)

class AdminLookupsView(PanelView):
    def get(self, request):
        number = request.query_params.get("number")
        if number:
            return Response({"results": lookups.timeline(number, request.query_params.get("platform"), 100)})
        rows = ProfileLookup.objects.order_by("-looked_up_at")[:100]
        return Response({"results": [lookups.profile_dict(r) for r in rows]})


class TelegramAdminView(PanelView):
    """Link the owner's own Telegram account: api_id/api_hash -> phone -> code -> (2FA password). Nothing secret is ever echoed."""

    def get(self, request):
        return Response(telegram_provider.status())

    def post(self, request):
        action, d = str(request.data.get("action") or ""), request.data
        try:
            if action == "save_api":
                telegram_provider.save_api(d.get("api_id"), d.get("api_hash"))
            elif action == "send_code":
                telegram_provider.start(d.get("phone"))
            elif action == "code":
                telegram_provider.confirm_code(d.get("code"))
            elif action == "password":
                telegram_provider.confirm_password(d.get("password"))
            elif action == "unlink":
                telegram_provider.unlink()
            else:
                raise MobileError("unknown_action", "اقدامِ ناشناخته.", 400)
        except telegram_provider.ProviderError as exc:
            log_action(request, f"telegram.{action}", "", ok=False, message=str(exc))
            raise MobileError(exc.code, str(exc), 400)
        log_action(request, f"telegram.{action}", "", message="انجام شد")
        return Response(telegram_provider.status())


class ActionLogView(PanelView):
    def get(self, request):
        limit, offset = _limit(request, 50, 200)
        qs = MobileActionLog.objects.select_related("user", "device")
        if request.query_params.get("action"):
            qs = qs.filter(action__startswith=request.query_params["action"])
        return Response({"count": qs.count(), "results": [{
            "at": r.created_at, "user": r.user.get_username() if r.user else None, "device": r.device.name if r.device else None,
            "action": r.action, "target": r.target, "ok": r.ok, "message": r.message, "ip": r.ip} for r in qs[offset:offset + limit]]})

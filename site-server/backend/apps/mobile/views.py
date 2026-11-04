"""The mobile API (/api/v1/mobile/…): endpoints used by the phone (device token) and, where noted, by the panel (staff login)."""
from __future__ import annotations

import logging
import os

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import assistant_facts, callerid, calls, lookups, monitor, phone, products, sms
from .base import (IsDevice, MobileAPIView, MobileError, PairThrottle, client_ip, log_action, require_fields)
from .models import (MobileActionLog, MobileCall, MobileContact, MobileDevice, MobileSettings, SmsMessage, hash_token,
                     new_device_token)

logger = logging.getLogger(__name__)
API_VERSION = 1


def _limit(request, default=30, cap=100):
    try:
        limit = max(1, min(int(request.query_params.get("limit") or default), cap))
        offset = max(0, int(request.query_params.get("offset") or 0))
    except (TypeError, ValueError):
        limit, offset = default, 0
    return limit, offset


def settings_payload(s: MobileSettings) -> dict:
    return {
        "sms_enabled": s.sms_enabled, "forward_incoming_sms": s.forward_incoming_sms,
        "calls_upload_enabled": s.calls_upload_enabled, "asr_enabled": s.asr_enabled,
        "max_sms_per_hour": s.max_sms_per_hour, "max_sms_per_day": s.max_sms_per_day,
        "claim_batch": s.claim_batch, "poll_interval_s": s.poll_interval_s,
    }


def device_dict(d: MobileDevice) -> dict:
    return {"uid": str(d.uid), "name": d.name, "model": d.model, "android_version": d.android_version, "app_version": d.app_version,
            "created_at": d.created_at, "last_seen_at": d.last_seen_at, "sms_enabled": d.sms_enabled,
            "user": {"id": d.user_id, "username": d.user.get_username()}}


def user_dict(u) -> dict:
    return {"id": u.pk, "username": u.get_username(), "display_name": u.get_full_name() or u.get_username()}


# ------------------------------------------------------------------ pairing

class PairView(MobileAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PairThrottle]

    def post(self, request):
        data = request.data
        require_fields(data, "username", "password", "device_name", "install_id")
        username = str(data["username"]).strip()
        ip = client_ip(request) or "?"
        lock_key = f"mobile:pairfail:{username.lower()}:{ip}"
        if cache.get(lock_key, 0) >= 8:
            raise MobileError("too_many_attempts", "تلاش‌های ناموفق زیاد بود؛ ۱۵ دقیقه بعد دوباره.", 429, {"Retry-After": "900"})
        user = authenticate(request=request, username=username, password=str(data["password"]))
        if user is None:
            cache.set(lock_key, cache.get(lock_key, 0) + 1, 900)
            raise MobileError("bad_credentials", "نام کاربری یا رمز درست نیست.", 401)
        if not (user.is_active and user.is_staff):
            raise MobileError("not_staff", "این حساب کارمند نیست؛ فقط کارمندان می‌توانند گوشی را وصل کنند.", 403)
        cache.delete(lock_key)
        token = new_device_token()
        install_id = str(data["install_id"]).strip()[:64]
        device = MobileDevice.objects.filter(install_id=install_id).first()
        fields = dict(user=user, name=str(data["device_name"]).strip()[:120], model=str(data.get("model") or "")[:120],
                      android_version=str(data.get("android_version") or "")[:20], app_version=str(data.get("app_version") or "")[:30],
                      token_hash=hash_token(token), token_prefix=token[:8], revoked_at=None, revoked_by=None,
                      last_seen_at=timezone.now(), last_ip=ip if ip != "?" else None)
        if device is None:
            device = MobileDevice.objects.create(install_id=install_id, **fields)
        else:
            for k, v in fields.items():
                setattr(device, k, v)
            device.save()
        log_action(request, "device.pair", str(device.uid), {"name": device.name, "model": device.model}, device=device, user=user,
                   message=f"گوشیِ «{device.name}» جفت شد")
        return Response({"device_token": token, "device": device_dict(device), "user": user_dict(user),
                         "server": {"api_version": API_VERSION, "time": timezone.now()},
                         "settings": settings_payload(MobileSettings.get())}, status=201)


class MeView(MobileAPIView):
    permission_classes = [IsDevice]

    def get(self, request):
        s = MobileSettings.get()
        use = sms.usage(self.device, s)
        return Response({"device": device_dict(self.device), "user": user_dict(request.user), "server_time": timezone.now(),
                         "settings": settings_payload(s),
                         "sms": {k: use[k] for k in ("sent_last_hour", "remaining_hour", "remaining_day", "queued_total")}})


class HeartbeatView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        d, data = self.device, request.data
        batt = data.get("battery_percent")
        d.battery_percent = batt if isinstance(batt, int) and 0 <= batt <= 100 else None
        d.charging = data.get("charging") if isinstance(data.get("charging"), bool) else None
        d.network = str(data.get("network") or "")[:12]
        d.sims = data.get("sims") if isinstance(data.get("sims"), list) else d.sims
        d.sms_ready = data.get("sms_ready") if isinstance(data.get("sms_ready"), bool) else None
        if data.get("app_version"):
            d.app_version = str(data["app_version"])[:30]
        d.heartbeat_at = timezone.now()
        d.save()
        s = MobileSettings.get()
        return Response({"ok": True, "server_time": timezone.now(), "settings": settings_payload(s),
                         "pending_sms": SmsMessage.objects.filter(state=SmsMessage.State.QUEUED).count()})


class UnpairView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        d = self.device
        d.revoked_at, d.revoked_by = timezone.now(), request.user
        d.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
        log_action(request, "device.unpair", str(d.uid), message="گوشی خودش را جدا کرد", device=d)
        return Response({"ok": True})


# ------------------------------------------------------------------ monitoring

class MonitorSummaryView(MobileAPIView):
    def get(self, request):
        return Response(monitor.summary())


class MonitorActionsView(MobileAPIView):
    def get(self, request):
        limit, offset = _limit(request)
        qs = MobileActionLog.objects.select_related("user", "device")
        rows = qs[offset:offset + limit]
        return Response({"count": qs.count(), "results": [{
            "at": r.created_at, "user": r.user.get_username() if r.user else None, "device": r.device.name if r.device else None,
            "action": r.action, "target": r.target, "ok": r.ok, "message": r.message} for r in rows]})

    def post(self, request):
        require_fields(request.data, "action")
        return Response(monitor.run_action(request, str(request.data["action"]), request.data.get("target"), request.data.get("params")))


# ------------------------------------------------------------------ SMS

class SmsClaimView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        data = request.data
        try:
            max_n = int(data["max"]) if data.get("max") not in (None, "") else None
            slot = int(data["sim_slot"]) if data.get("sim_slot") not in (None, "") else None
        except (TypeError, ValueError):
            raise MobileError("invalid", "max و sim_slot باید عدد باشند.", 400)
        return Response(sms.claim(self.device, max_n, slot))


class SmsReportView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request, uid):
        msg = SmsMessage.objects.filter(uid=uid).first()
        if msg is None:
            raise MobileError("not_found", "پیامک پیدا نشد.", 404)
        data = request.data
        msg = sms.report(self.device, msg, data.get("state"), data.get("error_code") or "", data.get("error") or "",
                         calls.parse_time(data.get("at")) if data.get("at") else None, data.get("parts"))
        return Response({"ok": True, "state": msg.state})


class SmsIncomingView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        items = request.data.get("messages")
        if not isinstance(items, list):
            raise MobileError("invalid", "messages باید فهرست باشد.", 400)
        return Response(sms.ingest_incoming(self.device, items))


class OptOutsFeedView(MobileAPIView):
    """The global «never message again» list, for the phone's own local campaigns (cursor = created time)."""

    permission_classes = [IsDevice]

    def get(self, request):
        from .models import SmsOptOut

        try:
            limit = max(1, min(int(request.query_params.get("limit") or 500), 500))
        except (TypeError, ValueError):
            limit = 500
        since_raw = request.query_params.get("since") or ""
        qs = SmsOptOut.objects.order_by("created_at", "id")
        since = calls.parse_time(since_raw, default=None) if since_raw else None
        if since_raw and since is not None:
            qs = qs.filter(created_at__gt=since)
        rows = list(qs[:limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = rows[-1].created_at if rows else (since or None)
        return Response({"numbers": [r.number for r in rows], "next_since": nxt.isoformat() if nxt else None, "has_more": more})


def sms_dict(m: SmsMessage) -> dict:
    return {"uid": str(m.uid), "to": m.to_raw or phone.national(m.to_number), "normalized": m.to_number, "body": m.body, "kind": m.kind,
            "campaign_ref": m.campaign_ref, "state": m.state, "state_label": m.get_state_display(), "attempts": m.attempts,
            "device": m.device.name if m.device else None, "created_at": m.created_at, "sent_at": m.sent_at,
            "delivered_at": m.delivered_at, "error": m.error, "error_code": m.error_code}


class SmsQueueView(MobileAPIView):
    """Staff (panel / other NM apps): queue an SMS, list the queue. The phone itself does not call this."""

    def _panel_only(self):
        if self.device is not None:
            raise MobileError("panel_only", "این بخش از پنل است، نه از گوشی.", 403)

    def get(self, request):
        limit, offset = _limit(request)
        qs = SmsMessage.objects.select_related("device")
        if request.query_params.get("state"):
            qs = qs.filter(state=request.query_params["state"].upper())
        q = phone.ascii_digits(request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(to_number__contains=phone.key(q) or q)
        return Response({"count": qs.count(), "results": [sms_dict(m) for m in qs[offset:offset + limit]]})

    def post(self, request):
        self._panel_only()
        data = request.data
        require_fields(data, "to", "body")
        key = request.headers.get("Idempotency-Key") or data.get("idempotency_key") or ""
        nb = calls.parse_time(data.get("not_before")) if data.get("not_before") else None
        try:
            msg, created = sms.enqueue(data["to"], data["body"], str(data.get("kind") or "transactional").lower(),
                                       str(data.get("campaign_ref") or ""), str(key), request.user, nb)
        except sms.OptedOut as exc:
            log_action(request, "sms.queue", str(exc.sms.uid), {"to": exc.sms.to_number}, ok=False, message="opted_out")
            return Response({"error": {"code": "opted_out", "message": exc.message}, "uid": str(exc.sms.uid)}, status=409)
        if created:
            log_action(request, "sms.queue", str(msg.uid), {"kind": msg.kind, "campaign_ref": msg.campaign_ref}, message="در صف گذاشته شد")
        return Response({"uid": str(msg.uid), "state": msg.state, "deduped": not created}, status=201 if created else 200)


# ------------------------------------------------------------------ calls

class CallsLogView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        entries = request.data.get("calls")
        if not isinstance(entries, list):
            raise MobileError("invalid", "calls باید فهرست باشد.", 400)
        return Response({"results": calls.log_calls(self.device, entries)})


class CallsLiveView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        data = request.data
        require_fields(data, "number")
        call, created = calls.register_live(self.device, data["number"], data.get("direction") or "in", data.get("started_at"),
                                            data.get("client_id") or "")
        return Response({"uid": str(call.uid), "created": created, "normalized": call.number,
                         "caller": {"display": call.caller_label or None, "known": bool(call.caller_label)}}, status=201 if created else 200)


class CallsListView(MobileAPIView):
    def get(self, request):
        limit, offset = _limit(request)
        qs = MobileCall.objects.all()
        number = request.query_params.get("number")
        if number:
            qs = qs.filter(number=phone.normalize(number))
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"].upper())
        if self.device is not None and request.query_params.get("mine") == "1":
            qs = qs.filter(device=self.device)
        return Response({"count": qs.count(), "results": [calls.call_dict(c) for c in qs[offset:offset + limit]]})


def _call_or_404(uid) -> MobileCall:
    try:
        c = MobileCall.objects.filter(uid=uid).first()
    except Exception:  # noqa: BLE001
        c = None
    if c is None:
        raise MobileError("not_found", "تماس پیدا نشد.", 404)
    return c


class CallDetailView(MobileAPIView):
    def get(self, request, uid):
        c = _call_or_404(uid)
        data = calls.call_dict(c, detail=True)
        data["profiles"] = lookups.latest_profiles(c.number)
        data["consent"] = calls.consent_state(c.number)
        return Response(data)


class CallAudioView(MobileAPIView):
    def get(self, request, uid):
        c = _call_or_404(uid)
        path = calls.audio_file(c)
        if path is None:
            raise MobileError("not_found", "برای این تماس فایلی نیست.", 404)
        resp = FileResponse(open(path, "rb"), content_type=c.audio_mime or "application/octet-stream")
        resp["Content-Disposition"] = f'inline; filename="call-{c.uid}{os.path.splitext(path.name)[1]}"'
        resp["Cache-Control"] = "private, no-store"
        log_action(request, "call.audio", str(c.uid), message="شنیدن/دانلودِ ضبط")
        return resp


class CallRecordingView(MobileAPIView):
    permission_classes = [IsDevice]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, uid):
        c = _call_or_404(uid)
        upload = request.FILES.get("audio")
        if upload is None:
            raise MobileError("missing_fields", "فایلِ audio لازم است.", 400)
        calls.save_recording(c, upload, request.data.get("source") or "builtin_recorder", request.data.get("duration_s"))
        _dispatch_processing(c)
        return Response({"uid": str(c.uid), "status": c.status}, status=201)


def _dispatch_processing(call: MobileCall):
    from . import tasks

    try:
        tasks.process_call.delay(call.pk)
    except Exception:  # noqa: BLE001 - broker down: say so on the row instead of silently stalling
        logger.exception("could not queue call processing")
        call.error = "صفِ پردازش در دسترس نبود؛ «پردازش دوباره» را بزنید."
        call.save(update_fields=["error", "updated_at"])


class CallReprocessView(MobileAPIView):
    def post(self, request, uid):
        c = _call_or_404(uid)
        if not c.audio_path:
            raise MobileError("bad_state", "این تماس فایلِ صدا ندارد.", 409)
        c.status, c.error = MobileCall.Status.UPLOADED, ""
        c.save(update_fields=["status", "error", "updated_at"])
        _dispatch_processing(c)
        log_action(request, "call.reprocess", str(c.uid))
        return Response({"ok": True}, status=202)


class ConsentView(MobileAPIView):
    def get(self, request):
        number = request.query_params.get("number") or ""
        if not phone.is_valid(phone.normalize(number)):
            raise MobileError("bad_number", "شماره درست نیست.", 400)
        return Response(calls.consent_state(number))

    def post(self, request):
        data = request.data
        require_fields(data, "number")
        row = calls.grant_consent(data["number"], data.get("how"), data.get("obtained_how"), request.user, self.device)
        log_action(request, "consent.grant", row.number, {"how": row.how}, message="رضایتِ ضبط ثبت شد")
        return Response(calls.consent_state(data["number"]))


class ConsentRevokeView(MobileAPIView):
    def post(self, request):
        require_fields(request.data, "number")
        calls.revoke_consent(request.data["number"])
        log_action(request, "consent.revoke", phone.normalize(request.data["number"]), message="رضایتِ ضبط پس گرفته شد")
        return Response(calls.consent_state(request.data["number"]))


# ------------------------------------------------------------------ helpers for the call screen

class ProductSearchView(MobileAPIView):
    def get(self, request):
        q = request.query_params.get("q") or ""
        limit, _ = _limit(request, 20, 50)
        results = products.search(request.user, q, limit) if q.strip() else []
        return Response({"count": len(results), "results": results})


class CallerIdView(MobileAPIView):
    def get(self, request):
        number = request.query_params.get("number") or ""
        if not phone.is_valid(phone.normalize(number)):
            raise MobileError("bad_number", "شماره درست نیست.", 400)
        data = callerid.lookup(request.user, number)
        data["profiles"] = lookups.latest_profiles(number)
        data["consent"] = {"granted": calls.consent_state(number)["granted"]}
        for m in data["matches"]:
            m["last_contact_at"] = m.get("last_contact_at")
        return Response(data)


class AssistantAskView(MobileAPIView):
    def post(self, request):
        from . import notes

        data = request.data
        require_fields(data, "question")
        facts = assistant_facts.build(request.user, data.get("number"), data.get("product_ids"), data.get("call_uid"))
        try:
            out = notes.quick_replies(request.user, str(data["question"])[:1000], facts)
        except notes.NotesUnavailable as exc:
            raise MobileError("ai_unavailable", f"دستیار الان در دسترس نیست: {exc}", 503)
        out["facts_used"] = facts.get("summary_for_user", {})
        log_action(request, "assistant.ask", "", {"products": len(facts.get("products", []))}, message="پرسش از دستیار")
        return Response(out)


class ContactsSyncView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        items = request.data.get("contacts")
        if not isinstance(items, list):
            raise MobileError("invalid", "contacts باید فهرست باشد.", 400)
        if request.data.get("replace", True):
            MobileContact.objects.filter(device=self.device).delete()
        rows = {}
        for it in items[:5000]:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()[:200]
            for n in (it.get("numbers") or [])[:5]:
                norm = phone.normalize(n)
                if phone.is_valid(norm) and name:
                    rows.setdefault(norm, MobileContact(device=self.device, name=name, number=norm))
        MobileContact.objects.bulk_create(list(rows.values()), ignore_conflicts=True)
        return Response({"count": MobileContact.objects.filter(device=self.device).count()})

    def delete(self, request):
        n, _ = MobileContact.objects.filter(device=self.device).delete()
        return Response({"count": 0, "deleted": n})


# ------------------------------------------------------------------ messenger lookups

class LookupConfigView(MobileAPIView):
    def get(self, request):
        return Response(lookups.config_for(self.device))


class LookupAuthorizeView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        d = request.data
        require_fields(d, "number", "platform", "trigger")
        out = lookups.authorize(request.user, self.device, d["number"], d["platform"], d["trigger"], d.get("call_uid"),
                                bool(d.get("refresh")))
        log_action(request, "lookup.authorize", phone.normalize(d["number"]), {"platform": d["platform"], "trigger": d["trigger"]},
                   ok=bool(out.get("allowed")), message="مجوزِ جستجو" if out.get("allowed") else "نتیجهٔ ذخیره‌شده")
        return Response(out)


class LookupListView(MobileAPIView):
    def post(self, request):
        """The phone submits what it read in a messenger WebView (needs a ticket from `authorize`)."""
        if self.device is None:
            raise MobileError("device_only", "این درخواست فقط از گوشیِ جفت‌شده انجام می‌شود.", 403)
        row = lookups.submit(self.device, request.data)
        log_action(request, "lookup.submit", row.number, {"platform": row.platform, "status": row.status}, message=row.status)
        return Response(lookups.profile_dict(row), status=201)

    def get(self, request):
        number = request.query_params.get("number") or ""
        if not phone.is_valid(phone.normalize(number)):
            raise MobileError("bad_number", "شماره درست نیست.", 400)
        res = lookups.timeline(number, request.query_params.get("platform"), request.query_params.get("limit") or 50)
        return Response({"count": len(res), "results": res})


class LookupLatestView(MobileAPIView):
    def get(self, request):
        number = request.query_params.get("number") or ""
        if not phone.is_valid(phone.normalize(number)):
            raise MobileError("bad_number", "شماره درست نیست.", 400)
        return Response({"number": number, "normalized": phone.normalize(number), "profiles": lookups.latest_profiles(number)})


class LookupServerView(MobileAPIView):
    permission_classes = [IsDevice]

    def post(self, request):
        require_fields(request.data, "ticket")
        row = lookups.run_server(self.device, request.data["ticket"])
        log_action(request, "lookup.server", row.number, {"platform": row.platform, "status": row.status}, message=row.status)
        return Response(lookups.profile_dict(row), status=201)


class LookupAvatarView(MobileAPIView):
    def get(self, request, uid):
        from .models import ProfileLookup

        row = ProfileLookup.objects.filter(uid=uid).first()
        path = lookups.avatar_file(row) if row else None
        if path is None:
            raise Http404("no avatar")
        ctype = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix, "application/octet-stream")
        resp = FileResponse(open(path, "rb"), content_type=ctype)
        resp["Cache-Control"] = "private, max-age=3600"
        return resp

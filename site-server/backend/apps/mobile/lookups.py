"""Messenger profile lookup for CALLER IDENTIFICATION (owner-approved, tightly scoped).

Guardrails enforced on the server — the phone cannot skip them:
* there is no endpoint that takes several numbers; each lookup is `authorize` (one number, one platform) -> single-use
  ticket -> result;
* `trigger=call`: the number must belong to a call of THIS paired phone from the last 24 h (live-registered or in the call log);
  `trigger=manual`: one number typed by a staff user, with a daily quota; no ticket is issued for «a list»;
* per-platform on/off switch (default OFF) in the panel; per device / hour, device / day, platform / day, manual / user / day;
* «bulk» detector: many DIFFERENT numbers from one device within an hour are refused;
* results cached for N days (30); refresh only after a pause, and not more than a few times per call;
* only what a normal user of the platform sees is stored: display name, username, photo, bio, «is on the platform».
The messenger logins stay on the owner's own phone (WebViews) / on the Telegram session the owner linked; NM never receives
a messenger password or cookie.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import secrets
from datetime import timedelta

from django.utils import timezone

from . import calls as calls_service
from . import phone
from .base import MobileError
from .models import (LOOKUP_PLATFORMS, LookupTicket, MobileCall, MobileDevice, MobileSettings, ProfileLookup)

logger = logging.getLogger(__name__)

LABELS = {"telegram": "تلگرام", "whatsapp": "واتساپ", "eitaa": "ایتا", "bale": "بله", "soroush": "سروش", "rubika": "روبیکا"}
SERVER_PLATFORMS = {"telegram"}
WARNING = ("این روش غیررسمی است و ممکن است حسابِ همان پیام‌رسان را محدود یا مسدود کند؛ فقط با حسابِ خودتان و با احتیاط روشن کنید."
           )
WARNING_OFFICIAL = ("از راهِ رسمیِ تلگرام (MTProto) با حسابی که خودتان وصل کرده‌اید انجام می‌شود؛ باز هم تلگرام ممکن است "
                    "در صورتِ تعدادِ زیاد جستجو محدودیتِ موقت بگذارد.")
RULES = ("فقط برای شناساییِ تماس‌گیرنده است: شماره‌های تماسِ واقعیِ همین گوشی یا یک جستجوی دستیِ یک کارمند. فهرستِ شماره "
         "جستجو نمی‌شود. فقط آنچه پیام‌رسان به یک کاربرِ عادی نشان می‌دهد (نام، نام‌کاربری، عکس، بیو و «در این پیام‌رسان هست یا نه») "
         "ذخیره می‌شود و نتیجه ۳۰ روز نگه داشته می‌شود. ورود به پیام‌رسان‌ها را خودِ مالک روی گوشیِ خودش انجام می‌دهد.")
TICKET_MINUTES = 10
STATUSES = {s for s, _ in ProfileLookup.Status.choices}
AVATAR_MAX = 300 * 1024
FIELD_KEYS = {"display_name", "username", "bio", "avatar", "on_platform", "deep_link_id"}


def _telegram():
    from . import telegram_provider

    return telegram_provider


# ------------------------------------------------------------------ config

def config_for(device: MobileDevice | None) -> dict:
    s = MobileSettings.get()
    now = timezone.now()
    out = []
    for key in LOOKUP_PLATFORMS:
        server = key in SERVER_PLATFORMS
        enabled = s.platform_enabled(key)
        ready = True
        if server:
            try:
                ready = bool(_telegram().is_ready())
            except Exception:  # noqa: BLE001
                ready = False
        left = None
        if device is not None:
            used = LookupTicket.objects.filter(device=device, created_at__gte=now - timedelta(days=1), refunded=False).count()
            plat = LookupTicket.objects.filter(platform=key, created_at__gte=now - timedelta(days=1), refunded=False).count()
            left = max(0, min(s.lookup_per_device_day - used, s.lookup_per_platform_day - plat))
        out.append({"key": key, "label": LABELS[key], "enabled": enabled, "method": "server" if server else "webview",
                    "ready": bool(enabled and ready), "warning": WARNING_OFFICIAL if server else WARNING, "left_today": left})
    return {"cache_days": s.lookup_cache_days, "platforms": out, "rules": RULES}


# ------------------------------------------------------------------ authorize

def _latest(norm, platform, newer_than=None):
    qs = ProfileLookup.objects.filter(number=norm, platform=platform,
                                      status__in=[ProfileLookup.Status.FOUND, ProfileLookup.Status.NOT_FOUND, ProfileLookup.Status.HIDDEN])
    if newer_than:
        qs = qs.filter(looked_up_at__gte=newer_than)
    return qs.order_by("-looked_up_at", "-id").first()


def authorize(user, device: MobileDevice, number, platform, trigger, call_uid=None, refresh=False, now=None) -> dict:
    now = now or timezone.now()
    s = MobileSettings.get()
    platform = str(platform or "").lower()
    if platform not in LOOKUP_PLATFORMS:
        raise MobileError("bad_platform", "پیام‌رسانِ نامعتبر.", 400)
    if not user.is_staff:
        raise MobileError("not_staff", "فقط کارمندان.", 403)
    norm = phone.normalize(number)
    if not phone.is_valid(norm):
        raise MobileError("bad_number", "شماره درست نیست.", 400)
    if not s.platform_enabled(platform):
        raise MobileError("platform_disabled", f"جستجو در {LABELS[platform]} از پنل روشن نشده است.", 403)
    trigger = str(trigger or "").lower()
    call = None
    if trigger == "call":
        if not call_uid:
            raise MobileError("no_matching_call", "جستجو فقط برای شمارهٔ یک تماسِ واقعی انجام می‌شود.", 403)
        call = MobileCall.objects.filter(uid=str(call_uid), device=device, number=norm,
                                         created_at__gte=now - timedelta(hours=24)).first() if _is_uuid(call_uid) else None
        if call is None:
            raise MobileError("no_matching_call", "این شماره در تماس‌های امروزِ این گوشی نیست؛ جستجو فقط برای تماسِ واقعی انجام می‌شود.", 403)
    elif trigger == "manual":
        day = LookupTicket.objects.filter(user=user, trigger="manual", created_at__gte=now - timedelta(days=1), refunded=False).count()
        if day >= s.lookup_manual_per_user_day:
            raise MobileError("rate_limited", "سقفِ جستجوی دستیِ امروز پر شده است.", 429, {"Retry-After": "3600"})
    else:
        raise MobileError("bad_trigger", "trigger باید call یا manual باشد.", 400)

    latest = _latest(norm, platform, now - timedelta(days=s.lookup_cache_days))
    if latest and not refresh:
        return {"allowed": False, "reason": "cached", "cached": profile_dict(latest, now)}
    if refresh and latest and latest.looked_up_at > now - timedelta(minutes=s.lookup_min_refresh_minutes):
        raise MobileError("recently_refreshed", f"این نتیجه تازه است؛ تازه‌سازی بعد از {s.lookup_min_refresh_minutes} دقیقه ممکن است.", 409)

    live = LookupTicket.objects.filter(refunded=False)
    if call is not None and live.filter(call=call, platform=platform).count() >= 3:
        raise MobileError("rate_limited", "برای این تماس بیش از سه بار در این پیام‌رسان جستجو شده است.", 429, {"Retry-After": "3600"})
    hour_ago, day_ago = now - timedelta(hours=1), now - timedelta(days=1)
    dev_hour = live.filter(device=device, created_at__gte=hour_ago)
    distinct = dev_hour.exclude(number=norm).values("number").distinct().count()
    if distinct >= s.lookup_burst_numbers_per_hour:
        raise MobileError("bulk_blocked", "شماره‌های متفاوتِ زیادی در یک ساعت از این گوشی جستجو شده؛ این شبیه جستجوی فهرستی است و مسدود شد.", 429,
                          {"Retry-After": "3600"})
    if dev_hour.count() >= s.lookup_per_device_hour:
        raise MobileError("rate_limited", "سقفِ جستجو در ساعت برای این گوشی پر شده است.", 429, {"Retry-After": "900"})
    if live.filter(device=device, created_at__gte=day_ago).count() >= s.lookup_per_device_day:
        raise MobileError("rate_limited", "سقفِ جستجو در روز برای این گوشی پر شده است.", 429, {"Retry-After": "3600"})
    if live.filter(platform=platform, created_at__gte=day_ago).count() >= s.lookup_per_platform_day:
        raise MobileError("rate_limited", f"سقفِ جستجوی روزانه در {LABELS[platform]} پر شده است.", 429, {"Retry-After": "3600"})
    method = "server" if platform in SERVER_PLATFORMS else "webview"
    if method == "server":
        try:
            ready = bool(_telegram().is_ready())
        except Exception:  # noqa: BLE001
            ready = False
        if not ready:
            raise MobileError("platform_not_ready", "حسابِ تلگرام هنوز در پنل وصل نشده است.", 503)
    ticket = LookupTicket.objects.create(
        token=secrets.token_urlsafe(24), device=device, user=user, number=norm, platform=platform, trigger=trigger, call=call,
        refresh=bool(refresh), method=method, expires_at=now + timedelta(minutes=TICKET_MINUTES))
    return {"allowed": True, "ticket": ticket.token, "method": method, "normalized": norm, "expires_in": TICKET_MINUTES * 60}


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


# ------------------------------------------------------------------ submit

def _take_ticket(device: MobileDevice, token, now) -> LookupTicket:
    t = LookupTicket.objects.filter(token=str(token or ""), device=device).first()
    if t is None:
        raise MobileError("bad_ticket", "این مجوزِ جستجو معتبر نیست.", 403)
    if t.used_at is not None:
        raise MobileError("ticket_used", "این مجوز قبلاً استفاده شده است.", 409)
    if t.expires_at <= now:
        raise MobileError("ticket_expired", "مجوزِ جستجو منقضی شده؛ دوباره درخواست کنید.", 410)
    used = LookupTicket.objects.filter(pk=t.pk, used_at__isnull=True).update(used_at=now)
    if not used:
        raise MobileError("ticket_used", "این مجوز قبلاً استفاده شده است.", 409)
    t.used_at = now
    return t


def _clip(value, n):
    return str(value).strip()[:n] if value not in (None, "") else ""


def _safe_extra(extra) -> dict:
    if not isinstance(extra, dict):
        return {}
    out = {}
    for k, v in list(extra.items())[:12]:
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)[:40]] = v if not isinstance(v, str) else v[:200]
    return out if len(json.dumps(out, ensure_ascii=False)) <= 2000 else {}


def _save_avatar(uid, b64, platform) -> str:
    if not b64:
        return ""
    try:
        raw = base64.b64decode(str(b64).split(",")[-1], validate=False)
    except (binascii.Error, ValueError):
        return ""
    if not raw or len(raw) > AVATAR_MAX:
        return ""
    if raw[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif raw[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ext = ".webp"
    else:
        return ""
    rel = f"avatars/{platform}/{uid}{ext}"
    target = calls_service.data_dir() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return rel


def _record(ticket: LookupTicket, status, on_platform, display_name, username, bio, deep_link_id, avatar_b64, extra, sources, error,
            now) -> ProfileLookup:
    row = ProfileLookup(number=ticket.number, platform=ticket.platform, method=ticket.method, status=status, on_platform=on_platform,
                        display_name=_clip(display_name, 200), username=_clip(username, 100).lstrip("@"), bio=_clip(bio, 1000),
                        deep_link_id=_clip(deep_link_id, 120), extra=_safe_extra(extra), error=_clip(error, 300),
                        looked_up_at=now, device=ticket.device, user=ticket.user, trigger=ticket.trigger, call=ticket.call,
                        refresh=ticket.refresh)
    if isinstance(sources, dict):
        row.field_sources = {k: _clip(v, 100) for k, v in sources.items() if k in FIELD_KEYS and v}
    row.save()
    path = _save_avatar(row.uid, avatar_b64, ticket.platform)
    if path:
        row.avatar_path = path
        row.save(update_fields=["avatar_path"])
    return row


def submit(device: MobileDevice, payload: dict, now=None) -> ProfileLookup:
    now = now or timezone.now()
    ticket = _take_ticket(device, payload.get("ticket"), now)
    if ticket.method != "webview":
        raise MobileError("wrong_method", "این پیام‌رسان را سرور انجام می‌دهد، نه گوشی.", 400)
    status = str(payload.get("status") or "").lower()
    if status not in STATUSES:
        raise MobileError("bad_status", "وضعیتِ نتیجه نامعتبر است.", 400)
    if status == ProfileLookup.Status.LOGIN_REQUIRED:
        LookupTicket.objects.filter(pk=ticket.pk).update(refunded=True)     # does not count against the quota
    on_platform = payload.get("on_platform")
    on_platform = on_platform if isinstance(on_platform, bool) else None
    if status == ProfileLookup.Status.NOT_FOUND:
        on_platform = False
    return _record(ticket, status, on_platform, payload.get("display_name"), payload.get("username"), payload.get("bio"),
                   payload.get("deep_link_id"), payload.get("avatar_b64"), payload.get("extra"), payload.get("field_sources"),
                   payload.get("error"), now)


def run_server(device: MobileDevice, token, now=None) -> ProfileLookup:
    now = now or timezone.now()
    ticket = _take_ticket(device, token, now)
    if ticket.method != "server":
        raise MobileError("wrong_method", "این پیام‌رسان را خودِ گوشی انجام می‌دهد.", 400)
    provider = _telegram()
    try:
        result = provider.lookup(ticket.number)
    except provider.ProviderError as exc:
        if exc.refund:
            LookupTicket.objects.filter(pk=ticket.pk).update(refunded=True)
        raise MobileError(exc.code, str(exc), 503) from exc
    return _record(ticket, result.get("status", "error"), result.get("on_platform"), result.get("display_name"), result.get("username"),
                   result.get("bio"), result.get("deep_link_id"), result.get("avatar_b64"), result.get("extra"),
                   result.get("field_sources"), result.get("error"), now)


# ------------------------------------------------------------------ read

def profile_dict(row: ProfileLookup, now=None) -> dict:
    now = now or timezone.now()
    age = max(0, (now - row.looked_up_at).days)
    s = MobileSettings.get()
    return {
        "uid": str(row.uid), "number": phone.national(row.number), "normalized": row.number, "platform": row.platform,
        "label": LABELS.get(row.platform, row.platform), "method": row.method, "status": row.status, "on_platform": row.on_platform,
        "display_name": row.display_name or None, "username": row.username or None, "bio": row.bio or None,
        "deep_link_id": row.deep_link_id or None,
        "avatar_url": f"/api/v1/mobile/lookups/{row.uid}/avatar/" if row.avatar_path else None,
        "field_sources": row.field_sources or {}, "looked_up_at": row.looked_up_at, "age_days": age,
        "stale": age >= s.lookup_cache_days, "trigger": row.trigger,
    }


def latest_profiles(number, now=None) -> list[dict]:
    norm = phone.normalize(number)
    out = []
    for key in LOOKUP_PLATFORMS:
        row = ProfileLookup.objects.filter(number=norm, platform=key).exclude(status=ProfileLookup.Status.LOGIN_REQUIRED) \
            .order_by("-looked_up_at", "-id").first()
        if row:
            out.append(profile_dict(row, now))
    return out


def timeline(number, platform=None, limit=50) -> list[dict]:
    qs = ProfileLookup.objects.filter(number=phone.normalize(number))
    if platform:
        qs = qs.filter(platform=platform)
    return [profile_dict(r) for r in qs.order_by("-looked_up_at", "-id")[:max(1, min(int(limit), 100))]]


def avatar_file(row: ProfileLookup):
    if not row.avatar_path:
        return None
    base = calls_service.data_dir().resolve()
    p = (base / row.avatar_path).resolve()
    return p if base in p.parents and p.is_file() else None

"""Calls: live registration, call-log upload, consent, recordings.

NM's rule (the same one the existing «بازاریابی تلفنی» module enforces): **no consent row, no stored recording.**
Call-log METADATA (number, time, duration) is kept without a recording; audio is refused until the marketer
has declared that the other person was told and agreed.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings as dj_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import callerid, phone
from .base import MobileError
from .models import MobileCall, MobileCallConsent, MobileDevice, MobileSettings

logger = logging.getLogger(__name__)

ALLOWED_EXT = {".m4a", ".aac", ".mp3", ".wav", ".amr", ".3gp", ".ogg", ".opus", ".flac", ".mp4", ".webm", ".awb"}
DIRECTIONS = {"in", "out", "missed", "rejected"}


def data_dir() -> Path:
    base = Path(getattr(dj_settings, "NM_DATA_DIR", Path(dj_settings.BASE_DIR) / "data")) / "mobile"
    base.mkdir(parents=True, exist_ok=True)
    return base


def parse_time(value, default=None):
    if not value:
        return default or timezone.now()
    dt = parse_datetime(str(value))
    if dt is None:
        return default or timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


# ------------------------------------------------------------------ registration

def _reconcile(device, norm, started_at, direction):
    """A live-registered call (no client_id yet) that this call-log row is the final version of."""
    window = timedelta(minutes=5)
    return (MobileCall.objects.filter(device=device, number=norm, client_id="", started_at__gte=started_at - window,
                                      started_at__lte=started_at + window).order_by("-started_at").first())


def _label(user, norm) -> str:
    try:
        return callerid.display_for(user, norm)
    except Exception:  # noqa: BLE001 - a lookup failure must never lose a call
        logger.exception("callerid failed")
        return ""


def register_live(device: MobileDevice, number, direction="in", started_at=None, client_id="") -> tuple[MobileCall, bool]:
    norm = phone.normalize(number)
    if not phone.is_valid(norm):
        raise MobileError("bad_number", "شمارهٔ تماس درست نیست.", 400)
    direction = direction if direction in ("in", "out") else "in"
    started = parse_time(started_at)
    client_id = str(client_id or "").strip()[:80]
    if client_id:
        existing = MobileCall.objects.filter(device=device, client_id=client_id).first()
        if existing:
            return existing, False
    recent = MobileCall.objects.filter(device=device, number=norm, live=True, started_at__gte=started - timedelta(minutes=2),
                                       started_at__lte=started + timedelta(minutes=2)).first()
    if recent:
        return recent, False                # the phone state changes ring->offhook fire several times
    call = MobileCall.objects.create(device=device, user=device.user, client_id=client_id, number_raw=str(number)[:40], number=norm,
                                     direction=direction, started_at=started, live=True, caller_label=_label(device.user, norm))
    return call, True


def log_calls(device: MobileDevice, entries) -> list[dict]:
    results = []
    for it in (entries or [])[:200]:
        if not isinstance(it, dict):
            continue
        norm = phone.normalize(it.get("number"))
        cid = str(it.get("client_id") or "").strip()[:80]
        if not phone.is_valid(norm) or not cid:
            results.append({"client_id": cid, "uid": None, "created": False, "error": "bad_row"})
            continue
        direction = it.get("direction") if it.get("direction") in DIRECTIONS else "in"
        started = parse_time(it.get("started_at"))
        duration = max(0, int(it.get("duration_s") or 0))
        name = str(it.get("contact_name") or "")[:200]
        call = MobileCall.objects.filter(device=device, client_id=cid).first()
        created = False
        if call is None:
            call = _reconcile(device, norm, started, direction)
            if call is not None:
                call.client_id = cid
            else:
                call = MobileCall(device=device, user=device.user, client_id=cid, number=norm, started_at=started)
                created = True
        call.number_raw = str(it.get("number"))[:40]
        call.number = norm
        call.direction = direction
        call.started_at = started
        call.duration_s = duration
        if name:
            call.contact_name = name
        call.live = False
        if not call.caller_label:
            call.caller_label = _label(device.user, norm)
        call.save()
        results.append({"client_id": cid, "uid": str(call.uid), "created": created,
                        "caller": {"display": call.caller_label or None, "known": bool(call.caller_label)}})
    return results


# ------------------------------------------------------------------ consent

def consent_state(number) -> dict:
    norm = phone.normalize(number)
    row = MobileCallConsent.objects.filter(number=norm).first()
    if row and row.active:
        return {"number": str(number), "normalized": norm, "granted": True, "how": row.how, "obtained_at": row.obtained_at,
                "source": "mobile"}
    prospect = _prospect_consent(norm)
    if prospect:
        return {"number": str(number), "normalized": norm, "granted": True, "how": prospect["how"],
                "obtained_at": prospect["obtained_at"], "source": "prospect"}
    return {"number": str(number), "normalized": norm, "granted": False, "how": None, "obtained_at": None, "source": None}


def _prospect_consent(norm):
    """Consent already recorded in the existing «بازاریابی تلفنی» module for a prospect with this phone."""
    try:
        from apps.customers.calls import CallConsent
    except Exception:  # noqa: BLE001
        return None
    k = phone.key(norm)
    if len(k) < 7:
        return None
    for row in CallConsent.objects.select_related("prospect").filter(granted=True, revoked_at__isnull=True).exclude(prospect__phone=""):
        if phone.key(row.prospect.phone) == k:
            return {"how": str(row.how).lower(), "obtained_at": row.obtained_at}
    return None


def grant_consent(number, how, obtained_how, user=None, device=None) -> MobileCallConsent:
    norm = phone.normalize(number)
    if not phone.is_valid(norm):
        raise MobileError("bad_number", "شماره درست نیست.", 400)
    how = str(how or "verbal").lower()
    if how not in MobileCallConsent.How.values:
        raise MobileError("bad_how", "نحوهٔ رضایت باید verbal، written یا contract باشد.", 400)
    if not str(obtained_how or "").strip():
        raise MobileError("missing_fields", "بنویسید رضایت دقیقاً چطور گرفته شد.", 400)
    row, _ = MobileCallConsent.objects.update_or_create(
        number=norm, defaults={"granted": True, "how": how, "obtained_how": str(obtained_how)[:300], "obtained_at": timezone.now(),
                               "revoked_at": None, "declared_by": user, "device": device})
    return row


def revoke_consent(number) -> bool:
    norm = phone.normalize(number)
    return bool(MobileCallConsent.objects.filter(number=norm, revoked_at__isnull=True).update(revoked_at=timezone.now()))


# ------------------------------------------------------------------ recordings

def sniff_audio(head: bytes, ext: str) -> bool:
    """Light magic-number check: the file really looks like audio, whatever its name says."""
    if len(head) < 8:
        return False
    if head[4:8] == b"ftyp":                     # m4a / mp4 / 3gp
        return True
    if head[:3] == b"ID3" or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):   # mp3 / adts aac
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return True
    if head[:5] == b"#!AMR" or head[:9] == b"#!AMR-WB\n"[:9]:
        return True
    if head[:4] in (b"OggS", b"fLaC", b"\x1aE\xdf\xa3"):
        return True
    return False


def save_recording(call: MobileCall, upload, source="builtin_recorder", duration_s=None) -> MobileCall:
    settings = MobileSettings.get()
    if not settings.calls_upload_enabled:
        raise MobileError("uploads_disabled", "بارگذاریِ ضبط تماس از پنل خاموش است.", 409)
    state = consent_state(call.number)
    if not state["granted"]:
        call.status = MobileCall.Status.NO_CONSENT
        call.error = "رضایتِ طرفِ مقابل برای ضبط ثبت نشده"
        call.save(update_fields=["status", "error", "updated_at"])
        raise MobileError("no_consent", "بدون ثبتِ رضایتِ طرفِ مقابل، ضبط ذخیره نمی‌شود. اول رضایت را ثبت کنید.", 403)
    size = getattr(upload, "size", 0) or 0
    if size > settings.max_audio_mb * 1024 * 1024:
        raise MobileError("too_large", f"فایل بزرگ‌تر از {settings.max_audio_mb} مگابایت است.", 413)
    ext = os.path.splitext(getattr(upload, "name", "") or "")[1].lower()
    head = upload.read(16)
    upload.seek(0)
    if ext not in ALLOWED_EXT or not sniff_audio(head, ext):
        raise MobileError("bad_audio", "این فایل صدا نیست یا قالبش پشتیبانی نمی‌شود.", 415)
    now = timezone.now()
    rel = f"calls/{now:%Y}/{now:%m}/{call.uid}{ext}"
    target = data_dir() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    try:
        os.chmod(target, 0o640)
    except OSError:
        pass
    call.audio_path = rel
    call.audio_size = target.stat().st_size
    call.audio_mime = getattr(upload, "content_type", "") or ""
    call.audio_source = str(source or "")[:20]
    if duration_s:
        try:
            call.duration_s = max(call.duration_s, int(duration_s))
        except (TypeError, ValueError):
            pass
    call.status = MobileCall.Status.UPLOADED
    call.error = ""
    call.save()
    return call


def audio_file(call: MobileCall) -> Path | None:
    if not call.audio_path:
        return None
    p = (data_dir() / call.audio_path).resolve()
    if data_dir().resolve() not in p.parents or not p.is_file():
        return None
    return p


# ------------------------------------------------------------------ serialisation

def call_dict(c: MobileCall, detail=False) -> dict:
    d = {
        "uid": str(c.uid), "number": c.number_raw or phone.national(c.number), "normalized": c.number,
        "direction": c.direction, "started_at": c.started_at, "duration_s": c.duration_s, "contact_name": c.contact_name,
        "caller": {"display": c.caller_label or None, "known": bool(c.caller_label)},
        "status": c.status, "has_audio": bool(c.audio_path), "error": c.error,
    }
    if detail:
        d.update({
            "transcript": c.transcript, "segments": c.segments or [], "asr_engine": c.asr_engine, "summary": c.summary,
            "sentiment": c.sentiment, "objections": c.objections or [], "commitments": c.commitments or [],
            "next_steps": c.next_steps or [],
        })
    return d

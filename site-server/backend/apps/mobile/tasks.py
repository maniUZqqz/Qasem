"""Background work for calls: transcribe, then write the AI notes. Never raises (a stuck row looks like a broken feature)."""
from __future__ import annotations

import logging

from celery import shared_task

from . import asr, calls, notes
from .models import MobileCall, MobileSettings

logger = logging.getLogger(__name__)


PARKED_TEXT = "در صف تا روشن شدنِ سرورِ پردازش؛ تبدیل به متن و یادداشتِ تماس خودکار انجام می‌شود و این‌جا می‌آید."


def _park(call, exc, status, strict: bool) -> bool:
    """موتورِ گفتار/متن الان نیست ولی «با صبر درست می‌شود» ⇒ «در صف تا روشن شدنِ سرورِ پردازش» (compute.deferred، platform) و وضعیتِ تماس
    «منتظر» (نه «خطا»). strict (اجرای صف‌دار): فقط وضعیت را می‌گذارد و فراخوان خطا را دوباره می‌اندازد تا درخواست در صف بماند."""
    from apps.compute import deferred

    if not deferred.is_outage(exc):
        return False
    if not strict and not deferred.defer("mobile.call", None, {"call_id": call.pk}, reason=str(exc)[:300]):
        return False
    call.status, call.error = status, PARKED_TEXT
    call.save(update_fields=["status", "error", "updated_at"])
    return True


def process(call_id: int, *, strict: bool = False) -> str:
    call = MobileCall.objects.filter(pk=call_id).first()
    if call is None:
        return "missing"
    settings = MobileSettings.get()
    path = calls.audio_file(call)
    if path is None:
        call.status, call.error = MobileCall.Status.FAILED, "فایلِ صدا پیدا نشد."
        call.save(update_fields=["status", "error", "updated_at"])
        return "no_audio"
    if not settings.asr_enabled:
        call.status, call.error = MobileCall.Status.UPLOADED, "تبدیل به متن از پنل خاموش است."
        call.save(update_fields=["status", "error", "updated_at"])
        return "asr_off"
    call.status, call.error = MobileCall.Status.TRANSCRIBING, ""
    call.save(update_fields=["status", "error", "updated_at"])
    store = notes.resolve_store(call.user)
    try:
        result = asr.transcribe(path, store=store)
    except asr.AsrUnavailable as exc:
        if _park(call, exc, MobileCall.Status.UPLOADED, strict):
            if strict:
                raise
            return "asr_queued"
        call.status, call.error = MobileCall.Status.FAILED, str(exc)[:400]
        call.save(update_fields=["status", "error", "updated_at"])
        return "asr_failed"
    except Exception as exc:  # noqa: BLE001
        logger.exception("call %s transcription crashed", call_id)
        call.status, call.error = MobileCall.Status.FAILED, f"تبدیل به متن خطا داد: {exc}"[:400]
        call.save(update_fields=["status", "error", "updated_at"])
        return "asr_crashed"
    call.transcript = (result.get("text") or "").strip()
    call.segments = result.get("segments") or []
    call.asr_engine = str(result.get("engine") or "")[:12]
    call.status = MobileCall.Status.TRANSCRIBED
    call.error = "" if call.transcript else "در این فایل حرفی شنیده نشد."
    call.save()
    if not call.transcript:
        return "empty"
    try:
        data = notes.analyse(call)
    except notes.NotesUnavailable as exc:
        if _park(call, exc, MobileCall.Status.TRANSCRIBED, strict):
            if strict:
                raise
            return "notes_queued"
        call.error = f"متن آماده شد ولی تحلیل نشد: {exc}"[:400]
        call.save(update_fields=["error", "updated_at"])
        return "notes_failed"
    except Exception as exc:  # noqa: BLE001
        logger.exception("call %s notes crashed", call_id)
        call.error = f"متن آماده شد ولی تحلیل نشد: {exc}"[:400]
        call.save(update_fields=["error", "updated_at"])
        return "notes_crashed"
    call.summary, call.sentiment = data["summary"], data["sentiment"]
    call.objections, call.commitments, call.next_steps = data["objections"], data["commitments"], data["next_steps"]
    call.status, call.error = MobileCall.Status.ANALYSED, ""
    call.save()
    return "ok"


@shared_task(name="apps.mobile.tasks.process_call")
def process_call(call_id: int) -> str:
    return process(call_id)


def deferred_process_call(store, *, call_id: int, _user_id=None) -> dict:
    """اجرای صف‌دار (compute.deferred، سطحِ پلتفرم): همان تبدیل به متن + یادداشتِ تماس با موتورِ واقعی. هنوز نیست ⇒ خطا ⇒ در صف می‌ماند."""
    call = MobileCall.objects.filter(pk=call_id).first()
    if call is None or call.status == MobileCall.Status.ANALYSED:
        return {"state": "skipped"}
    return {"state": process(call_id, strict=True)}


def on_deferred_end(store, *, state: str = "", message: str = "", call_id=None, **_params) -> None:
    """برگهٔ صف لغو/منقضی شد ⇒ تماس با «در صف…» بی‌پایان نماند."""
    call = MobileCall.objects.filter(pk=call_id).first() if call_id else None
    if call is None or call.error != PARKED_TEXT:
        return
    call.error = "تحلیلِ خودکار لغو شد." if state == "cancelled" else "هوش مصنوعی تا مهلتِ انتظار برنگشت؛ تحلیل انجام نشد."
    if call.status == MobileCall.Status.UPLOADED:
        call.status = MobileCall.Status.FAILED
    call.save(update_fields=["status", "error", "updated_at"])

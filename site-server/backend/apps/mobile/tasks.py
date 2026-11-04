"""Background work for calls: transcribe, then write the AI notes. Never raises (a stuck row looks like a broken feature)."""
from __future__ import annotations

import logging

from celery import shared_task

from . import asr, calls, notes
from .models import MobileCall, MobileSettings

logger = logging.getLogger(__name__)


def process(call_id: int) -> str:
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

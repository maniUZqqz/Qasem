"""کارهای Celery ِ ادیتورِ عکس. هیچ‌کدام منتظرِ سرورِ پردازش نمی‌ماند (نخِ Celery گرو نمی‌رود): poll خودش را
دوباره در صف می‌گذارد — هر ۶ ثانیه وقتی گره آنلاین است، هر ۳۰ ثانیه وقتی نیست. بعد از ۲۴ ساعت poll می‌ایستد ولی
کار در صف می‌ماند و هر بار که پنل باز شود دوباره وارسی می‌شود (views._nudge)."""
from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import services
from .models import PhotoEdit

logger = logging.getLogger(__name__)

POLL_ONLINE = 6
POLL_OFFLINE = 30
POLL_HOURS = 24


def _eager() -> bool:
    return bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))


def _edit(edit_id: int) -> PhotoEdit | None:
    return PhotoEdit.objects.filter(pk=edit_id).select_related("asset", "asset__store").first()


def _schedule_poll(edit_id: int, started: str | None = None) -> None:
    if _eager():
        return
    online = services.node_status()["online"]
    poll_edit_task.apply_async((edit_id, started or timezone.now().isoformat()),
                               countdown=POLL_ONLINE if online else POLL_OFFLINE)


@shared_task(ignore_result=True)
def start_edit_task(edit_id: int) -> None:
    edit = _edit(edit_id)
    if edit is None:
        return
    services.start(edit)
    if edit.state == PhotoEdit.State.NODE:
        if services.refresh(edit):          # همان ویرایش قبلاً ساخته شده بود ⇐ همین حالا
            edit.refresh_from_db()
            services.run_server_stage(edit)
            return
        _schedule_poll(edit_id)


@shared_task(ignore_result=True)
def poll_edit_task(edit_id: int, started: str | None = None) -> None:
    edit = _edit(edit_id)
    if edit is None or edit.state != PhotoEdit.State.NODE:
        return
    if services.refresh(edit):
        finish_edit_task.delay(edit_id)
        return
    edit.refresh_from_db()
    if edit.state != PhotoEdit.State.NODE:
        return
    try:
        begun = datetime.fromisoformat(started) if started else edit.created_at
    except ValueError:
        begun = edit.created_at
    if (timezone.now() - begun).total_seconds() > POLL_HOURS * 3600:
        logger.info("photoedit: edit %s still waits for a processing server; polling stops (panel nudges it)", edit_id)
        return
    _schedule_poll(edit_id, started)


@shared_task(ignore_result=True, soft_time_limit=900)
def finish_edit_task(edit_id: int) -> None:
    edit = _edit(edit_id)
    if edit is not None and edit.state == PhotoEdit.State.SERVER:
        services.run_server_stage(edit)


# ───────────────────────────── طراحِ خودکار (نیمه‌خودکار با دستور)

@shared_task(ignore_result=True, soft_time_limit=1500, time_limit=1560)
def run_design_task(design_id: int, allow_wait: bool = True) -> None:
    """یک طراحی را کامل می‌کند (تحلیل ⇒ برنامه ⇒ ساخت ⇒ نقد). از ``designer.engine.run`` است؛ خطا همیشه روی خودِ طراحی می‌نشیند.
    هوشِ مصنوعی روی سرورِ پردازشِ خاموش ⇒ طراحی «در صف — منتظرِ سرورِ پردازش» می‌ماند و خودش دوباره اجرا می‌شود (engine._park)."""
    from .designer import engine

    engine.run(design_id, allow_wait=allow_wait)


@shared_task(ignore_result=True, soft_time_limit=3300, time_limit=3400)
def run_batch_task(batch_id: int) -> None:
    """«طراحیِ گروهی»: عکس‌ها تک‌به‌تک (batch.run)؛ پیشرفت روی خودِ گروه می‌نشیند."""
    from . import batch

    batch.run(batch_id)


# ───────────────────────────── ترجمهٔ توضیحِ «پرکردنِ هوشمند» (فارسی ⇒ انگلیسی)

@shared_task(ignore_result=True)
def genfill_translate_job_task(uid: str) -> None:
    """کارِ منتظرِ ترجمه را یک گام جلو می‌برد؛ مترجمی نبود ⇒ بعد از GENFILL_TR_RETRY_S ثانیه دوباره (مثلِ poll ِ بالا؛ زیرِ
    celery eager تکرار نمی‌شود). گرهٔ خاموش و متیسِ بی‌اعتبار فقط یعنی «بعداً»: کار گم نمی‌شود."""
    result = services.genfill_translate_step(uid)
    if result == "waiting" and not _eager():
        genfill_translate_job_task.apply_async((uid,), countdown=services.GENFILL_TR_RETRY_S)


@shared_task(ignore_result=True)
def genfill_preview_task(store_id: int, text: str) -> None:
    """ترجمهٔ پیش‌نمایشِ پنل (پیش از «اجرا»)؛ نتیجه یا دلیلِ شکست در فایلِ کَش/وضعیت می‌ماند و پنل می‌خواندش."""
    from apps.stores.models import Store

    from . import translate

    store = Store.objects.filter(pk=store_id).first()
    if store is not None:
        translate.run_preview(store, text)

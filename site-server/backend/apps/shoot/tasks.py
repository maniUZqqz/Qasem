"""کارهای Celery ِ فیلم‌برداریِ هدایت‌شده (صفِ پیش‌فرضِ celery؛ همه روی سرورِ سایت به جز حذفِ پس‌زمینه)."""
from __future__ import annotations

import logging

from celery import shared_task

from .models import ShootOutput, ShootSession

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True, soft_time_limit=300)
def analyze_task(session_id: int) -> None:
    from . import services

    session = ShootSession.objects.filter(pk=session_id).select_related("product", "store").first()
    if session is not None:
        services.run_analysis(session)


@shared_task(ignore_result=True, soft_time_limit=900)
def voice_task(session_id: int) -> None:
    from . import voice

    session = ShootSession.objects.filter(pk=session_id).select_related("store").first()
    if session is None:
        return
    try:
        result = voice.build_cues(session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("shoot: voice cues for session %s failed", session_id)
        result = {"state": "FAILED", "clips": {}, "error": str(exc)[:300]}
    ShootSession.objects.filter(pk=session_id).update(voice=result)


def _run_output(output_id: int, user_id, kind: str) -> None:
    from django.contrib.auth import get_user_model

    from . import render, services

    output = ShootOutput.objects.filter(pk=output_id).select_related("session", "session__store",
                                                                      "session__product").first()
    if output is None or output.state not in (ShootOutput.State.QUEUED, ShootOutput.State.RUNNING):
        return
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    services.set_output(output, state=ShootOutput.State.RUNNING, progress=0.02, message="شروع شد")

    def progress(frac: float, message: str) -> None:
        services.set_output(output, progress=round(min(0.99, max(0.0, frac)), 3), message=message[:300])

    try:
        fn = render.render_video if kind == ShootOutput.Kind.VIDEO else render.render_poster
        result = fn(output, user, progress)
    except Exception as exc:  # noqa: BLE001
        logger.exception("shoot: output %s failed", output_id)
        services.set_output(output, state=ShootOutput.State.FAILED, message="ناموفق", error=str(exc)[:3000])
        return
    services.set_output(output, state=ShootOutput.State.READY, progress=1.0, message="آماده",
                        file=result["file"], thumb=result["thumb"], stats=result["stats"])


@shared_task(ignore_result=True, soft_time_limit=1800)
def render_video_task(output_id: int, user_id=None) -> None:
    _run_output(output_id, user_id, ShootOutput.Kind.VIDEO)


@shared_task(ignore_result=True, soft_time_limit=600)
def render_poster_task(output_id: int, user_id=None) -> None:
    _run_output(output_id, user_id, ShootOutput.Kind.POSTER)

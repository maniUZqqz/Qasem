"""کارهای Celery ِ استودیوی موشن.

  · site_render_task  ⇒ رندرِ سایت (یک‌به‌یک، با قفل)
  · poll_render_task  ⇒ وضعیتِ کارِ گره را دنبال می‌کند و وقتی تمام شد ویدیو را در رسانهٔ فروشگاه می‌گذارد.
    نخِ Celery گرو نمی‌ماند: خودش را دوباره در صف می‌گذارد (۶ ثانیه وقتی گره آنلاین است، ۳۰ ثانیه وقتی نیست، تا ۴۸ ساعت).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import pipeline, services
from .models import MotionRender

logger = logging.getLogger(__name__)

POLL_ONLINE = 6
POLL_OFFLINE = 30
POLL_HOURS = 48


def _eager() -> bool:
    return bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))


def schedule_poll(render_id: int) -> None:
    if _eager():
        return
    from apps.compute import services as CS

    online = bool(CS.online_nodes(services.CAPABILITY))
    poll_render_task.apply_async((render_id,), countdown=POLL_ONLINE if online else POLL_OFFLINE)


@shared_task(ignore_result=True, name="apps.motion.tasks.poll_render_task")
def poll_render_task(render_id: int) -> None:
    r = MotionRender.objects.filter(pk=render_id).select_related("store").first()
    if r is None or r.state not in MotionRender.ACTIVE or r.target != MotionRender.Target.NODE:
        return
    if services.refresh(r):
        return
    if timezone.now() - r.created_at > timedelta(hours=POLL_HOURS):
        return          # کار در صف می‌ماند؛ با باز شدنِ پنل دوباره وارسی می‌شود
    schedule_poll(render_id)


@shared_task(ignore_result=True, name="apps.motion.tasks.site_render_task", time_limit=services.runner.SITE_TIMEOUT_S + 600)
def site_render_task(render_id: int) -> None:
    r = MotionRender.objects.filter(pk=render_id).select_related("store").first()
    if r is None:
        return
    services.render_on_site(r)


PREPARE_RETRY_S = 60


def _launch(render: MotionRender) -> None:
    """طرحِ نهایی آماده است: گره ⇐ ثبت در صف + poll؛ سایت ⇐ تسکِ رندر."""
    services.start(render)
    render.refresh_from_db()
    if render.state == MotionRender.State.FAILED:
        return
    if render.target == MotionRender.Target.SITE:
        _run(site_render_task, render.pk)
    else:
        schedule_poll(render.pk)


@shared_task(ignore_result=True, name="apps.motion.tasks.prepare_render_task", time_limit=2400)
def prepare_render_task(render_id: int) -> None:
    """کنترلِ کیفیت + صدا، سپس رندر. صدای منتظرِ گره ⇒ خودش را هر ۶۰ ثانیه دوباره می‌آورد (تا ۴۸ ساعت) و با روشن‌شدنِ گره خودکار ادامه می‌دهد."""
    r = MotionRender.objects.filter(pk=render_id).select_related("store", "plan").first()
    if r is None or r.state not in MotionRender.ACTIVE or r.job_uid:
        return
    try:
        outcome = pipeline.prepare_render(r)
    except Exception as exc:  # noqa: BLE001
        logger.exception("motion: prepare of %s failed", render_id)
        services.fail(r, f"آماده‌سازی ناموفق بود: {exc}")
        return
    if outcome == "waiting":
        if timezone.now() - r.created_at > timedelta(hours=POLL_HOURS):
            services.fail(r, "گویندهٔ روی سرورِ پردازش تا ۴۸ ساعت ساخته نشد.")
        elif not _eager():
            prepare_render_task.apply_async((render_id,), countdown=PREPARE_RETRY_S)
        return
    if outcome == "ready":
        r.refresh_from_db()
        if r.state in MotionRender.ACTIVE:
            _launch(r)


@shared_task(ignore_result=True, name="apps.motion.tasks.critique_task", time_limit=1500)
def critique_task(plan_id: int) -> None:
    """نقدِ بصریِ طرح؛ مدل نبود ⇒ «منتظر» و هر ۶۰ ثانیه دوباره (تا ۴۸ ساعت)."""
    from . import critique
    from .models import MotionPlan

    plan = MotionPlan.objects.filter(pk=plan_id).select_related("store").first()
    if plan is None or (plan.critique or {}).get("state") not in ("waiting", "running"):
        return
    state = critique.run(plan)
    if state.get("state") == "waiting" and not _eager():
        critique_task.apply_async((plan_id,), countdown=critique.RETRY_S)


@shared_task(ignore_result=True, name="apps.motion.tasks.qa_task", time_limit=1500)
def qa_task(plan_id: int, apply_fixes: bool = True, geometry: bool = True) -> None:
    """کنترلِ کیفیتِ یک طرح (قاعده‌ای + هندسهٔ فریم‌ها)؛ اصلاح‌ها یک نسخهٔ قابل‌برگشت می‌شوند و گزارش روی plan.qa می‌ماند."""
    from . import plans, specs
    from .models import MotionPlan

    plan = MotionPlan.objects.filter(pk=plan_id).select_related("store").first()
    if plan is None:
        return
    try:
        report = pipeline.run_qa(plan.store, plan.spec, tag=f"plan{plan.pk}", max_total=specs.MAX_TOTAL_S_NODE, geometry=geometry)
        rep = pipeline.slim_report(report)
        rep.update(state="done", applied=bool(apply_fixes and report["fixed"]))
        if apply_fixes and report["fixed"]:
            plan = plans.commit(plan, report["spec"], label=rep["summary"][:150], source="qa")
        MotionPlan.objects.filter(pk=plan.pk).update(qa=rep)
    except Exception as exc:  # noqa: BLE001
        logger.exception("motion: QA task of plan %s failed", plan_id)
        MotionPlan.objects.filter(pk=plan_id).update(qa={"state": "failed", "summary": f"کنترلِ کیفیت ناموفق بود: {exc}"[:300], "rounds": [], "remaining": []})


def schedule_critique(plan) -> dict:
    from . import critique

    state = critique.request(plan)
    _run(critique_task, plan.pk)
    return state


def dispatch(render: MotionRender) -> None:
    """رندرِ تازه‌ساخته را به راه می‌اندازد: [کنترلِ کیفیت + صدا] ⇒ گره (ثبت در صف + poll) یا سایت (تسکِ رندر)."""
    try:
        if render.mode != MotionRender.Mode.CODE and (render.options or {}).get("prepare", True):
            render.state, render.message = MotionRender.State.PREPARING, "آماده‌سازی (کنترلِ کیفیت و صدا)…"
            render.save(update_fields=["state", "message", "updated_at"])
            _run(prepare_render_task, render.pk)
            if (render.options or {}).get("critique") and render.plan_id:
                schedule_critique(render.plan)
            return
        _launch(render)
    except Exception as exc:  # noqa: BLE001
        logger.exception("motion: dispatch of %s failed", render.pk)
        services.fail(render, f"شروعِ رندر ناموفق بود: {exc}")


def _run(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:  # noqa: BLE001 — بی‌بروکر: همین‌جا
        logger.warning("motion: celery unavailable, running %s inline", task.name)
        task(*args)

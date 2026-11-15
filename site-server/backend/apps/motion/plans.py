"""طرحِ زنده و تاریخچهٔ نسخه‌ها: هر تغییر (کاربر، چت، هوش مصنوعی، اصلاحِ خودکارِ QA) یک نسخه است؛ برگشت و جلوتر فقط نشانگر را جابه‌جا می‌کنند.

قاعده‌ها: ویرایش پس از «برگشت» شاخهٔ جلوتر را دور می‌اندازد (مثلِ هر ویرایشگر)، حداکثر ۶۰ نسخه نگه داشته می‌شود، و همهٔ تغییرها از
specs.normalize_spec می‌گذرند؛ پس طرحِ ذخیره‌شده همیشه معتبر است.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from . import patch as patch_mod
from . import specs
from .models import MotionPlan, MotionPlanRev

MAX_REVS = 60
SOURCES = ("user", "ai", "chat", "patch", "qa", "critique", "audio", "import", "undo")


class PlanError(ValueError):
    pass


def _clean(spec: dict, notes=None) -> dict:
    try:
        out = specs.normalize_spec(spec, max_total=specs.MAX_TOTAL_S_NODE, notes=notes)
    except specs.SpecError as exc:
        raise PlanError(str(exc)) from exc
    out.pop("total_s", None)
    return out


@transaction.atomic
def create(store, user, spec: dict, *, title: str = "", source: str = "user", label: str = "نسخهٔ اول") -> MotionPlan:
    clean = _clean(spec)
    plan = MotionPlan.objects.create(store=store, user=user, title=(title or _title_of(clean))[:200], spec=clean, cursor=1)
    MotionPlanRev.objects.create(plan=plan, n=1, spec=clean, label=label[:160], source=source if source in SOURCES else "user")
    return plan


def _title_of(spec: dict) -> str:
    sc = spec["scenes"][0]
    return str(sc.get("title") or sc.get("name") or sc.get("text") or sc.get("caption") or "طرحِ موشن")[:80]


@transaction.atomic
def commit(plan: MotionPlan, spec: dict, *, label: str = "", source: str = "user", ops: list | None = None, coalesce: bool = False) -> MotionPlan:
    """نسخهٔ تازه؛ اگر طرح عوض نشده باشد کاری نمی‌کند. coalesce: ویرایش‌های پیاپیِ کاربر (کمتر از ۱۵ ثانیه) یک نسخه می‌شوند (تایپ کردن نسخهٔ جداگانه نمی‌سازد)."""
    plan = MotionPlan.objects.select_for_update().get(pk=plan.pk)
    clean = _clean(spec)
    if _same(clean, plan.spec):
        return plan
    if coalesce and source == "user":
        last = MotionPlanRev.objects.filter(plan=plan, n=plan.cursor).first()
        if last is not None and last.source == "user" and last.n > 1 and (timezone.now() - last.created_at).total_seconds() < 15 and not MotionPlanRev.objects.filter(plan=plan, n__gt=plan.cursor).exists():
            last.spec, last.created_at = clean, timezone.now()
            last.save(update_fields=["spec", "created_at"])
            plan.spec, plan.qa = clean, {}
            plan.save(update_fields=["spec", "qa", "updated_at"])
            return plan
    MotionPlanRev.objects.filter(plan=plan, n__gt=plan.cursor).delete()          # شاخهٔ «جلوتر» دور ریخته می‌شود
    n = plan.cursor + 1
    MotionPlanRev.objects.create(plan=plan, n=n, spec=clean, label=(label or "ویرایش")[:160], source=source if source in SOURCES else "user", ops=ops or [])
    old = list(MotionPlanRev.objects.filter(plan=plan).order_by("n").values_list("pk", flat=True))
    if len(old) > MAX_REVS:
        MotionPlanRev.objects.filter(pk__in=old[: len(old) - MAX_REVS]).delete()
    plan.spec, plan.cursor = clean, n
    plan.qa = {}                      # گزارشِ قبلی دیگر برای این نسخه نیست
    plan.save(update_fields=["spec", "cursor", "qa", "updated_at"])
    return plan


def _same(a: dict, b: dict) -> bool:
    f = lambda s: {k: v for k, v in s.items() if k not in ("total_s", "safe")}  # noqa: E731
    return f(a) == f(b)


def apply_ops(plan: MotionPlan, ops, *, label: str = "", source: str = "patch") -> tuple[MotionPlan, list]:
    """patch ⇒ نسخهٔ تازه. ⇒ (plan, یادداشت‌های فارسی از آنچه عوض شد)."""
    notes: list = []
    try:
        new = patch_mod.apply_patch(plan.spec, ops, notes=notes)
    except patch_mod.PatchError as exc:
        raise PlanError(str(exc)) from exc
    summary = patch_mod.diff_summary(plan.spec, new)
    plan = commit(plan, new, label=label or "؛ ".join(summary)[:150] or "تغییر", source=source, ops=ops if isinstance(ops, list) else [ops])
    return plan, summary + notes


def history(plan: MotionPlan) -> list:
    return [{"n": r.n, "label": r.label, "source": r.source, "current": r.n == plan.cursor, "created_at": r.created_at.isoformat(), "ops": r.ops}
            for r in MotionPlanRev.objects.filter(plan=plan).order_by("n")]


@transaction.atomic
def step(plan: MotionPlan, direction: int) -> MotionPlan:
    """direction -1 = برگشت (undo)، +1 = جلوتر (redo)."""
    plan = MotionPlan.objects.select_for_update().get(pk=plan.pk)
    target = plan.cursor + (1 if direction > 0 else -1)
    rev = MotionPlanRev.objects.filter(plan=plan, n=target).first()
    if rev is None:
        raise PlanError("چیزی برای برگشتن نیست." if direction < 0 else "چیزی برای جلوتر رفتن نیست.")
    plan.spec, plan.cursor, plan.qa = rev.spec, rev.n, {}
    plan.save(update_fields=["spec", "cursor", "qa", "updated_at"])
    return plan


@transaction.atomic
def restore(plan: MotionPlan, n: int) -> MotionPlan:
    rev = MotionPlanRev.objects.filter(plan=plan, n=n).first()
    if rev is None:
        raise PlanError("این نسخه پیدا نشد.")
    plan = MotionPlan.objects.select_for_update().get(pk=plan.pk)
    plan.spec, plan.cursor, plan.qa = rev.spec, rev.n, {}
    plan.save(update_fields=["spec", "cursor", "qa", "updated_at"])
    return plan


def can_undo(plan: MotionPlan) -> bool:
    return MotionPlanRev.objects.filter(plan=plan, n=plan.cursor - 1).exists()


def can_redo(plan: MotionPlan) -> bool:
    return MotionPlanRev.objects.filter(plan=plan, n=plan.cursor + 1).exists()


def plan_dict(plan: MotionPlan, *, with_history: bool = True) -> dict:
    from . import services

    spec = dict(plan.spec)
    spec["total_s"] = round(specs.total_seconds(spec), 2) if spec.get("scenes") else 0
    d = {"id": plan.pk, "title": plan.title, "spec": spec, "rev": plan.cursor, "can_undo": can_undo(plan), "can_redo": can_redo(plan),
         "qa": services.qa_public(plan.qa or {}), "critique": services.critique_public(plan.critique or {}), "updated_at": plan.updated_at.isoformat(),
         "created_at": plan.created_at.isoformat()}
    if with_history:
        d["history"] = history(plan)
    return d

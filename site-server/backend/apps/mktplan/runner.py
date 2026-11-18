"""اجرای برنامه: ساختنِ کارها، همگام‌کردنِ وضعیت‌ها از روی چیزهای ساخته‌شده، و تیکِ پس‌زمینه.

سه عملیات:

* ``run_plan``   — برای هر کارِ برنامه تولیدکننده‌اش را صدا می‌زند (اول می‌پذیرد، بعد می‌سازد؛ تکرارپذیر).
* ``sync_plan``  — وضعیتِ هر کار را از روی پیوندهایش می‌خواند (رندرِ موشن، کارِ صف، ردیفِ کمپین…) و ذخیره می‌کند.
* ``tick``       — هر ۱۰ دقیقه: همگام می‌کند، و کارهایی را که منتظرِ «هوش مصنوعی» یا «سرورِ پردازش» بودند وقتی آماده شدند پیش می‌برد؛ پس با روشن‌شدنِ گره
  همه‌چیز بی‌هیچ کلیکی ادامه می‌یابد.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from . import ai as plan_ai
from . import clock, drafts, facts as facts_mod, kinds, producers, refs
from .models import MarketingPlan, PlanItem

logger = logging.getLogger(__name__)

LOCK_S = 20 * 60
MAX_TRIES = 6
POLISH_PER_TICK = 3
S = PlanItem.Status


# ----------------------------------------------------------------------------- گره

def node_state() -> dict:
    from apps.compute.models import ComputeNode

    nodes = list(ComputeNode.objects.filter(enabled=True))
    on = [n for n in nodes if n.online]
    pick = (on or nodes or [None])[0]
    return {
        "online": bool(on), "known": len(nodes), "name": pick.name if pick else "",
        "last_seen": pick.last_seen.isoformat() if pick and pick.last_seen else None,
        "agent": str(((pick.capabilities or {}).get("agent") or "") if pick else ""),
    }


# ----------------------------------------------------------------------------- همگام‌سازیِ وضعیت

def _refresh_ref(ref: dict) -> None:
    """کارِ تمام‌شدهٔ گره را به خروجیِ بخشِ مربوط تبدیل می‌کند (همان تابعی که صفحهٔ آن بخش هنگامِ باز شدن صدا می‌زند)."""
    t = ref.get("type")
    try:
        if t == "motion_render":
            from apps.motion import services as M
            from apps.motion.models import MotionRender

            r = MotionRender.objects.filter(pk=ref["id"]).first()
            if r is not None and r.state in (MotionRender.State.QUEUED, MotionRender.State.PREPARING, MotionRender.State.WAITING_NODE, MotionRender.State.RENDERING):
                M.refresh(r)
        elif t == "thumbnail":
            from apps.thumbs import services as T
            from apps.thumbs.models import Thumbnail

            r = Thumbnail.objects.filter(pk=ref["id"]).first()
            if r is not None and r.state == Thumbnail.State.WAITING_BG:
                T.refresh(r)
        elif t == "audio_asset":
            from apps.ai.models import AudioAsset
            from services.audio import studio

            r = AudioAsset.objects.filter(pk=ref["id"]).first()
            if r is not None and r.status in (AudioAsset.Status.PENDING, AudioAsset.Status.RUNNING):
                studio.sync(r)
        elif t == "character_job":
            from apps.brandchar import ai_render
            from apps.brandchar.models import CharacterAIJob

            r = CharacterAIJob.objects.filter(pk=ref["id"]).first()
            if r is not None and r.state in (CharacterAIJob.State.QUEUED, CharacterAIJob.State.RUNNING):
                ai_render.refresh(r)
        elif t == "design_export":
            from apps.design_studio import bridges
            from apps.design_studio.models import DesignExport

            r = DesignExport.objects.filter(pk=ref["id"]).first()
            if r is not None and r.kind == "mp4" and r.state in (DesignExport.State.QUEUED, DesignExport.State.RUNNING):
                bridges.refresh_video(r)
        elif t == "scan":
            from apps.igtrends import dispatch
            from apps.igtrends.models import IgScanRun

            r = IgScanRun.objects.filter(pk=ref["id"]).first()
            if r is not None and r.state in (IgScanRun.State.QUEUED, IgScanRun.State.RUNNING):
                dispatch.sync_run(r)
    except Exception as exc:  # noqa: BLE001 — همگام‌سازیِ یک مورد نباید بقیه را بخواباند
        logger.warning("mktplan: refresh of %s failed: %s", ref, exc)


def derive(item: PlanItem, *, refresh: bool = False) -> tuple[str, str]:
    """وضعیتِ زندهٔ یک کار از روی پیوندهایش. ⇒ (وضعیت، پیامِ کوتاه). پیوندها را هم با وضعیتِ تازه به‌روز می‌کند."""
    meta = item.meta or {}
    rows = []
    new_refs = []
    for r in item.refs or []:
        if refresh:
            _refresh_ref(r)
        st, note = refs.state_of(r)
        new_refs.append({**r, "state": st, "note": note})
        rows.append((st, note, r))
    item.refs = new_refs
    live = [x for x in rows if x[0] != refs.MISSING]
    pick = lambda *states: next((x for x in live if x[0] in states), None)  # noqa: E731
    waiting, running = pick(refs.WAITING), pick(refs.RUNNING)
    failed, ready = pick(refs.FAILED), pick(refs.READY, refs.DONE)
    has_draft = bool(pick(refs.DRAFT)) or bool(item.draft)
    needs_you = meta.get("needs_you")
    if waiting:
        return S.WAITING_NODE, waiting[1] or "منتظرِ سرورِ پردازش"
    if running:
        return S.RUNNING, running[1] or "در حالِ ساخت"
    if failed and not ready:
        return S.FAILED, failed[1] or "ناموفق"
    if needs_you and not ready:
        return S.NEEDS_YOU, str(needs_you)
    if ready:
        return S.READY, ready[1] or "آماده"
    if meta.get("waiting_node"):
        return S.WAITING_NODE, str(meta["waiting_node"])
    if has_draft:
        return S.DRAFTED, item.message or "پیش‌نویس آماده است"
    if item.last_error:
        return S.FAILED, item.last_error[:200]
    return S.PLANNED, item.message or ""


def sync_item(item: PlanItem, *, refresh: bool = False) -> bool:
    status, msg = derive(item, refresh=refresh)
    changed = status != item.status or (msg and msg != item.message and status in (S.WAITING_NODE, S.RUNNING, S.FAILED, S.NEEDS_YOU, S.READY))
    if status in (S.WAITING_NODE, S.RUNNING, S.FAILED, S.NEEDS_YOU, S.READY) and msg:
        item.message = msg[:300]
    item.status = status
    item.save(update_fields=["status", "message", "refs", "updated_at"])
    return bool(changed)


def sync_plan(plan: MarketingPlan, *, refresh: bool = False) -> dict:
    n = 0
    for item in plan.items.all():
        if sync_item(item, refresh=refresh):
            n += 1
    return {"changed": n}


# ----------------------------------------------------------------------------- اجرا

def _lock(plan: MarketingPlan, now) -> bool:
    cutoff = now - timedelta(seconds=LOCK_S)
    got = MarketingPlan.objects.filter(pk=plan.pk).filter(Q(running_since__isnull=True) | Q(running_since__lt=cutoff)).update(running_since=now)
    return bool(got)


def _unlock(plan: MarketingPlan) -> None:
    MarketingPlan.objects.filter(pk=plan.pk).update(running_since=None)


def run_plan(plan: MarketingPlan, *, user=None, keys=None, kinds_only=None, log=None, force: bool = False) -> dict:
    """همهٔ کارها (یا فقط ``keys``/``kinds_only``) را می‌سازد. ⇒ {ran, ok, failed, waiting, skipped, log[]}."""
    now = timezone.now()
    if not _lock(plan, now) and not force:
        return {"ran": 0, "ok": 0, "failed": 0, "waiting": 0, "skipped": 0, "log": ["اجرای دیگری هنوز در جریان است"], "busy": True}
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        if log:
            log(msg)

    out = {"ran": 0, "ok": 0, "failed": 0, "waiting": 0, "skipped": 0}
    try:
        f = facts_mod.store_facts(plan.store)
        ctx = producers.Ctx(plan=plan, store=plan.store, user=user, f=f, log=say)
        for item in plan.items.order_by("day", "order", "id"):
            if keys and item.key not in keys:
                continue
            if kinds_only and item.kind not in kinds_only:
                continue
            if item.decision in ("skipped", "approved", "done"):
                out["skipped"] += 1
                continue
            res = producers.run_one(ctx, item)
            meta = dict(item.meta or {})
            meta["tries"] = int(meta.get("tries") or 0) + (0 if res["ok"] else 1)
            item.meta = meta
            item.save()
            out["ran"] += 1
            out["ok" if res["ok"] else "failed"] += 1
            out["waiting"] += int(res["waiting"])
            say(f"{item.key}: {'✓' if res['ok'] else '✗'} {item.message or item.last_error}"[:240])
        sync_plan(plan, refresh=True)
    finally:
        _unlock(plan)
    plan.last_run_at = timezone.now()
    plan.last_run = {"at": plan.last_run_at.isoformat(), "by": getattr(user, "username", "") if getattr(user, "is_authenticated", False) else "خودکار",
                     "counts": counts(plan), **{k: v for k, v in out.items()}, "log": lines[-60:]}
    plan.save(update_fields=["last_run_at", "last_run", "updated_at"])
    return {**out, "log": lines}


def run_background(plan: MarketingPlan, user=None, keys=None) -> str:
    """اجرا را در پس‌زمینه می‌اندازد (Celery، وگرنه رشته). ⇒ «celery» یا «thread»."""
    try:
        from .tasks import run_plan_task

        run_plan_task.delay(plan.pk, getattr(user, "pk", None), list(keys) if keys else None)
        return "celery"
    except Exception:  # noqa: BLE001 — بروکر نیست
        def work():
            try:
                run_plan(plan, user=user, keys=set(keys) if keys else None)
            except Exception:  # noqa: BLE001
                logger.exception("mktplan: background run failed")
            finally:
                try:
                    from django.db import connection

                    connection.close()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=work, name=f"mktplan-run-{plan.pk}", daemon=True).start()
        return "thread"


def counts(plan: MarketingPlan) -> dict:
    by: dict[str, int] = {}
    decided = 0
    for i in plan.items.all():
        by[i.status] = by.get(i.status, 0) + 1
        if i.decision:
            decided += 1
    total = sum(by.values())
    return {"total": total, "by_status": by, "decided": decided,
            "waiting_node": by.get(S.WAITING_NODE, 0), "needs_you": by.get(S.NEEDS_YOU, 0), "failed": by.get(S.FAILED, 0),
            "ready": by.get(S.READY, 0) + by.get(S.DRAFTED, 0)}


# ----------------------------------------------------------------------------- پولیش با هوش مصنوعی

_POLISHABLE = {"post", "carousel", "story", "reel", "profile", "email", "sms", "dm"}


def polish_item(plan: MarketingPlan, item: PlanItem, f: dict, *, ask=None) -> str:
    """پیش‌نویسِ قاعده‌محور را با هوش مصنوعی بازنویسی می‌کند. ⇒ «ok» | «skip» | دلیلِ فارسیِ ناموفقی."""
    from apps.campaigns.tasks_board import CampaignTask
    from apps.inbox.models import Broadcast

    if item.kind == "ideas":
        from apps.ideabank import fill, generator

        ok, why = plan_ai.available(plan.store)
        if not ok and ask is None:
            return why
        try:
            res = generator.generate_and_save(plan.store, count=6, use_ai=True, ctx=fill.context(plan.store), topic=f.get("flagship", ""),
                                              facts=[x for x in (f.get("one_liner"), f.get("tagline")) if x], variation=2)
        except ValueError as exc:
            item.ai_wait = False
            item.save(update_fields=["ai_wait", "updated_at"])
            return str(exc)
        item.ai_wait = res["via"] == "formula"
        item.meta = {**(item.meta or {}), "polished_by": (res.get("ai") or {}).get("label", "")}
        item.save(update_fields=["ai_wait", "meta", "updated_at"])
        return "ok" if not item.ai_wait else (res.get("message") or "هوش مصنوعی در دسترس نبود")[:200]
    if item.kind not in _POLISHABLE or not item.draft or (item.meta or {}).get("adopted"):
        item.ai_wait = False
        item.save(update_fields=["ai_wait", "updated_at"])
        return "skip"
    new, why = plan_ai.polish(plan.store, f, item.draft, kinds.label(item.kind), ask=ask)
    if new is None:
        return why
    old = item.draft
    for r in refs.of_type(item, "campaign_task"):
        t = CampaignTask.objects.filter(pk=r["id"]).first()
        if t is not None and old in (t.detail or ""):
            t.detail = t.detail.replace(old, new)
            t.save(update_fields=["detail", "updated_at"])
    for r in refs.of_type(item, "broadcast"):
        b = Broadcast.objects.filter(pk=r["id"], status=Broadcast.Status.DRAFT).first()
        if b is not None and b.text == old:
            b.text = new
            b.save(update_fields=["text", "updated_at"])
    item.draft, item.ai_wait = new, False
    item.meta = {**(item.meta or {}), "polished": True, "checks": drafts.check(new, f)}
    item.save(update_fields=["draft", "ai_wait", "meta", "updated_at"])
    return "ok"


# ----------------------------------------------------------------------------- تیکِ پس‌زمینه

def _needs_rerun(item: PlanItem, node_on: bool) -> bool:
    if item.decision:
        return False
    tries = int((item.meta or {}).get("tries") or 0)
    if (item.meta or {}).get("retry_soon") and tries < MAX_TRIES:        # مثلاً پروژهٔ سه‌بعدی هنوز صحنه ندارد؛ رندرش را همین تیک صف کن (گره روشن نباشد هم)
        return True
    if item.status == S.FAILED and tries < MAX_TRIES:
        return True
    if item.status == S.PLANNED:
        return True
    if item.status == S.WAITING_NODE and node_on and (item.meta or {}).get("waiting_node"):
        return True
    if node_on and item.needs_node and any(r.get("state") in (refs.CANCELLED, refs.MISSING) for r in item.refs or []):
        return True
    return False


def tick(plan_id: int | None = None, *, ask=None) -> dict:
    """همگام‌سازی + پیش‌بردنِ کارهای منتظر. ⇒ {plans, rerun, polished}."""
    plans = MarketingPlan.objects.filter(autorun=True)
    if plan_id:
        plans = plans.filter(pk=plan_id)
    out = {"plans": 0, "rerun": 0, "polished": 0}
    node = node_state()
    for plan in plans.select_related("store"):
        out["plans"] += 1
        try:
            sync_plan(plan, refresh=True)
            keys = {i.key for i in plan.items.all() if _needs_rerun(i, node["online"])}
            if keys:
                res = run_plan(plan, keys=keys)
                out["rerun"] += res.get("ran", 0)
            todo = [i for i in plan.items.all() if i.ai_wait and not i.decision]
            if todo:
                f = facts_mod.store_facts(plan.store)
                ok, _why = plan_ai.available(plan.store)
                if ok or ask is not None:
                    for item in todo[:POLISH_PER_TICK]:
                        if polish_item(plan, item, f, ask=ask) == "ok":
                            out["polished"] += 1
        except Exception:  # noqa: BLE001 — یک برنامهٔ خراب نباید تیکِ بقیه را بگیرد
            logger.exception("mktplan: tick failed for plan %s", plan.pk)
    return out


# ----------------------------------------------------------------------------- خروجیِ API

def item_public(i: PlanItem) -> dict:
    meta = i.meta or {}
    date = meta.get("date") or ""
    return {
        "weekday": clock.WEEKDAYS_FA[dt.date.fromisoformat(date).weekday()] if date else "",
        "id": i.pk, "key": i.key, "day": i.day, "order": i.order, "week": meta.get("week") or (1 if i.day <= 7 else 2), "date": date,
        "date_fa": clock.jalali(dt.date.fromisoformat(date)) if date else "",
        "when_fa": clock.fa_when(i.scheduled_for) if i.scheduled_for else "",
        "kind": i.kind, "kind_label": kinds.label(i.kind), "group": kinds.group_of(i.kind), "section": i.section,
        "url": kinds.url_for(i.section, i.plan.store_id) if i.section else "", "title": i.title, "brief": i.brief, "draft": i.draft,
        "status": i.status, "status_label": kinds.STATUS_FA.get(i.status, i.status), "decision": i.decision,
        "decision_label": kinds.DECISION_FA.get(i.decision, ""), "needs_node": i.needs_node, "ai_wait": i.ai_wait,
        "needs_you": meta.get("needs_you") or "", "message": i.message, "error": i.last_error, "checks": meta.get("checks") or [],
        "adopted": bool(meta.get("adopted")), "polished": bool(meta.get("polished")), "companion": meta.get("for") or "",
        "refs": [{"type": r.get("type"), "id": r.get("id"), "label": r.get("label", ""), "url": r.get("url", ""), "state": r.get("state", ""),
                  "note": r.get("note", "")} for r in (i.refs or [])],
    }


def plan_public(plan: MarketingPlan) -> dict:
    ok, why = plan_ai.available(plan.store)
    items = [item_public(i) for i in plan.items.select_related("plan").order_by("day", "order", "id")]
    return {
        "id": plan.pk, "key": plan.key, "name": plan.name, "goal": plan.goal, "start_date": plan.start_date.isoformat(),
        "start_fa": clock.jalali(plan.start_date), "days": plan.days, "autorun": plan.autorun, "summary": plan.summary,
        "last_run": plan.last_run or {}, "last_run_at": plan.last_run_at.isoformat() if plan.last_run_at else None,
        "running": bool(plan.running_since and plan.running_since > timezone.now() - timedelta(seconds=LOCK_S)),
        "counts": counts(plan), "items": items, "node": node_state(), "ai": {"ok": bool(ok), "why": why},
        "groups": kinds.GROUPS, "status_labels": kinds.STATUS_FA,
    }

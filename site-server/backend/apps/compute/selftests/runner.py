"""اجرای آزمونِ خودکار: ساختنِ اجرا، فرستادنِ کارهای واقعیِ کوچک به گره، سنجش، گزارش، و بازگرداندنِ کارهای ناموفق.

همه‌چیز در پایگاه‌داده است (SelfTestRun / SelfTestResult)؛ `advance()` هر دقیقه از `tasks.maintenance` صدا زده می‌شود و هر بار فقط
یک گام جلو می‌رود، پس با ری‌استارتِ سایت یا قطعِ گره چیزی گم نمی‌شود.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from .. import queue as QV
from .. import services as SV
from ..models import ComputeJob, ComputeNode, ComputeSettings, SelfTestResult, SelfTestRun
from . import (BOOT_BUSY, BOOT_MIN_AGENT, REGISTRY, YOUNG_AGENT_S, Ctx, Verdict, agent_age_s, agent_at_least, bootstrap_features,
               load_all, tests)
from .requeue import requeue_after_pass

logger = logging.getLogger(__name__)

QUEUE_STALE_S = 30 * 60            # کارِ آزمون که با گرهٔ آنلاین این‌قدر در صف ماند ⇒ رد (با علت)
RUN_STALE_S = 45 * 60              # گره این‌قدر خاموش بماند ⇒ اجرا متوقف
BLOCK_WAIT_S = 30 * 60             # مدلِ خاموش/نصب‌نشده: این‌قدر منتظر می‌مانیم
S = SelfTestResult.State


def node_code_id(caps: dict) -> str:
    c = caps.get("code") if isinstance(caps.get("code"), dict) else {}
    return str(c.get("id") or "")[:16]


def active_run(node) -> SelfTestRun | None:
    return SelfTestRun.objects.filter(node=node, state=SelfTestRun.State.RUNNING).order_by("-created_at").first()


def latest_run(node) -> SelfTestRun | None:
    return SelfTestRun.objects.filter(node=node).order_by("-created_at").first()


def run_outdated(run: SelfTestRun, caps: dict) -> bool:
    """اجرا برای نسخه‌ای از عامل (یا کدی) ساخته شده که دیگر روی گره نیست؟ (با ریستارتِ هم‌نسخه چیزی عوض نمی‌شود)"""
    have = str((caps or {}).get("agent") or "")[:20]
    if run.agent_version and have and run.agent_version != have:
        return True
    code = node_code_id(caps or {})
    return bool(run.code_id and code and run.code_id != code)


def update_in_flight(run: SelfTestRun) -> bool:
    """خودِ این اجرا دستورِ به‌روزرسانی/راه‌اندازیِ دوباره فرستاده و منتظرِ برگشتِ عامل است (آزمونِ update_flow)؟"""
    return any((r.extra or {}).get("cmd_id") and not r.final for r in run.results.all())


def abort_run(run: SelfTestRun, note: str) -> None:
    """اجرا را متوقف می‌کند: کارهای در راهش لغو، آزمون‌های ناتمامش «اجرا نشد» (با علت)."""
    for r in run.results.all():
        if r.final:
            continue
        if r.job_uid:
            job = ComputeJob.objects.filter(uid=r.job_uid).first()
            if job and not job.final:
                SV.cancel(job, "آزمونِ خودکار: " + note)
        _final(r, S.SKIPPED, note)
    run.state = SelfTestRun.State.ABORTED
    run.finished_at = timezone.now()
    run.note = note[:300]
    run.save()


def start_run(node: ComputeNode, trigger: str = "manual", by: str = "", deep: bool = False, only=None) -> SelfTestRun:
    """یک اجرای تازه؛ اگر برای این گره اجرایی در جریان است همان برمی‌گردد (دو اجرای هم‌زمان نمی‌شود) — مگر اینکه آن اجرا برای نسخهٔ
    قدیمیِ عامل ساخته شده باشد: آن متوقف می‌شود و اجرای تازه برای نسخهٔ فعلی ساخته می‌شود (گزارشِ نسخهٔ قدیمی نباید جلوی گزارشِ
    درستِ نسخهٔ تازه را بگیرد)."""
    load_all()
    caps = node.capabilities or {}
    run = active_run(node)
    if run is not None:
        if run_outdated(run, caps) and not update_in_flight(run):
            abort_run(run, "نسخهٔ عاملِ سرور عوض شد (%s ⇒ %s)؛ آزمونِ تازه برای نسخهٔ تازه ساخته شد." % (
                run.agent_version or "؟", caps.get("agent") or "؟"))
        else:
            return run
    chosen = [t for t in tests(deep or trigger == "deep") if not only or t.key in set(only)]
    if only:                                           # پیش‌نیازها هم می‌آیند
        keys = {t.key for t in chosen}
        grew = True
        while grew:
            grew = False
            for t in list(chosen):
                for dep in t.after:
                    if dep not in keys and dep in REGISTRY:
                        chosen.append(REGISTRY[dep])
                        keys.add(dep)
                        grew = True
        chosen.sort(key=lambda t: (t.order, t.key))
    run = SelfTestRun.objects.create(node=node, trigger=trigger, by=by[:60], agent_version=str(caps.get("agent") or "")[:20],
                                     code_id=node_code_id(caps))
    SelfTestResult.objects.bulk_create([
        SelfTestResult(run=run, key=t.key, label=t.label, group=t.group, order=i, optional=t.optional, state=S.PENDING)
        for i, t in enumerate(chosen)])
    advance(run)
    return run


# ───────────────────────────── گام‌ها

def _final(r: SelfTestResult, state: str, detail: str = "", **kw) -> None:
    r.state = state
    r.detail = detail[:1500]
    r.finished_at = timezone.now()
    for k, v in kw.items():
        setattr(r, k, v)
    r.save()


def _gpu_needed(t, ctx) -> bool:
    g = t.gpu_required
    try:
        return bool(g(ctx)) if callable(g) else bool(g)
    except Exception:  # noqa: BLE001
        return False


def _enqueue(node, spec) -> ComputeJob:
    tmp = Path(tempfile.mkdtemp(prefix="nm-selftest-"))
    try:
        files = {}
        for name, data in (spec.files or {}).items():
            p = tmp / name
            p.write_bytes(data)
            files[name] = str(p)
        return SV.enqueue(spec.kind, spec.payload, files, origin="selftest", priority=spec.priority, node=node.name, dedupe=False,
                          require_online=False, timeout_s=spec.timeout_s, category="selftest", max_attempts=1, max_wait_s=6 * 3600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _apply_verdict(t, r, ctx, v: Verdict, job=None) -> None:
    meta = ctx.meta(job) if job else {}
    device = v.device or meta.get("device", "")
    warning = meta.get("device_warning", "") or v.warning
    detail = v.detail
    ok = v.ok
    if ok and device == "cpu" and _gpu_needed(t, ctx):
        ok = False
        detail = "این آزمون باید روی کارت اجرا می‌شد ولی روی پردازنده اجرا شد: %s" % (meta.get("device_note") or "علتی گزارش نشد")
    elif ok and device == "mixed":
        warning = warning or ("بخشی از مدل روی پردازنده است: %s" % meta.get("device_note", ""))
    artifacts = QV.job_outputs(job)[:6] if job else []
    extra = dict(r.extra or {})
    extra.update(v.extra or {})
    if meta.get("gpu"):
        extra["gpu"] = {k: meta["gpu"].get(k) for k in ("util_avg", "util_max", "vram_max_mb", "vram_total_mb", "temp_max_c") if k in meta["gpu"]}
    state = S.PASSED if ok else (S.SKIPPED if v.skip else S.FAILED)
    _final(r, state, detail, device=device[:12], warning=warning[:300], artifacts=artifacts, extra=extra,
           seconds=(job.run_s if job and job.run_s is not None else r.seconds))


def _evaluate_job(t, r, ctx, job) -> None:
    if job.state == ComputeJob.State.COMPLETED:
        try:
            v = t.check(ctx, job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("selftest %s: check crashed", t.key)
            v = Verdict.failed("سنجشِ نتیجه خطا داد: %s" % exc)
        _apply_verdict(t, r, ctx, v, job)
    elif job.state == ComputeJob.State.FAILED:
        _final(r, S.FAILED, (job.error or "کار ناموفق بود")[-600:], seconds=job.run_s,
               device=str(ctx.meta(job).get("device") or "")[:12])
    else:
        _final(r, S.FAILED, "کار لغو شد: %s" % ((job.error or job.message or "")[:300]), seconds=job.run_s)


def _bootstrap_note(node, kind):
    boot = (node.capabilities or {}).get("bootstrap") or {}
    why = (boot.get("blocked_kinds") or {}).get(kind)
    if not why:
        return None
    feature = why.split(":", 1)[0]
    feat = (boot.get("features") or {}).get(feature) or {}
    return feature, feat


def _step_queued(t, r, ctx, job) -> None:
    node = ctx.node
    now = timezone.now()
    age = (now - (r.started_at or now)).total_seconds()
    if job.state in (ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING):
        if r.state != S.RUNNING:
            r.state = S.RUNNING
            r.save(update_fields=["state"])
        if age > max(job.timeout_s, 300) * 2:
            SV.cancel(job, "آزمونِ خودکار: کار بیش از دو برابرِ مهلت طول کشید.")
            _final(r, S.FAILED, "کار بیش از مهلتش طول کشید و لغو شد (%d ثانیه)" % age)
        return
    # هنوز در صف است
    if not node.online:
        return                                             # گره خاموش است؛ منتظر (اجرا اگر خیلی بماند متوقف می‌شود)
    note = _bootstrap_note(node, job.kind)
    if note:
        feature, feat = note
        title = feat.get("title") or feature
        if feat.get("state") == "failed":
            bad = next((i for i in feat.get("items", []) if i.get("state") == "failed"), {})
            SV.cancel(job, "آزمونِ خودکار: نصبِ پیش‌نیاز شکست خورد.")
            _final(r, S.FAILED, "نصبِ «%s» شکست خورد: %s (در پنل «تلاش دوباره» را بزنید)" % (title, bad.get("error") or "؟"))
            return
        if age > t.wait_install_s:
            SV.cancel(job, "آزمونِ خودکار: نصب تمام نشد.")
            _final(r, S.FAILED, "نصبِ «%s» تا %d ساعت تمام نشد" % (title, t.wait_install_s // 3600))
            return
        r.state = S.WAITING
        r.detail = "منتظرِ پایانِ نصبِ «%s» ..." % title
        r.save(update_fields=["state", "detail"])
        return
    if SV.kind_unsupported(node, job) and age > 300:
        if _update_pending(node) and age <= t.wait_install_s:
            r.state = S.WAITING
            r.detail = "عاملِ این سرور هنوز نوعِ «%s» را نمی‌شناسد؛ منتظرِ به‌روزرسانیِ خودکار ..." % job.kind
            r.save(update_fields=["state", "detail"])
            return
        SV.cancel(job, "آزمونِ خودکار: عاملِ گره این نوع کار را نمی‌شناسد.")
        _final(r, S.FAILED, "عاملِ این سرور (نسخهٔ %s) نوعِ «%s» را نمی‌شناسد؛ «به‌روزرسانی» را بزنید." % (
            (node.capabilities or {}).get("agent") or "؟", job.kind))
        return
    if SV.audio_blocked(node, job) or SV.matting_blocked(node, job):
        if age > BLOCK_WAIT_S:
            SV.cancel(job, "آزمونِ خودکار: مدل آماده نشد.")
            _final(r, S.FAILED, "مدلِ لازم تا نیم ساعت روی این سرور آماده (نصب/روشن) نشد")
        else:
            r.state = S.WAITING
            r.detail = "منتظرِ آماده شدنِ مدل روی سرور ..."
            r.save(update_fields=["state", "detail"])
        return
    if age > QUEUE_STALE_S:
        SV.cancel(job, "آزمونِ خودکار: کار در صف ماند.")
        _final(r, S.FAILED, "کار تا نیم ساعت از صف برداشته نشد (%s)" % ((job.message or "علت نامعلوم")[:200]))
        return
    if r.state != S.QUEUED:
        r.state = S.QUEUED
        r.detail = ""
        r.save(update_fields=["state", "detail"])


def _update_pending(node) -> bool:
    """به‌روزرسانیِ خودکارِ عامل در راه است؟ (بسته تازه‌تر از عامل، تنظیمِ خودکار روشن، عامل دستورِ به‌روزرسانی را می‌شناسد)"""
    try:
        from .. import autopilot

        return bool(autopilot.update_wanted(node)[0])
    except Exception:  # noqa: BLE001
        return False


def _hold(t, r, detail: str) -> bool:
    """آزمون هنوز نمی‌تواند شروع شود: «منتظر» با علت (با سقفِ زمان)؛ True برمی‌گرداند."""
    now = timezone.now()
    if r.started_at is None:
        r.started_at = now
    if (now - r.started_at).total_seconds() > t.wait_install_s:
        r.extra = {k: v for k, v in (r.extra or {}).items() if k != "gate"}
        _final(r, S.FAILED, "زمانِ انتظار تمام شد: %s" % detail)
        return True
    r.state = S.WAITING
    r.detail = detail[:1500]
    r.extra = {**(r.extra or {}), "gate": True}
    r.save()
    return True


def _install_hold(features, caps) -> str:
    """چیزی که هنوز مانعِ شروعِ آزمونی است که به این ویژگی‌های نصبِ خودکار تکیه دارد؛ '' یعنی راهی است."""
    feats = bootstrap_features(caps)
    age = agent_age_s(caps)
    if feats is None:
        if age is not None and age < 6 * 60:
            return "عاملِ سرور تازه بالا آمده و نصبِ خودکار را هنوز شروع نکرده ..."
        return ""                                  # عامل هرگز گزارش نداد؛ آزمونِ «نصبِ خودکار» همین را رد می‌کند
    for name in features:
        f = feats.get(name) or {}
        if f.get("applicable", True) and f.get("state") in BOOT_BUSY:
            return "منتظرِ پایانِ نصبِ «%s» ..." % (f.get("title") or name)
    if age is not None and age < YOUNG_AGENT_S:
        return "عاملِ سرور تازه بالا آمده؛ منتظرِ پایانِ بررسیِ نصب‌ها ..."
    return ""


def _gate(t, r, ctx) -> bool:
    """پیش از ساخته شدنِ آزمون: عاملِ گره آن را می‌شناسد و نصبِ خودکارِ پیش‌نیازهایش تمام است؟ True ⇒ این گام تمام شد (منتظر
    ماند یا نهایی شد) و آزمون نباید ساخته شود."""
    caps = ctx.caps
    if t.min_agent and not agent_at_least(caps, t.min_agent):
        have = caps.get("agent") or "؟"
        if _update_pending(ctx.node):
            return _hold(t, r, "عاملِ این سرور (نسخهٔ %s) این آزمون را نمی‌شناسد (از نسخهٔ %s به بعد)؛ منتظرِ به‌روزرسانیِ خودکار ..." % (
                have, t.min_agent))
        _final(r, S.SKIPPED if t.optional else S.FAILED,
               "عاملِ این سرور (نسخهٔ %s) این آزمون را نمی‌شناسد (نسخهٔ %s به بعد لازم است)؛ «به‌روزرسانی» را بزنید." % (have, t.min_agent))
        return True
    if t.needs_features and agent_at_least(caps, BOOT_MIN_AGENT):
        why = _install_hold(t.needs_features, caps)
        if why:
            return _hold(t, r, why)
    if (r.extra or {}).get("gate"):                # راه باز شد
        r.extra = {k: v for k, v in r.extra.items() if k != "gate"}
        r.started_at = None
        r.state = S.PENDING
        r.detail = ""
        r.save()
    return False


def _step_virtual(t, r, ctx) -> None:
    now = timezone.now()
    if r.started_at is None:
        r.started_at = now
    cctx = Ctx(ctx.node, ctx.run, ctx.results, result=r)
    try:
        v = t.virtual(cctx)
    except Exception as exc:  # noqa: BLE001
        logger.exception("selftest %s: virtual check crashed", t.key)
        v = Verdict.failed("سنجش خطا داد: %s" % exc)
    r.extra = {**(r.extra or {}), **(v.extra or {})}
    if v.wait:
        if (now - r.started_at).total_seconds() > t.wait_install_s:
            _final(r, S.FAILED, "زمانِ انتظار تمام شد: %s" % v.detail)
            return
        r.state = S.WAITING
        r.detail = v.detail[:1500]
        r.save()
        return
    _apply_verdict(t, r, ctx, v)


def _step(t, r, ctx) -> None:
    results = ctx.results
    if r.state == S.PENDING or (r.state == S.WAITING and (r.extra or {}).get("gate")):
        deps = [results[k] for k in t.after if k in results]
        bad = [d for d in deps if d.state in (S.FAILED, S.SKIPPED)]
        if bad:
            _final(r, S.SKIPPED, "آزمونِ پیش‌نیاز («%s») قبول نشد" % bad[0].label)
            return
        if any(not d.final for d in deps):
            return
        if t.final and any(not o.final for k, o in results.items() if k != r.key and not getattr(REGISTRY.get(k), "final", False)):
            return
        if ctx.node.online and _gate(t, r, ctx):          # عاملِ قدیمی / نصبِ در جریان: صبر (یا خطای روشن)، نه «ردشده»
            return
        ok, why = t.available(ctx.node)
        if not ok:
            _final(r, S.SKIPPED, why or "این قابلیت روی سرور نیست")
            return
        if not ctx.node.online:
            return
        if t.virtual:
            _step_virtual(t, r, ctx)
            return
        spec = t.build(ctx)
        if spec is None:
            _final(r, S.SKIPPED, "ورودیِ آزمون آماده نشد (پیش‌نیاز خروجی نداد)")
            return
        try:
            job = _enqueue(ctx.node, spec)
        except Exception as exc:  # noqa: BLE001
            _final(r, S.FAILED, "کار در صف گذاشته نشد: %s" % exc)
            return
        r.job_uid = job.uid
        r.state = S.QUEUED
        r.started_at = timezone.now()
        r.detail = ""
        r.save()
        return
    if t.virtual:
        _step_virtual(t, r, ctx)
        return
    job = ComputeJob.objects.filter(uid=r.job_uid).first() if r.job_uid else None
    if job is None:
        _final(r, S.FAILED, "کارِ آزمون پیدا نشد")
        return
    if job.final:
        _evaluate_job(t, r, ctx, job)
        return
    _step_queued(t, r, ctx, job)


def advance(run: SelfTestRun) -> dict:
    """یک گام برای یک اجرا. {"done": bool, "final": n, "total": n}"""
    load_all()
    if run.state != SelfTestRun.State.RUNNING:
        return {"done": True}
    node = ComputeNode.objects.get(pk=run.node_id)
    results = {r.key: r for r in run.results.order_by("order")}
    ctx = Ctx(node, run, results)
    for key, r in list(results.items()):
        if r.final:
            continue
        t = REGISTRY.get(key)
        if t is None:
            _final(r, S.SKIPPED, "این آزمون دیگر تعریف نشده است")
            continue
        try:
            _step(t, r, ctx)
        except Exception as exc:  # noqa: BLE001 — یک آزمونِ خراب بقیه را نمی‌خواباند
            logger.exception("selftest %s crashed", key)
            _final(r, S.FAILED, "خطای داخلی در آزمون: %s" % exc)
    left = [r for r in results.values() if not r.final]
    if left and node.last_seen and (timezone.now() - node.last_seen).total_seconds() > RUN_STALE_S:
        for r in left:
            if r.job_uid:
                job = ComputeJob.objects.filter(uid=r.job_uid).first()
                if job and not job.final:
                    SV.cancel(job, "آزمونِ خودکار: سرور خاموش شد.")
            _final(r, S.SKIPPED, "سرور خاموش شد؛ آزمون ناتمام ماند")
        run.state = SelfTestRun.State.ABORTED
        run.finished_at = timezone.now()
        run.note = "سرور بیش از %d دقیقه خاموش بود" % (RUN_STALE_S // 60)
        run.save()
        return {"done": True, "final": len(results), "total": len(results)}
    if not left:
        finish_run(run, node)
    return {"done": not left, "final": len(results) - len(left), "total": len(results)}


def finish_run(run: SelfTestRun, node=None) -> None:
    node = node or run.node
    run.state = SelfTestRun.State.FINISHED
    run.finished_at = timezone.now()
    requeued = dict(run.requeued or {})
    try:
        if ComputeSettings.get().requeue_after_pass:
            for r in run.results.filter(state=S.PASSED):
                t = REGISTRY.get(r.key)
                if t and t.requeue and r.key not in requeued:
                    requeued[r.key] = requeue_after_pass(run, t)
    except Exception:  # noqa: BLE001
        logger.exception("selftest: requeue after pass failed")
    run.requeued = requeued
    run.save()


def advance_all() -> dict:
    out = {"runs": 0, "finished": 0}
    for run in SelfTestRun.objects.filter(state=SelfTestRun.State.RUNNING):
        out["runs"] += 1
        try:
            if advance(run).get("done"):
                out["finished"] += 1
        except Exception:  # noqa: BLE001
            logger.exception("selftest run %s: advance failed", run.pk)
    return out


def rerun(run: SelfTestRun, key: str) -> SelfTestResult | None:
    """«دوباره» برای یک آزمون: همان ردیف از نو (پیش‌نیازهای قبول‌شده می‌مانند؛ آزمون‌های «ردشده به‌خاطرِ پیش‌نیاز» هم از نو)."""
    load_all()
    r = run.results.filter(key=key).first()
    if r is None:
        return None
    if r.job_uid:
        job = ComputeJob.objects.filter(uid=r.job_uid).first()
        if job and not job.final:
            SV.cancel(job, "آزمونِ خودکار: دوباره درخواست شد.")
    todo = [r] + [x for x in run.results.filter(state=S.SKIPPED) if key in getattr(REGISTRY.get(x.key), "after", ())]
    for x in todo:
        x.state = S.PENDING
        x.job_uid = None
        x.detail = ""
        x.device = ""
        x.warning = ""
        x.seconds = None
        x.artifacts = []
        x.extra = {}
        x.started_at = None
        x.finished_at = None
        x.save()
    run.state = SelfTestRun.State.RUNNING
    run.finished_at = None
    requeued = dict(run.requeued or {})
    requeued.pop(key, None)
    run.requeued = requeued
    run.save()
    advance(run)
    return SelfTestResult.objects.get(pk=r.pk)


# ───────────────────────────── گزارش برای پنل

def result_json(r: SelfTestResult) -> dict:
    t = REGISTRY.get(r.key)
    return {"key": r.key, "label": r.label, "group": r.group, "state": r.state, "state_label": r.get_state_display(),
            "optional": r.optional, "detail": r.detail, "device": r.device, "warning": r.warning, "seconds": r.seconds,
            "artifacts": r.artifacts, "extra": {k: v for k, v in (r.extra or {}).items() if k in ("gpu", "tokens_per_s", "before", "after", "action", "audio_seconds")},
            "job": str(r.job_uid) if r.job_uid else "", "describe": getattr(t, "describe", "") if t else "",
            "deep": bool(getattr(t, "deep", False)), "started": r.started_at, "finished": r.finished_at}


def summary_of(results) -> dict:
    required = [r for r in results if not r.optional and r.state != S.SKIPPED]
    passed = [r for r in results if r.state == S.PASSED]
    failed = [r for r in results if r.state == S.FAILED]
    return {"total": len(results), "passed": len(passed), "failed": len(failed), "skipped": len([r for r in results if r.state == S.SKIPPED]),
            "pending": len([r for r in results if not r.final]),
            "required_failed": len([r for r in failed if not r.optional]),
            "ok": bool(results) and all(r.final for r in results) and not any(not r.optional for r in failed) and len(required) > 0,
            "warnings": len([r for r in results if r.warning])}


def run_json(run: SelfTestRun, with_results: bool = True) -> dict:
    results = list(run.results.order_by("order"))
    caps = run.node.capabilities or {}
    d = {"id": run.pk, "node": run.node.name, "node_id": run.node_id, "trigger": run.trigger, "state": run.state, "by": run.by,
         "state_label": run.get_state_display(), "agent_version": run.agent_version, "code_id": run.code_id, "created": run.created_at,
         "finished": run.finished_at, "note": run.note, "requeued": run.requeued or {}, "summary": summary_of(results),
         "node_online": run.node.online, "node_agent": caps.get("agent")}
    if with_results:
        d["results"] = [result_json(r) for r in results]
    return d

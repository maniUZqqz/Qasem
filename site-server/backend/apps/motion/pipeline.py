"""خطِ تولید پیش از رندر: طرح ⇒ [کنترلِ کیفیتِ قاعده‌ای و اصلاحِ خودکار] ⇒ [صدا: گوینده، موسیقی، بیت، مخلوط] ⇒ طرحِ نهایی برای رندر.

روی هر رندرِ قالبی/هوشمند اجرا می‌شود (tasks.prepare_render_task). هیچ‌جا نمی‌ایستد: بی‌مرورگر فقط قاعده‌های بدونِ هندسه اجرا می‌شوند، بی‌گوینده
رندر بی‌صدا ادامه می‌یابد (با پیامِ روشن)، و فقط وقتی گویندهٔ انتخاب‌شده روی گره ساخته می‌شود و گره خاموش است رندر «منتظرِ گره» می‌ماند.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from django.utils import timezone

from . import plans, qa, qa_browser, runner, sound, specs
from .models import MotionRender

logger = logging.getLogger(__name__)


def audio_root() -> Path:
    d = runner.data_dir() / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mix_path(render: MotionRender) -> Path | None:
    if not render.audio_dir:
        return None
    p = runner.data_dir() / render.audio_dir / "mix.m4a"
    return p if p.is_file() else None


def run_qa(store, spec: dict, *, tag: str, max_total: float, geometry: bool = True, cancelled=None, on_round=None) -> dict:
    """حلقهٔ QA روی یک طرح؛ مرورگرِ سایت آماده نباشد فقط قاعده‌های بدونِ مرورگر. ⇒ گزارش (با report["spec"] = طرحِ اصلاح‌شده)."""
    ok, why = qa_browser.available() if geometry else (False, "خاموش")
    work = Path(tempfile.mkdtemp(prefix="nm-motion-qa-"))
    lock = None
    try:
        measure = None
        if ok:
            lock = runner.SiteLock()
            try:
                lock.acquire(cancelled=cancelled)
                measure = qa_browser.make_measure(store, workdir=work, media_dir=qa_browser.media_dir_for(store.pk, tag), cancelled=cancelled)
            except runner.RenderError as exc:
                ok, why = False, str(exc)
        report = qa.run_loop(spec, measure=measure, max_total=max_total, on_round=on_round)
        if not ok and geometry:
            report["geometry_skipped"] = why
        return report
    finally:
        if lock:
            lock.release()
        shutil.rmtree(work, ignore_errors=True)


def slim_report(report: dict) -> dict:
    out = {k: v for k, v in report.items() if k != "spec"}
    out["summary"] = qa.summary_fa(report)
    out["at"] = timezone.now().isoformat()
    return json.loads(json.dumps(out, default=str))


def _set(render: MotionRender, state: str, message: str, **fields) -> None:
    render.state, render.message = state, message[:300]
    for k, v in fields.items():
        setattr(render, k, v)
    render.save(update_fields=["state", "message", "updated_at", *fields])


def prepare_render(render: MotionRender, *, synth=None, asr=None, geometry: bool | None = None) -> str:
    """⇒ "ready" | "waiting" (صدا منتظرِ گره) | "failed". طرحِ نهایی روی render.spec نوشته می‌شود.
    geometry: بررسیِ هندسیِ فریم‌های واقعی (مرورگر). None = خودکار؛ زیرِ آزمون خاموش است (هر آزمونِ API مرورگر باز نکند) مگر آزمونِ واقعی True بدهد."""
    from django.conf import settings

    from . import services

    geo = geometry if geometry is not None else not getattr(settings, "IS_TEST", False)

    opts = render.options or {}
    cap = specs.MAX_TOTAL_S_SITE if render.target == MotionRender.Target.SITE else specs.MAX_TOTAL_S_NODE
    spec = render.spec
    store = render.store
    _set(render, MotionRender.State.PREPARING, "کنترلِ کیفیتِ طرح…")

    def cancelled() -> bool:
        return MotionRender.objects.filter(pk=render.pk, state=MotionRender.State.CANCELLED).exists()

    # ── ۱) کنترلِ کیفیت
    if opts.get("qa", True):
        try:
            report = run_qa(store, spec, tag=f"render{render.pk}", max_total=cap, geometry=geo, cancelled=cancelled)
            spec = report["spec"]
            render.qa = slim_report(report)
        except Exception as exc:  # noqa: BLE001 — QA هیچ‌وقت رندر را نمی‌اندازد
            logger.exception("motion: QA of render %s failed", render.pk)
            render.qa = {"summary": f"کنترلِ کیفیت اجرا نشد: {exc}"[:300], "rounds": [], "remaining": [], "fixed": 0}
        render.save(update_fields=["qa", "updated_at"])
        if cancelled():
            return "failed"
    # ── ۲) صدا
    audio_note = ""
    if sound.wanted(spec):
        _set(render, MotionRender.State.PREPARING, "ساختِ صدا (گوینده، موسیقی، مخلوط)…")
        work = audio_root() / str(render.pk)
        shutil.rmtree(work, ignore_errors=True)
        try:
            res = sound.prepare(store, render.user, spec, work, synth=synth, asr=asr,
                                progress=lambda p, m: MotionRender.objects.filter(pk=render.pk).update(message=m[:300], progress=round(p * 0.2, 3)))
            spec = res["spec"]
            render.audio_info = res["info"] | {"mix": res["info"].get("mix"), "has_mix": bool(res["mix"])}
            render.audio_dir = f"audio/{render.pk}" if res["mix"] else ""
        except sound.AudioPending as exc:
            _set(render, MotionRender.State.WAITING_NODE, str(exc))
            return "waiting"
        except Exception as exc:  # noqa: BLE001 — صدا نشد ⇒ ویدیوی بی‌صدا با هشدارِ روشن
            logger.exception("motion: audio of render %s failed", render.pk)
            audio_note = f"صدا ساخته نشد ({exc}); ویدیو بی‌صدا رندر می‌شود."
            render.audio_info = {"error": str(exc)[:300]}
            render.audio_dir = ""
        render.save(update_fields=["audio_info", "audio_dir", "updated_at"])
    # ── ۳) طرحِ نهایی
    try:
        final = specs.normalize_spec(spec, max_total=cap)
    except specs.SpecError as exc:
        services.fail(render, f"پس از کنترلِ کیفیت/صدا مدتِ ویدیو از سقف گذشت: {exc}")
        return "failed"
    changed = {k: v for k, v in final.items() if k != "total_s"} != {k: v for k, v in render.spec.items() if k != "total_s"}
    render.spec = final
    render.save(update_fields=["spec", "updated_at"])
    if changed and render.plan_id:
        try:
            plans.commit(render.plan, final, label="اصلاحِ خودکارِ کیفیت و صدا" + (f" — {qa.summary_fa(render.qa)}" if render.qa else "")[:90], source="qa")
        except plans.PlanError:
            pass
    if audio_note:
        MotionRender.objects.filter(pk=render.pk).update(message=audio_note[:300])
    return "ready"

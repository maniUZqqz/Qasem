"""نقدِ بصری: ۳ تا ۶ فریمِ کلیدی + طرح ⇒ مدلِ بینایی (qwen3-vl مالک روی گره؛ متیس پشتیبان) ⇒ مشکل‌ها + patch ⇒ اعمال ⇒ فریم‌های تازه، حداکثر ۳ دور.

مدل در دسترس نباشد (گره خاموش و متیس بی‌اعتبار) حلقه «منتظر» می‌ماند و هر ۶۰ ثانیه خودش دوباره می‌سنجد (تا ۴۸ ساعت)؛ با روشن‌شدنِ گره خودکار اجرا می‌شود.
نتیجه (تاریخچهٔ دورها با فریم‌های «قبل/بعد») روی MotionPlan.critique می‌ماند و پنل نشانش می‌دهد؛ هر patch یک نسخهٔ قابل‌برگشت از طرح است.
بدونِ ابزارِ رندرِ سایت (فریم‌ها) نقد ممکن نیست و حالتش «unavailable» با دلیلِ فارسی است؛ قواعدِ بدونِ مدل (qa.py) همیشه جدا اجرا می‌شوند.
"""
from __future__ import annotations

import base64
import json
import logging
import tempfile
from pathlib import Path

from datetime import datetime

from django.utils import timezone

from . import ai, plans, promptkit, qa, qa_browser, specs
from . import patch as patch_mod
from .models import MotionPlan

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
MAX_FRAMES = 6
RETRY_S = 60
GIVE_UP_HOURS = 48

SYSTEM = """You are a strict art director reviewing frames of a Persian motion-graphics video made from a SCENE PLAN (JSON). Each image is one frame; the list below tells which scene
(0-based index) each image shows, in order. Look for REAL visual problems only: text clipped or overflowing, two texts overlapping, low contrast, text too small to read on a phone,
unbalanced or empty layout, too many things at once, colours that clash with the style. If everything is fine answer verdict "ok" with no ops.
Reply with ONE JSON object {"verdict":"ok"|"fix","issues":[{"scene":int,"problem":"<Persian sentence>","severity":"low"|"medium"|"high"}],"ops":[...]}.
Fix ONLY the scenes that have issues with a JSON PATCH (a few ops at most, never rewrite the whole plan, never invent facts). The patch language:
""" + promptkit.PATCH_GUIDE.split("Ops:", 1)[1].split("Reply with", 1)[0].strip()


def schema() -> dict:
    ops = promptkit.patch_schema()["properties"]["ops"]
    return {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["ok", "fix"]},
        "issues": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
            "scene": {"type": "integer"}, "problem": {"type": "string"}, "severity": {"type": "string", "enum": ["low", "medium", "high"]}}, "required": ["scene", "problem"]}},
        "ops": ops}, "required": ["verdict"]}


def pick_frames(spec: dict, limit: int = MAX_FRAMES) -> list:
    """۳ تا ۶ صحنه: اولی، آخری و پرمحتواترین‌ها؛ فریمِ «late» (پایانِ ورود) هر کدام."""
    n = len(spec["scenes"])
    order = sorted(range(n), key=lambda i: -qa._scene_words(spec["scenes"][i]))
    chosen = {0, n - 1}
    for i in order:
        if len(chosen) >= min(limit, n):
            break
        chosen.add(i)
    keys = qa.key_frames(spec, per_scene=2)
    return [k for k in keys if k["scene"] in chosen and k["kind"] == "late"]


def _b64(shot) -> str:
    """تصویرِ فریم برای مدل: از فایلِ روی دیسک اگر هست، وگرنه از خودِ PIL."""
    import io

    buf = io.BytesIO()
    im = shot.get("_image")
    if im is None:
        raise ValueError("تصویرِ فریم در دسترس نیست.")
    im.convert("RGB").save(buf, "JPEG", quality=84)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ask(prov, spec: dict, shots: list) -> dict:
    listing = ", ".join(f"image {k + 1} = scene {s['scene']}" for k, s in enumerate(shots))
    user = f"Images: {listing}.\nPLAN:\n{promptkit.compact_plan(spec)}\nStyle: {spec['style']}; aspect {spec['aspect']}; platform {spec.get('platform') or 'none'}."
    data = ai._call_json(prov, user, SYSTEM, schema(), temperature=0.2, num_predict=1100, images=[_b64(s) for s in shots])
    if not isinstance(data, dict):
        raise ValueError("پاسخِ مدلِ بینایی شیء نبود.")
    issues = [{"scene": int(i.get("scene", 0)), "problem": str(i.get("problem", ""))[:240], "severity": i.get("severity") if i.get("severity") in ("low", "medium", "high") else "medium"}
              for i in (data.get("issues") or []) if isinstance(i, dict)][:12]
    ops = data.get("ops") if isinstance(data.get("ops"), list) else []
    return {"verdict": "fix" if (data.get("verdict") == "fix" and ops) else "ok", "issues": issues, "ops": ops[: patch_mod.MAX_OPS]}


def apply_valid(spec: dict, ops: list) -> tuple:
    """هر op جداگانه آزموده می‌شود؛ معتبرها به‌ترتیب اعمال می‌شوند. ⇒ (spec تازه, ops اعمال‌شده, ops رد‌شده)."""
    cur, ok, bad = spec, [], []
    for op in ops:
        try:
            cur = patch_mod.apply_patch(cur, [op])
            ok.append(op)
        except patch_mod.PatchError as exc:
            bad.append({"op": op, "why": str(exc)})
    return cur, ok, bad


def _meta(shots: list) -> list:
    return [{"scene": s["scene"], "frame": s["frame"], "image_rel": s.get("image_rel", "")} for s in shots]


def run(plan: MotionPlan, *, provider=None, measure=None, max_rounds: int = MAX_ROUNDS) -> dict:
    """یک اجرای کاملِ نقد روی طرح؛ وضعیت را در plan.critique می‌نویسد و همان را برمی‌گرداند."""
    store = plan.store
    state = dict(plan.critique or {})
    rounds = list(state.get("rounds") or []) if state.get("state") == "running" else []
    state.update(state="running", message="نقدِ تصویری در حال اجراست…", started_at=state.get("started_at") or timezone.now().isoformat())
    _save(plan, state)
    ok, why = qa_browser.available() if measure is None else (True, "")
    if not ok:
        return _finish(plan, state, "unavailable", "نقدِ تصویری به ابزارِ رندرِ سایت (برای گرفتنِ فریم) نیاز دارد: " + why)
    try:
        prov = provider if provider is not None else ai.get_provider(store, kind="vision")
        avail = getattr(prov, "availability", None)
        if callable(avail):
            good, reason = avail()
            if not good:
                raise ai.AIUnavailable(reason or ai.MSG_UNAVAILABLE)
    except Exception as exc:  # noqa: BLE001
        return _wait(plan, state, ai.explain(exc))
    tmp = Path(tempfile.mkdtemp(prefix="nm-motion-crit-"))
    try:
        from . import runner

        lock = None
        if measure is None:
            media_dir = qa_browser.media_dir_for(store.pk, f"plan{plan.pk}-critique")
            measure = qa_browser.make_measure(store, workdir=tmp, media_dir=media_dir, prefix="c", frames_fn=lambda s: pick_frames(s))
            lock = runner.SiteLock()
            lock.acquire()
        try:
            spec = plan.spec
            shots = measure(spec)
            for n in range(len(rounds) + 1, max_rounds + 1):
                try:
                    res = ask(prov, spec, shots)
                except Exception as exc:  # noqa: BLE001 — مدل میانهٔ کار از دسترس رفت
                    if rounds:
                        return _finish(plan, state | {"rounds": rounds}, "done", "مدل در دورِ بعد جواب نداد؛ نتیجهٔ دورهای قبل نگه داشته شد.")
                    return _wait(plan, state, ai.explain(exc))
                rec = {"n": n, "verdict": res["verdict"], "issues": res["issues"], "ops": res["ops"], "applied": [], "rejected": [], "before": _meta(shots), "after": []}
                if res["verdict"] == "ok":
                    rounds.append(rec)
                    state["rounds"] = rounds
                    return _finish(plan, state, "done", "مدلِ بینایی مشکلی ندید." if not res["issues"] else "مدلِ بینایی فقط ایرادهای جزئی دید.")
                new, applied, rejected = apply_valid(spec, res["ops"])
                rec["applied"], rec["rejected"] = applied, rejected
                if not applied or new == spec:
                    rounds.append(rec)
                    state["rounds"] = rounds
                    return _finish(plan, state, "done", "ایرادها گزارش شد ولی تغییرِ قابل‌اعمالی پیشنهاد نشد.")
                plan = plans.commit(plan, new, label=f"نقدِ تصویری (دور {n}): " + "؛ ".join(patch_mod.diff_summary(spec, new))[:110], source="critique", ops=applied)
                spec = plan.spec
                shots = measure(spec)
                rec["after"] = _meta(shots)
                rounds.append(rec)
                state["rounds"] = rounds
                _save(plan, state)
            return _finish(plan, state, "done", f"{max_rounds} دورِ نقد انجام شد.")
        finally:
            if lock:
                lock.release()
    except Exception as exc:  # noqa: BLE001
        logger.exception("motion critique of plan %s failed", plan.pk)
        return _finish(plan, state, "failed", f"نقدِ تصویری ناموفق بود: {exc}"[:300])
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _save(plan: MotionPlan, state: dict) -> None:
    MotionPlan.objects.filter(pk=plan.pk).update(critique=json.loads(json.dumps(state, default=str)), updated_at=timezone.now())
    plan.critique = state


def _finish(plan, state, name: str, message: str) -> dict:
    state.update(state=name, message=message, finished_at=timezone.now().isoformat())
    _save(plan, state)
    return state


def _wait(plan, state, reason: str) -> dict:
    """مدل نیست ⇒ «منتظر»؛ تسکِ Celery هر ۶۰ ثانیه دوباره می‌آید (tasks.critique_task)."""
    started = state.get("started_at")
    try:
        age = (timezone.now() - datetime.fromisoformat(started)).total_seconds() / 3600 if started else 0
    except Exception:  # noqa: BLE001
        age = 0
    if age > GIVE_UP_HOURS:
        return _finish(plan, state, "unavailable", "مدلِ بینایی تا ۴۸ ساعت در دسترس نبود؛ دوباره درخواست بدهید.")
    from .ai import tidy

    state.update(state="waiting", message=tidy("منتظرِ مدلِ بینایی (سرورِ پردازش خاموش است یا هوش مصنوعیِ ابری در دسترس نیست)؛ با آماده‌شدنش خودکار اجرا می‌شود. " + reason[:160]))
    state["attempts"] = int(state.get("attempts") or 0) + 1
    _save(plan, state)
    return state


def request(plan: MotionPlan) -> dict:
    """درخواستِ نقد: وضعیت را «waiting» می‌گذارد و تسک را زمان‌بندی می‌کند (tasks.critique_task)."""
    state = {"state": "waiting", "message": "در صفِ نقدِ تصویری…", "rounds": [], "started_at": timezone.now().isoformat(), "attempts": 0}
    _save(plan, state)
    return state


__all__ = ["run", "request", "ask", "pick_frames", "specs"]

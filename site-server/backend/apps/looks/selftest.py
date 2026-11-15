"""خودآزمونِ «سبک تصویر» روی سرورِ پردازش: یک تصویرِ نمونهٔ ۵۱۲×۵۱۲ از یک سبک (همان مسیرِ ساختِ تصویرِ نمونهٔ سبک‌ها).

همان قراردادِ ``apps.thumbs.selftest``: ``spec(caps)`` یک کارِ کوچکِ واقعی می‌دهد و ``check(job)`` درستیِ نتیجه را می‌سنجد؛ آزمونِ پذیرشِ
مرکزی (``apps/compute/selftests/looks.py``) و اجرای خودکارِ خودِ همین اپ (beat هر ۵ دقیقه، ``auto_step``) از آن استفاده می‌کنند.

    from apps.looks import selftest
    s = selftest.spec()                       # {"kind": "comfy.graph", "payload": {...}, "expect": {...}, ...}
    job = compute.enqueue_durable(s["kind"], s["payload"], {}, origin=s["origin"], timeout_s=s["timeout_s"])
    ok, message = selftest.check(job)         # (True, "…") یا (False, دلیلِ فارسی)

شرطِ قبولی: کار تمام شده، خروجی یک PNG است، بزرگ‌تر از ۱۰ کیلوبایت، ۵۱۲×۵۱۲، و یک‌رنگ نیست.
"""
from __future__ import annotations

from pathlib import Path

from . import compose, library, samples

FEATURE = "looks.samples"
ORIGIN = "selftest-looks"
LOOK = "cinematic_realistic"
SIZE = (512, 512)
STEPS = 10
SEED = 4321
MIN_BYTES = 10_000
MIN_STD = 6.0
TIMEOUT_S = 900


def spec(caps=None) -> dict:
    from apps.thumbs import aibg

    c = compose.compose(LOOK, "SAMPLE")
    prompt = library.join(samples.SUBJECT, c["positive"])
    choice = aibg.txt2img_choice(caps if caps is not None else aibg.node_caps())
    graph = aibg.build_graph(choice, prompt, SEED, SIZE, steps=STEPS, guidance=samples.guidance_for(c["hints"]), prefix="nm/selftest-looks")
    return {
        "feature": FEATURE, "title_fa": "سبک تصویر: تصویرِ نمونه (FLUX)", "kind": samples.JOB_KIND, "origin": ORIGIN, "timeout_s": TIMEOUT_S,
        "payload": {"graph": graph, "uploads": [], "x_looksample": {"selftest": True, "key": LOOK, "seed": SEED, "size": list(SIZE), "engine": choice["label"]}},
        "expect": {"size": list(SIZE), "min_bytes": MIN_BYTES, "min_std": MIN_STD},
        "needs": ["comfyui", "FLUX dev (چک‌پوینتِ fp8 یا UNET)"],
    }


def check(job) -> tuple[bool, str]:
    """نتیجهٔ کارِ خودآزمون را می‌سنجد. ⇒ (قبول؟، پیامِ فارسی)."""
    import numpy as np
    from PIL import Image

    from apps.compute.models import ComputeJob
    from apps.photoedit import services as photo

    if job.state != ComputeJob.State.COMPLETED:
        return False, f"کار تمام نشده یا ناموفق بود ({job.state}): {(job.error or job.message or '')[:200]}"
    _meta, path = photo._image_output(job)
    if path is None or not Path(path).is_file():
        return False, "سرورِ پردازش هیچ تصویری پس نفرستاد."
    size_b = Path(path).stat().st_size
    try:
        with Image.open(path) as im:
            im.load()
            fmt = im.format
            img = im.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return False, f"فایلِ تصویر خوانده نشد: {exc}"
    if fmt != "PNG":
        return False, f"خروجی PNG نیست ({fmt})."
    if list(img.size) != list(SIZE):
        return False, f"اندازهٔ تصویر {img.size[0]}×{img.size[1]} است، انتظار {SIZE[0]}×{SIZE[1]} بود."
    arr = np.asarray(img.convert("L"), dtype=np.float32)
    if float(arr.std()) < MIN_STD:
        return False, "تصویر خالی یا یک‌رنگ است (انحرافِ معیارِ روشنایی خیلی کم)."
    if size_b <= MIN_BYTES:
        return False, f"فایلِ تصویر خیلی کوچک است ({size_b} بایت)؛ تصویرِ واقعی باید بزرگ‌تر از ۱۰ کیلوبایت باشد."
    return True, f"تصویرِ {SIZE[0]}×{SIZE[1]} ({size_b // 1024} کیلوبایت) ساخته شد (میانگین {arr.mean():.0f}، پراکندگی {arr.std():.0f})."


def enqueue():
    """خودآزمون را در صفِ ماندگار می‌گذارد (گره خاموش ⇒ منتظر می‌ماند). ⇒ ComputeJob."""
    from apps.compute import services as compute

    s = spec()
    return compute.enqueue_durable(s["kind"], s["payload"], {}, origin=s["origin"], timeout_s=s["timeout_s"], dedupe=False, priority=40)


def latest():
    from apps.compute.models import ComputeJob

    return ComputeJob.objects.filter(origin=ORIGIN).order_by("-created_at").first()


# ───────────────────────────── اجرای خودکار

RETEST_OK_S = 7 * 86400
RETEST_FAIL_S = 6 * 3600
_FINISHED = ("COMPLETED", "FAILED", "CANCELLED")


def _verdict(job) -> dict | None:
    from django.utils import timezone

    if job.state not in _FINISHED:
        return None
    got = (job.result or {}).get("selftest")
    if isinstance(got, dict) and "ok" in got:
        return got
    ok, message = check(job)
    got = {"ok": ok, "message": message, "at": timezone.now().isoformat()}
    job.result = {**(job.result or {}), "selftest": got}
    job.save(update_fields=["result", "updated_at"])
    return got


def status() -> dict:
    """برای پنل: ``{state: none|waiting|running|ok|failed, message}``."""
    job = latest()
    if job is None:
        return {"state": "none", "message": "آزمونِ خودکارِ تصویرِ نمونهٔ سبک‌ها هنوز اجرا نشده؛ وقتی سرورِ پردازش روشن شود خودش اجرا می‌شود."}
    if job.state in ("QUEUED", "CLAIMED"):
        return {"state": "waiting", "message": "آزمونِ خودکار در صفِ سرورِ پردازش است و با روشن‌شدنش اجرا می‌شود."}
    if job.state == "RUNNING":
        return {"state": "running", "message": "آزمونِ خودکار هم‌اکنون روی سرورِ پردازش در حالِ اجراست."}
    v = _verdict(job) or {"ok": False, "message": "نتیجهٔ آزمون نامعلوم است."}
    return {"state": "ok" if v["ok"] else "failed", "message": ("آزمونِ خودکار قبول شد: " if v["ok"] else "آزمونِ خودکار رد شد: ") + v["message"],
            "at": v.get("at", "")}


def auto_step(now=None) -> dict:
    """یک گامِ خودکار: کارِ آزمون را هر وقت لازم است در صفِ ماندگار می‌گذارد و نتیجهٔ کارِ تمام‌شده را می‌سنجد."""
    from django.utils import timezone

    now = now or timezone.now()
    job = latest()
    if job is not None and job.state in ("QUEUED", "CLAIMED", "RUNNING"):
        return {"action": "wait", "job": str(job.uid)}
    verdict = _verdict(job) if job is not None else None
    if job is not None and verdict is not None:
        age = (now - (job.finished_at or job.created_at)).total_seconds()
        if age < (RETEST_OK_S if verdict["ok"] else RETEST_FAIL_S):
            return {"action": "idle", "ok": verdict["ok"]}
    try:
        new = enqueue()
    except Exception as exc:  # noqa: BLE001 — GraphError (مدل نیست)، گرهٔ ComfyUI ثبت نیست، صف…
        return {"action": "skip", "why": str(exc)[:300]}
    return {"action": "enqueued", "job": str(new.uid)}

"""خودآزمونِ بخشِ «پس‌زمینهٔ هوش مصنوعی» ِ تامنیل‌ساز روی سرورِ پردازش.

وقتی گره روشن شد، آزمونِ پذیرشِ خودکارِ سرورِ پردازش (``apps.compute.selftests``، اگر در این نسخه هست) یا اسکریپتِ استقرار از همین
ماژول استفاده می‌کند: ``spec(caps)`` یک کارِ کوچکِ واقعی (FLUX، ۵۱۲×۵۱۲، چند گام) می‌دهد و ``check(job)`` درستیِ نتیجه را می‌سنجد.

    from apps.thumbs import selftest
    s = selftest.spec()                       # {"kind": "comfy.graph", "payload": {...}, "expect": {...}, ...}
    job = compute.enqueue_durable(s["kind"], s["payload"], {}, origin=s["origin"], timeout_s=s["timeout_s"])
    ...                                       # منتظرِ پایانِ کار
    ok, message = selftest.check(job)         # (True, "…") یا (False, دلیلِ فارسی)

هیچ نوعِ کارِ تازه‌ای در عاملِ گره لازم نیست؛ همان ``comfy.graph`` است که «پرکردنِ هوشمند» هم دارد.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from apps.photoedit import services as photo

from . import aibg

FEATURE = "thumbnails.ai_background"
ORIGIN = "selftest-thumbbg"
SIZE = (512, 512)
STEPS = 10
SEED = 1234
PROMPT = "a smooth soft blue and orange gradient studio background, empty, clean, no text, no people"
MIN_STD = 6.0
TIMEOUT_S = 900


def spec(caps=None) -> dict:
    choice = aibg.txt2img_choice(caps if caps is not None else aibg.node_caps())
    graph = aibg.build_graph(choice, PROMPT, SEED, SIZE, steps=STEPS, prefix="nm/selftest-thumbbg")
    return {
        "feature": FEATURE, "title_fa": "تامنیل‌ساز: پس‌زمینهٔ هوش مصنوعی (FLUX)", "kind": aibg.JOB_KIND, "origin": ORIGIN, "timeout_s": TIMEOUT_S,
        "payload": {"graph": graph, "uploads": [], "x_thumbbg": {"selftest": True, "seed": SEED, "size": list(SIZE), "engine": choice["label"]}},
        "expect": {"size": list(SIZE), "min_std": MIN_STD},
        "needs": ["comfyui", "FLUX dev (چک‌پوینتِ fp8 یا UNET)"],
    }


def check(job) -> tuple[bool, str]:
    """نتیجهٔ کارِ خودآزمون را می‌سنجد. ⇒ (قبول؟، پیامِ فارسی)."""
    from apps.compute.models import ComputeJob

    if job.state != ComputeJob.State.COMPLETED:
        return False, f"کار تمام نشده یا ناموفق بود ({job.state}): {(job.error or job.message or '')[:200]}"
    _meta, path = photo._image_output(job)
    if path is None or not path.is_file():
        return False, "سرورِ پردازش هیچ تصویری پس نفرستاد."
    try:
        with Image.open(path) as im:
            im.load()
            img = im.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return False, f"فایلِ تصویر خوانده نشد: {exc}"
    if list(img.size) != list(SIZE):
        return False, f"اندازهٔ تصویر {img.size[0]}×{img.size[1]} است، انتظار {SIZE[0]}×{SIZE[1]} بود."
    arr = np.asarray(img.convert("L"), dtype=np.float32)
    if float(arr.std()) < MIN_STD:
        return False, "تصویر خالی یا یک‌رنگ است (انحرافِ معیارِ روشنایی خیلی کم)."
    if float(arr.mean()) < 4 or float(arr.mean()) > 251:
        return False, "تصویر کاملاً سیاه یا سفید است."
    return True, f"تصویرِ {SIZE[0]}×{SIZE[1]} ساخته شد (میانگین {arr.mean():.0f}، پراکندگی {arr.std():.0f})."


def enqueue():
    """خودآزمون را در صفِ ماندگار می‌گذارد (گره خاموش ⇒ منتظر می‌ماند و وقتی روشن شد انجام می‌شود). ⇒ ComputeJob."""
    from apps.compute import services as compute

    s = spec()
    return compute.enqueue_durable(s["kind"], s["payload"], {}, origin=s["origin"], timeout_s=s["timeout_s"], dedupe=False, priority=40)


def latest():
    """آخرین کارِ خودآزمون یا None."""
    from apps.compute.models import ComputeJob

    return ComputeJob.objects.filter(origin=ORIGIN).order_by("-created_at").first()


# ───────────────────────────── اجرای خودکار (بدونِ هیچ کارِ دستی)

RETEST_OK_S = 7 * 86400        # قبول‌شده: هفته‌ای یک بار دوباره (مدل/نود ممکن است عوض شده باشد)
RETEST_FAIL_S = 6 * 3600       # ردشده: هر ۶ ساعت یک بار (تا مالک مدل/نود را درست کند)
_FINISHED = ("COMPLETED", "FAILED", "CANCELLED")


def _verdict(job) -> dict | None:
    """نتیجهٔ سنجیدهٔ یک کارِ تمام‌شده؛ برای بارِ اول سنجیده و در ``job.result["selftest"]`` ذخیره می‌شود."""
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
        return {"state": "none", "message": "آزمونِ خودکارِ پس‌زمینهٔ هوش مصنوعی هنوز اجرا نشده؛ وقتی سرورِ پردازش روشن شود خودش اجرا می‌شود."}
    if job.state in ("QUEUED", "CLAIMED"):
        return {"state": "waiting", "message": "آزمونِ خودکار در صفِ سرورِ پردازش است و با روشن‌شدنش اجرا می‌شود."}
    if job.state == "RUNNING":
        return {"state": "running", "message": "آزمونِ خودکار هم‌اکنون روی سرورِ پردازش در حالِ اجراست."}
    v = _verdict(job) or {"ok": False, "message": "نتیجهٔ آزمون نامعلوم است."}
    return {"state": "ok" if v["ok"] else "failed", "message": ("آزمونِ خودکار قبول شد: " if v["ok"] else "آزمونِ خودکار رد شد: ") + v["message"],
            "at": v.get("at", "")}


def auto_step(now=None) -> dict:
    """یک گامِ اجرای خودکار (هر ۵ دقیقه از beat): کارِ آزمون را هر وقت لازم است در صفِ ماندگار می‌گذارد، نتیجهٔ کارِ تمام‌شده را می‌سنجد.

    گره خاموش هم باشد کار در صف می‌ماند و با اولین heartbeat انجام می‌شود؛ پس «روشن‌شدنِ گره ⇒ آزمونِ خودکار» بدونِ هیچ دکمه‌ای.
    اگر روی گره مدلِ FLUX dev نیست، کار گذاشته نمی‌شود و علتِ فارسی برمی‌گردد (پنل همین را می‌نویسد)."""
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

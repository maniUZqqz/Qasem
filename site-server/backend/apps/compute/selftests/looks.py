"""آزمونِ «سبک تصویر › تصویرِ نمونه» — پیوندِ قراردادِ `docs/selftests/looks.md`.

ویژگیِ «سبک تصویر» (`apps.looks.selftest`: ``spec(caps)`` و ``check(job)``) را به آزمونِ خودکار وصل می‌کند: یک تصویرِ ۵۱۲×۵۱۲ از یک سبک با FLUX؛
قبول = PNG بزرگ‌تر از ۱۰ کیلوبایت و یک‌رنگ نباشد. اگر آن اپ در این نسخه نیست، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید (دو وصله مستقل‌اند)."""
from __future__ import annotations

try:  # pragma: no cover — بسته به این‌که وصلهٔ سبک تصویر اعمال شده باشد
    from apps.looks import selftest as _looks
except Exception:  # noqa: BLE001
    _looks = None

from . import SelfTest, Spec, Verdict, caps_ok, register


def _available(node):
    ok, why = caps_ok(node, "comfyui", why="ComfyUI روی این سرور نیست")
    if not ok:
        return ok, why
    models = (node.capabilities or {}).get("comfy_models")
    if isinstance(models, (list, dict)) and not models:
        return False, "هیچ مدلی در ComfyUI این سرور نیست"
    return True, ""


def build(ctx):
    try:
        s = _looks.spec(ctx.caps)
    except Exception as exc:  # noqa: BLE001 — GraphError: مدلِ FLUX dev نصب نیست
        ctx.result.extra = {**(ctx.result.extra or {}), "why": str(exc)[:300]}
        return None
    return Spec(s["kind"], s["payload"], timeout_s=int(s.get("timeout_s") or 900))


def check(ctx, job):
    ok, message = _looks.check(job)
    return Verdict.passed(message) if ok else Verdict.failed(message)


if _looks is not None:
    register(SelfTest(key="looks_sample", label="سبک تصویر: تصویرِ نمونه (FLUX)", group="image", kind="comfy.graph", build=build,
                      check=check, available=_available, gpu_required=True, optional=True, order=46, after=("comfy_flux",),
                      requeue={"kinds": ("comfy.graph",)},
                      describe="مسیرِ واقعیِ تصویرهای نمونهٔ سبک‌ها؛ قبول شدنش یعنی ساختِ تصویرِ نمونه و پس‌زمینهٔ سبک‌دار کار می‌کند"))

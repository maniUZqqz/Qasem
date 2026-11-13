"""آزمونِ «تامنیل‌ساز › پس‌زمینهٔ هوش مصنوعی» — پیوندِ قراردادِ `docs/selftests/thumbnails.md`.

ویژگیِ تامنیل‌ساز (`apps.thumbs.selftest`: ``spec(caps)`` و ``check(job)``) را به آزمونِ خودکار وصل می‌کند. اگر آن اپ در این نسخه
نیست، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید (دو وصله مستقل‌اند)."""
from __future__ import annotations

try:  # pragma: no cover — بسته به این‌که وصلهٔ تامنیل‌ساز اعمال شده باشد
    from apps.thumbs import selftest as _thumbs
except Exception:  # noqa: BLE001
    _thumbs = None

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
        s = _thumbs.spec(ctx.caps)
    except Exception as exc:  # noqa: BLE001 — GraphError: مدلِ لازم نصب نیست
        ctx.result.extra = {**(ctx.result.extra or {}), "why": str(exc)[:300]}
        return None
    return Spec(s["kind"], s["payload"], timeout_s=int(s.get("timeout_s") or 900))


def check(ctx, job):
    ok, message = _thumbs.check(job)
    return Verdict.passed(message) if ok else Verdict.failed(message)


if _thumbs is not None:
    register(SelfTest(key="thumbs_bg", label="تامنیل‌ساز: پس‌زمینهٔ هوش مصنوعی (FLUX)", group="image", kind="comfy.graph", build=build,
                      check=check, available=_available, gpu_required=True, optional=True, order=45, after=("comfy_flux",),
                      requeue={"kinds": ("comfy.graph",)},
                      describe="مسیرِ واقعیِ تامنیل‌ساز؛ قبول شدنش یعنی «پس‌زمینهٔ هوش مصنوعی» کار می‌کند"))

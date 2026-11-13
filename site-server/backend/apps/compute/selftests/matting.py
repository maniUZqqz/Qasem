"""آزمونِ جداسازیِ پس‌زمینهٔ عکس (u2netp / isnet / birefnet-lite با ONNX روی کارت)."""
import io

from . import SelfTest, Spec, Verdict, png, register

PREFERENCE = ("u2netp", "isnet", "birefnet-lite")


def _installed_model(node) -> str:
    models = (node.capabilities or {}).get("matting_models") or {}
    for key in PREFERENCE:
        if (models.get(key) or {}).get("state") == "installed":
            return key
    return ""


def _runtime_gpu(node) -> bool:
    return bool(((node.capabilities or {}).get("matting_runtime") or {}).get("gpu"))


def _available(node):
    caps = node.capabilities or {}
    if not caps.get("photo_matting"):
        return False, "جداسازیِ پس‌زمینه روی این سرور فعال نیست"
    if (caps.get("matting_runtime") or {}).get("ok") is not True:
        return False, "محیطِ اجرای جداسازی (onnxruntime) هنوز آماده نیست"
    if not _installed_model(node):
        return False, "هیچ مدلِ جداسازی روی این سرور نصب نیست"
    return True, ""


def build(ctx):
    return Spec("photo.matting", {"image": "selftest.png", "model": _installed_model(ctx.node), "feather": 0, "keep_size": True},
                files={"selftest.png": png("subject", 320)}, timeout_s=900)


def check(ctx, job):
    mask_raw, cut_raw = ctx.read_output(job, "mask.png"), ctx.read_output(job, "cutout.png")
    if not mask_raw or not cut_raw:
        return Verdict.failed("mask.png یا cutout.png ساخته نشد")
    try:
        from PIL import Image

        mask = Image.open(io.BytesIO(mask_raw)).convert("L")
        w, h = mask.size
        centre, corner = mask.getpixel((w // 2, h // 2)), mask.getpixel((4, 4))
    except Exception as e:  # noqa: BLE001
        return Verdict.failed("ماسک خوانده نشد: %s" % e)
    if centre < 128 or corner > 100:
        return Verdict.failed("ماسک درست نیست: وسطِ سوژه %d و گوشهٔ پس‌زمینه %d" % (centre, corner))
    meta = ctx.meta(job)
    return Verdict.passed("مدلِ %s · ماسک درست (وسط %d، گوشه %d) · %s ثانیه" % ((job.payload or {}).get("model"), centre, corner,
                                                                       meta.get("seconds", job.run_s)))


register(SelfTest(key="matting", label="جداسازیِ پس‌زمینهٔ عکس (ONNX روی کارت)", group="image", kind="photo.matting", build=build, check=check,
                  available=_available, gpu_required=lambda ctx: _runtime_gpu(ctx.node), order=50, needs_features=("gpu-runtime",),
                  requeue={"kinds": ("photo.matting", "edit.matte")}, describe="دایرهٔ آبی از زمینهٔ نارنجی جدا می‌شود"))

"""آزمونِ ComfyUI: یک تصویرِ کوچکِ FLUX؛ و (فقط در «آزمونِ عمیق») یک ویدیوی کوتاهِ Wan."""
import io

from . import SelfTest, Spec, Verdict, caps_ok, png, register

IMAGE_PROFILES = ("flux-product-fast", "flux-product-balanced", "flux-product-portrait")
VIDEO_PROFILES = ("wan22-480p-short", "wan22-480p-long")


def _has_profile(node, names):
    prof = (node.capabilities or {}).get("comfy_profiles")
    if isinstance(prof, list) and prof:
        return next((n for n in names if n in prof), "")
    return names[0]                     # لیستِ پروفایل‌ها هنوز نرسیده (ComfyUI خاموش): نخستین را می‌آزماییم


def _available(names):
    def fn(node):
        ok, why = caps_ok(node, "comfyui", why="ComfyUI روی این سرور نیست و عامل هم نمی‌تواند روشنش کند")
        if not ok:
            return ok, why
        if not _has_profile(node, names):
            return False, "پروفایلِ لازم (%s) روی این سرور نیست" % names[0]
        return True, ""
    return fn


def build_image(ctx):
    profile = _has_profile(ctx.node, IMAGE_PROFILES)
    return Spec("comfy.profile", {"profile": profile, "prompt": "a clean modern gym interior, a pair of dumbbells and a yoga mat on the floor, soft morning light, photo, no text",
                                  "negative_prompt": "", "controls": {"width": 512, "height": 512, "steps": 4, "seed": 7}},
                timeout_s=1800)


def check_image(ctx, job):
    outs = [o for o in job.outputs() if str(o.get("media")) == "image" or str(o.get("name", "")).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if not outs:
        return Verdict.failed("ComfyUI تصویری برنگرداند (خروجی‌ها: %s)" % ", ".join(o.get("name", "?") for o in job.outputs()))
    raw = ctx.read_output(job, outs[0]["name"])
    if not raw or len(raw) < 4000:
        return Verdict.failed("تصویر خالی یا خیلی کوچک است (%s بایت)" % (len(raw or b"")))
    try:
        from PIL import Image, ImageStat

        im = Image.open(io.BytesIO(raw)).convert("RGB")
        spread = max(ImageStat.Stat(im).stddev)
    except Exception as e:  # noqa: BLE001
        return Verdict.failed("تصویر خوانده نشد: %s" % e)
    if im.width < 256 or spread < 4:
        return Verdict.failed("تصویر خراب یا یک‌رنگ است (%dx%d، پراکندگی %.1f)" % (im.width, im.height, spread))
    return Verdict.passed("%s · %dx%d در %s ثانیه" % ((job.payload or {}).get("profile"), im.width, im.height, job.run_s if job.run_s is not None else "؟"))


def build_video(ctx):
    profile = _has_profile(ctx.node, VIDEO_PROFILES)
    return Spec("comfy.profile", {"profile": profile, "prompt": "slow gentle zoom in", "image": "selftest.png",
                                  "controls": {"length": 17, "steps": 4, "width": 480, "height": 480, "seed": 3}},
                files={"selftest.png": png("square", 480)}, timeout_s=3600)


def check_video(ctx, job):
    outs = [o for o in job.outputs() if str(o.get("name", "")).lower().endswith((".mp4", ".webm", ".mov", ".gif"))]
    if not outs or (outs[0].get("size") or 0) < 20000:
        return Verdict.failed("ویدیویی (یا ویدیوی کافی) ساخته نشد")
    return Verdict.passed("%s · %s کیلوبایت در %s ثانیه" % ((job.payload or {}).get("profile"), (outs[0].get("size") or 0) // 1024, job.run_s))


register(SelfTest(key="comfy_flux", label="ساختِ تصویر با FLUX (ComfyUI)", group="image", kind="comfy.profile", build=build_image,
                  check=check_image, available=_available(IMAGE_PROFILES), gpu_required=True, order=40,
                  requeue={"kinds": ("comfy.graph", "comfy.profile")}, describe="یک تصویرِ ۵۱۲ با چهار گام؛ بارگذاریِ اولِ مدل چند دقیقه می‌برد"))
register(SelfTest(key="comfy_wan", label="ساختِ ویدیوی کوتاه با Wan (آزمونِ عمیق)", group="video", kind="comfy.profile", build=build_video,
                  check=check_video, available=_available(VIDEO_PROFILES), gpu_required=True, optional=True, deep=True, order=90,
                  after=("comfy_flux",), requeue={"kinds": ("comfy.graph", "comfy.profile")},
                  describe="فقط با دکمهٔ «آزمونِ عمیق»؛ چند دقیقه طول می‌کشد"))

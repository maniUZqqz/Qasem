"""آزمونِ رندرِ نهاییِ ویرایشگرِ ویدیو (edit.render): یک گرافِ ffmpeg که خودش تصویر می‌سازد، با NVENC رمزگذاری و آپلودِ تکه‌ای."""
from . import SelfTest, Spec, Verdict, register

GRAPH = "testsrc2=s=640x360:r=30:d=2,format=yuv420p[vout]"


def _available(node):
    edit = (node.capabilities or {}).get("edit")
    if isinstance(edit, dict) and edit.get("render") is True:
        return True, ""
    if isinstance(edit, dict):
        return False, "ffmpegِ این سرور برای رندر کامل نیست (%s)" % (edit.get("why") or ", ".join(edit.get("missing") or []) or "نامشخص")
    return False, "قابلیتِ رندرِ ویدیو روی این سرور گزارش نشده است"


def _nvenc_expected(ctx) -> bool:
    return bool((((ctx.caps.get("edit") or {}).get("nvenc")) or {}).get("h264"))


def build(ctx):
    enc = {"cpu": ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"],
           "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-pix_fmt", "yuv420p"], "codec": "h264"}
    return Spec("edit.render", {"graph": GRAPH, "inputs": [], "texts": {}, "assets": {}, "fonts": [], "files": {}, "audio": False,
                                "audio_args": [], "encode": enc, "out": "render.mp4", "length": 2}, timeout_s=900)


def check(ctx, job):
    outs = {o.get("name"): o for o in job.outputs()}
    out = outs.get("render.mp4")
    if not out or (out.get("size") or 0) < 3000:
        return Verdict.failed("render.mp4 ساخته نشد یا خالی است")
    meta = ctx.meta(job)
    enc = meta.get("encoder") or ""
    detail = "%s · %s کیلوبایت · رمزگشا: %s · %s ثانیه" % (enc, (out.get("size") or 0) // 1024, meta.get("decoder") or "-", meta.get("render_seconds"))
    if _nvenc_expected(ctx) and "NVENC" not in enc:
        return Verdict.failed("کارت NVENC دارد ولی رندر روی پردازنده انجام شد (%s)" % enc, device="cpu")
    return Verdict.passed(detail)


register(SelfTest(key="edit_render", label="رندرِ نهاییِ ویرایشگرِ ویدیو (NVENC)", group="video", kind="edit.render", build=build, check=check,
                  available=_available, gpu_required=lambda ctx: _nvenc_expected(ctx), order=55, needs_features=("ffmpeg-nvenc",),
                  requeue={"kinds": ("edit.render", "edit.matte", "edit.track")}, describe="دو ثانیه ویدیو؛ آپلودِ تکه‌ای و بررسیِ اندازه"))

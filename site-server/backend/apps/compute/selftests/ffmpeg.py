"""آزمونِ رمزگذاریِ سخت‌افزاری: یک ویدیوی دوثانیه‌ای با NVENC ساخته و با NVDEC خوانده می‌شود."""
from . import SelfTest, Spec, Verdict, register


def build(ctx):
    return Spec("selftest.ffmpeg", {}, timeout_s=300)


def check(ctx, job):
    info = ctx.read_json(job, "ffmpeg.json")
    if not isinstance(info, dict):
        return Verdict.failed("گزارشِ ffmpeg.json از سرورِ پردازش نرسید.")
    meta = ctx.meta(job)
    if not info.get("nvenc_h264"):
        why = info.get("nvenc_error") or "رمزگذارِ h264_nvenc در این ffmpeg نیست یا کار نمی‌کند"
        return Verdict.failed("ffmpeg روی پردازنده (libx264) رمزگذاری کرد، نه کارت: %s" % why, device="cpu",
                              extra={"info": info})
    dec = info.get("nvdec") or {}
    nvdec = "NVDEC هم کار کرد" if dec.get("ok") else ("NVDEC کار نکرد" if dec.get("ok") is False else "NVDEC در این ffmpeg نیست")
    detail = "NVENC H.264 در %s ثانیه (%s) · %s · ffmpeg %s" % (info.get("encode_seconds"), info.get("size"), nvdec, info.get("version") or "")
    return Verdict.passed(detail, device=meta.get("device") or "nvenc", extra={"info": info})


register(SelfTest(key="ffmpeg_nvenc", label="رمزگذاریِ ویدیو با NVENC (و خواندن با NVDEC)", group="gpu", kind="selftest.ffmpeg",
                  build=build, check=check, gpu_required=True, order=20, after=(), min_agent="2.11", needs_features=("ffmpeg-nvenc",),
                  describe="ffmpeg ای که NVENC کار می‌کند؛ اگر نبود، نسخهٔ آن از آینهٔ سایت نصب می‌شود"))

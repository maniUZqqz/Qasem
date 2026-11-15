"""آزمونِ «موشن با صدا»: یک رندرِ واقعیِ ۳ ثانیه‌ای `motion.render` که صدای آمادهٔ سایت (mix.m4a: افکت‌های ساختهٔ خودِ سامانه، ‎−۱۴ LUFS) را گره زیرِ تصویر می‌گذارد.

سایت mix را می‌سازد (هیچ نمونه یا فایلِ بیرونی نیست)، گره فقط ویدیو را رندر و صدا را با ffmpeg ِ داخلِ بستهٔ Remotion زیرش می‌نشاند.
قبول = out.mp4 ‏۳ ثانیه با یک ردیفِ صدا و motion-render.json با audio = «muxed». کلیدِ آزمون: studio_motion_audio (توضیحِ بدونِ کد: docs/selftests/motion-audio.md).
گرهٔ قدیمی که `features` نمی‌دهد (بدونِ audio_mux) «رد» نمی‌شود، «در دسترس نیست» حساب می‌شود؛ سایت در آن حالت صدا را خودش با ویدیو ترکیب می‌کند."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import SelfTest, Spec, Verdict, register

KIND = "motion.render"
KEY = "studio_motion_audio"
SPEC = {
    "version": 2, "style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa", "digits": "auto", "platform": "reels",
    "brand": {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]},
    "scenes": [{"type": "kinetic_title", "duration": 3, "kicker": "آزمونِ صدا", "text": "با چغر، چغرتر شو", "emphasis": ["چغرتر"]}],
    "audio": {"sfx": True},
}


def _available(node):
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if not isinstance(kinds, list) or KIND not in kinds:
        return False, "عاملِ این سرور نوعِ «%s» را نمی‌شناسد (به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش لازم است)" % KIND
    motion = caps.get("motion") or {}
    if not caps.get("motion_render"):
        return False, "ابزارِ موشن روی این سرور خاموش است"
    if "audio_mux" not in (motion.get("features") or []):
        return False, "این نسخهٔ عامل صدا را زیرِ تصویر نمی‌گذارد (به‌روزرسانی لازم است؛ تا آن موقع سایت صدا را خودش ترکیب می‌کند)"
    return True, ""


def _mix_bytes() -> bytes:
    """یک mix ِ ۳ ثانیه‌ای از افکت‌های ساخته‌شدهٔ خودِ سامانه، با همان زنجیرهٔ تولیدِ واقعی (loudnorm ‎−۱۴)."""
    from apps.motion import sound

    work = Path(tempfile.mkdtemp(prefix="nm-selftest-audio-"))
    try:
        whoosh = sound.synth_sfx("whoosh", work / "whoosh.wav", -12.0)
        pop = sound.synth_sfx("pop", work / "pop.wav", -10.0)
        out = work / "mix.m4a"
        sound.build_mix(work, 3.0, [], [(str(whoosh), 0.2), (str(pop), 1.2), (str(whoosh), 2.0)], None, out)
        return out.read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build(ctx):
    payload = {"composition": "Template", "props": {"spec": SPEC}, "scale": 0.5, "crf": 23, "max_seconds": 10, "title": "motion audio selftest", "style": "flat-vector",
               "mode": "template", "selftest": True, "audio": {"file": "mix.m4a"}}
    return Spec(KIND, payload, files={"mix.m4a": _mix_bytes()}, timeout_s=1200)


def check(ctx, job):
    meta = ctx.meta(job)
    device = str(meta.get("device") or "")
    note = str(meta.get("audio") or "")
    if note != "muxed":
        return Verdict.failed("گره صدا را زیرِ تصویر نگذاشت (%s)" % (note or "بدونِ توضیح"), device=device)
    path = ctx.output_path(job, "out.mp4")
    try:
        from apps.motion import sound

        has = sound.has_audio(path)
        secs = sound.duration_of(path)
    except Exception as exc:  # noqa: BLE001
        return Verdict.failed("ویدیو بررسی نشد: %s" % exc, device=device)
    if not has:
        return Verdict.failed("out.mp4 ردیفِ صدا ندارد", device=device)
    if abs(secs - 3.0) > 0.4:
        return Verdict.failed("طولِ ویدیو %.1f ثانیه است؛ انتظار ۳ ثانیه" % secs, device=device)
    return Verdict.passed("ویدیوی ۳ ثانیه‌ای با صدا (%s ثانیه)" % round(secs, 1), device=device)


register(SelfTest(key=KEY, label="استودیوی موشن: ویدیو با صدا (گره صدا را زیرِ تصویر می‌گذارد)", group="video", kind=KIND, build=build, check=check,
                  available=_available, gpu_required=False, order=161, requeue={"kinds": (KIND,)},
                  describe="رندرِ ۳ ثانیه‌ای با mix ِ آمادهٔ سایت؛ قبول = ردیفِ صدا با ‎−۱۴ LUFS"))

_ = subprocess  # (ffmpeg فقط از راهِ apps.motion.sound صدا زده می‌شود)

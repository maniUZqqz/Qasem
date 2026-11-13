"""آزمونِ گفتار: Piper (فارسیِ ساده) و MOSS (فارسیِ طبیعی روی کارت). خروجیِ Piper ورودیِ آزمونِ تشخیصِ گفتار هم هست."""
import io
import wave

from . import SelfTest, Spec, Verdict, caps_ok, register

#: جملهٔ آزمون از واقعیت‌های برندِ «چغر» (docs/chagher/brand-facts-fa.md: شعار و کارِ محصول) — عدد و قیمت ندارد، تا صدای ساخته‌شده
#: هم یک نمونهٔ واقعی از کیفیتِ صدای همان محصولی باشد که مالک با آن همه‌چیز را می‌سنجد
TEXT = "سلام. با چغر، چغرتر شو. چغر برنامهٔ ورزشی و غذاییِ هر ورزشکار را در کمتر از یک دقیقه پیش‌نویس می‌کند."
MOSS_ENGINES = ("moss-fa", "moss", "moss-tts")


def wav_seconds(raw: bytes):
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001
        return None


def _check_wav(ctx, job, name="speech.wav", min_s=1.0):
    raw = ctx.read_output(job, name)
    if not raw or raw[:4] != b"RIFF":
        return None, Verdict.failed("فایلِ صوتیِ %s ساخته نشد یا wav نیست" % name)
    secs = wav_seconds(raw)
    if secs is None or secs < min_s:
        return secs, Verdict.failed("صدا خیلی کوتاه یا خراب است (%s ثانیه)" % (round(secs, 2) if secs is not None else "؟"))
    return secs, None


def _piper_available(node):
    return caps_ok(node, "voice", why="سرویسِ صدا (PersianAiKit.Voice) روی این سرور نیست")


def build_piper(ctx):
    return Spec("voice.tts", {"text": TEXT, "engine": "piper", "out": "speech.wav"}, timeout_s=900)


def check_piper(ctx, job):
    secs, bad = _check_wav(ctx, job)
    if bad:
        return bad
    return Verdict.passed("Piper · %.1f ثانیه صدا در %s ثانیه" % (secs, job.run_s if job.run_s is not None else "؟"), extra={"audio_seconds": secs})


def _moss_available(node):
    caps = node.capabilities or {}
    if ((node.desired or {}).get("audio") or {}).get("speech") is False:
        return False, "مدلِ گفتارِ MOSS در پنل برای این سرور خاموش است"
    audio = caps.get("audio")
    if isinstance(audio, dict) and not audio.get("moss"):
        return False, "مدلِ MOSS روی این سرور نصب نیست (در حالِ دانلود یا هنوز دانلود نشده)"
    return True, ""


def build_moss(ctx):
    return Spec("voice.tts", {"text": TEXT, "engine": "moss-fa", "voice": "mana", "out": "speech.wav", "selftest": True}, timeout_s=1800)


def check_moss(ctx, job):
    secs, bad = _check_wav(ctx, job)
    if bad:
        return bad
    return Verdict.passed("MOSS-TTS · %.1f ثانیه صدا در %s ثانیه" % (secs, job.run_s if job.run_s is not None else "؟"), extra={"audio_seconds": secs})


def _is_moss(job) -> bool:
    return str((job.payload or {}).get("engine") or "").lower() in MOSS_ENGINES


register(SelfTest(key="tts_piper", label="گفتارِ فارسی با Piper", group="audio", kind="voice.tts", build=build_piper, check=check_piper,
                  available=_piper_available, order=60,
                  requeue={"kinds": ("voice.tts",), "match": lambda j: not _is_moss(j)}, describe="یک جمله؛ خروجی ورودیِ آزمونِ تشخیصِ گفتار است"))
register(SelfTest(key="tts_moss", label="گفتارِ فارسیِ طبیعی با MOSS (روی کارت)", group="audio", kind="voice.tts", build=build_moss,
                  check=check_moss, available=_moss_available, gpu_required=True, order=61,
                  requeue={"kinds": ("voice.tts", "voice.clone"), "match": _is_moss},
                  describe="همان مدلی که صداهای چغر را می‌سازد؛ بعد از قبولی، صداهای ناموفقِ قبلی دوباره ساخته می‌شوند"))

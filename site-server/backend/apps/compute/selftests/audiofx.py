"""آزمونِ صدای محیط (MOSS-SoundEffect) و موسیقی (ACE-Step) — اختیاری؛ موسیقی فقط در «آزمونِ عمیق»."""
from . import SelfTest, Spec, Verdict, register
from .tts import _check_wav


def _sfx_available(node):
    caps = node.capabilities or {}
    if ((node.desired or {}).get("audio") or {}).get("sfx") is False:
        return False, "مدلِ صدای محیط در پنل برای این سرور خاموش است"
    audio = caps.get("audio")
    if isinstance(audio, dict) and not audio.get("sfx"):
        return False, "مدلِ صدای محیط روی این سرور نصب نیست"
    return True, ""


def _music_available(node):
    caps = node.capabilities or {}
    if ((node.desired or {}).get("audio") or {}).get("music") is False:
        return False, "مدلِ موسیقی در پنل برای این سرور خاموش است"
    audio = caps.get("audio")
    if isinstance(audio, dict) and not audio.get("music"):
        return False, "مدلِ موسیقی روی این سرور نصب نیست"
    return True, ""


def build_sfx(ctx):
    return Spec("voice.sfx", {"prompt": "a short wooden door knock", "seconds": 2, "out": "sfx.wav", "seed": 5}, timeout_s=1800)


def check_sfx(ctx, job):
    secs, bad = _check_wav(ctx, job, "sfx.wav", 0.5)
    return bad or Verdict.passed("%.1f ثانیه صدا در %s ثانیه" % (secs, job.run_s))


def build_music(ctx):
    return Spec("voice.music", {"prompt": "calm soft piano, warm, instrumental", "seconds": 10, "out": "music.wav", "seed": 11}, timeout_s=2400)


def check_music(ctx, job):
    secs, bad = _check_wav(ctx, job, "music.wav", 5.0)
    return bad or Verdict.passed("%.1f ثانیه موسیقی در %s ثانیه" % (secs, job.run_s))


register(SelfTest(key="sfx", label="صدای محیط و افکت (MOSS-SoundEffect)", group="audio", kind="voice.sfx", build=build_sfx, check=check_sfx,
                  available=_sfx_available, gpu_required=True, optional=True, order=80, requeue={"kinds": ("voice.sfx",)}))
register(SelfTest(key="music", label="موسیقیِ زمینه (ACE-Step) — آزمونِ عمیق", group="audio", kind="voice.music", build=build_music,
                  check=check_music, available=_music_available, gpu_required=True, optional=True, deep=True, order=91,
                  requeue={"kinds": ("voice.music",)}))

"""آزمونِ تشخیصِ گفتار: صدای Piper (آزمونِ tts_piper) به Vosk و به faster-whisper روی کارت داده می‌شود و متن با جمله مقایسه می‌شود."""
import re

from . import SelfTest, Spec, Verdict, caps_ok, register
from .tts import TEXT

EXPECTED = [w for w in re.split(r"[\s.،؛!؟]+", TEXT) if len(w) > 2]


def norm(text: str) -> str:
    return (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("ً", "").strip().lower()


def overlap(text: str) -> float:
    words = set(re.split(r"[\s.،؛!؟,]+", norm(text)))
    want = [norm(w) for w in EXPECTED]
    hit = sum(1 for w in want if w in words or any(w in x or x in w for x in words if len(x) > 2))
    return hit / float(len(want)) if want else 0.0


def flatten_text(obj) -> str:
    """متنِ همهٔ فیلدهای text / transcript / phrase در پاسخِ Vosk یا Whisper."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("text", "transcript", "phrase", "word") and isinstance(v, str):
                    out.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return " ".join(out)


def _speech(ctx):
    job = ctx.job("tts_piper")
    return ctx.read_output(job, "speech.wav") if job else None


def build_vosk(ctx):
    raw = _speech(ctx)
    if not raw:
        return None
    return Spec("voice.asr", {"audio": "speech.wav"}, files={"speech.wav": raw}, timeout_s=900)


def check_vosk(ctx, job):
    data = ctx.read_json(job, "asr.json")
    text = flatten_text(data)
    if not text.strip():
        return Verdict.failed("هیچ متنی تشخیص داده نشد")
    score = overlap(text)
    if score < 0.34:
        return Verdict.failed("متنِ تشخیص‌داده‌شده به جمله نمی‌خورد: «%s»" % text[:80])
    return Verdict.passed("«%s» (انطباق %d٪)" % (text[:70], int(score * 100)))


def _gpu_available(node):
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if isinstance(kinds, list) and "asr.transcribe" not in kinds:
        return False, "عاملِ این سرور «asr.transcribe» را نمی‌شناسد"
    if not isinstance(kinds, list):
        return False, "عاملِ این سرور قدیمی است (۲٫۱۱ به بعد لازم است)"
    return True, ""


def build_gpu(ctx):
    raw = _speech(ctx)
    if not raw:
        return None
    return Spec("asr.transcribe", {"audio": "speech.wav", "language": "fa", "model": "small", "word_timestamps": True},
                files={"speech.wav": raw}, timeout_s=1800)


def check_gpu(ctx, job):
    data = ctx.read_json(job, "transcript.json")
    if not isinstance(data, dict):
        return Verdict.failed("transcript.json نرسید")
    text = str(data.get("text") or "").strip()
    meta = ctx.meta(job)
    if not text:
        return Verdict.failed("هیچ متنی تشخیص داده نشد", device=meta.get("device", ""))
    score = overlap(text)
    if score < 0.34:
        return Verdict.failed("متنِ تشخیص‌داده‌شده به جمله نمی‌خورد: «%s»" % text[:80], device=meta.get("device", ""))
    return Verdict.passed("faster-whisper (%s) · «%s» (انطباق %d٪) · %s ثانیه" % (
        meta.get("compute_type") or "", text[:60], int(score * 100), meta.get("asr_seconds")), extra={"words": len(data.get("words") or [])})


register(SelfTest(key="asr_vosk", label="تشخیصِ گفتار (Vosk) از روی صدای Piper", group="audio", kind="voice.asr", build=build_vosk,
                  check=check_vosk, available=lambda n: caps_ok(n, "voice", why="سرویسِ صدا روی این سرور نیست"), after=("tts_piper",), order=70,
                  requeue={"kinds": ("voice.asr",)}, describe="زیرنویسِ خودکارِ ویدیو از همین مسیر می‌گذرد"))
register(SelfTest(key="asr_gpu", label="تشخیصِ گفتار روی کارت (faster-whisper + CUDA)", group="audio", kind="asr.transcribe", build=build_gpu,
                  check=check_gpu, available=_gpu_available, gpu_required=True, after=("tts_piper",), order=71,
                  min_agent="2.11", needs_features=("asr-gpu",),
                  requeue={"kinds": ("asr.transcribe",)}, describe="نصبِ خودکارِ کتابخانه و مدل؛ تا آماده شدن آزمون منتظر می‌ماند"))

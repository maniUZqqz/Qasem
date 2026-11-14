"""آزمونِ خودکارِ «تدوینِ خودکارِ حرفه‌ای» روی سرورِ پردازش (دو آزمون؛ سومی، جداسازیِ پس‌زمینهٔ ویدیو، در docs/selftests/autoedit.md است).

هر دو را همان سنجه‌های `services.editing.selftest_autoedit` قضاوت می‌کنند (تابع‌های خالصِ روی فایل‌ها؛ آزمونِ واحدشان بی‌گره اجرا می‌شود):

* `autoedit_words` — صدای Piper (آزمونِ tts_piper) به `asr.transcribe` (faster-whisper روی کارت)؛ قبول: کلمه‌ها با زمانِ صعودی و داخلِ کلیپ و دست‌کم
  دو کلمهٔ جمله درست شنیده شود. همهٔ برش‌های روی مرزِ کلمه، دوباره‌گویی، «اِم و اوم» و زیرنویسِ تدوینِ خودکار روی همین زمان‌ها ایستاده‌اند.
* `autoedit_mix` — باگِ «صداها روی هم می‌افتد» روی خودِ ماشین: پروژهٔ ۱۰ ثانیه‌ای (آدمِ جلوی دوربین ۳ تا ۵ ثانیه حرف می‌زند، بسترِ موسیقی، بدونِ هیچ
  تنظیمِ ducking، بلندیِ استاندارد) با همان گرافِ ffmpegِ سایت روی گره رندر می‌شود. قبول: فایل سالم و ۱۰±۰٫۷ ثانیه؛ `audioqc` هیچ گفتارِ دوبار، فازِ
  وارونه یا موسیقیِ روی صدا نمی‌شنود؛ بستر زیرِ گفتار دست‌کم ۸ دسی‌بل کم می‌شود (ducking پیش‌فرض واقعاً اعمال شده)؛ بلندی نزدیکِ ‎−۱۴ LUFS.
  رندر «ورودیِ ثبت‌شده در transfer» می‌خواهد (گره فایل‌ها را از سایت می‌گیرد) ولی اجراکنندهٔ آزمون فقط `Spec` می‌فرستد؛ پس این آزمون «مجازی» است: کارِ
  خودش را می‌سازد و در هر گام وضعیتش را می‌پرسد (شناسهٔ کار در `result.extra`).

هر دو فقط وقتی اجرا می‌شوند که عاملِ گره همهٔ نوع‌کارهایی را که تدوینِ خودکار به کار می‌برد اعلام کرده باشد (`PIPELINE_KINDS`)؛ وگرنه «ردشده» با نامِ آنچه کم است
(آزمونِ نیمه‌کاره‌ای که به‌خاطرِ عاملِ قدیمی رد شود بی‌معنی است).
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from . import SelfTest, Spec, Verdict, register

logger = logging.getLogger(__name__)

#: what the automatic edit uses on the node: speech (words), matting (background), the final render (faces for the framing are found on the site)
PIPELINE_KINDS = ("asr.transcribe", "edit.matte", "edit.render")
MIX_BUDGET_S = 900


def _st():
    from services.editing import selftest_autoedit

    return selftest_autoedit


def _pipeline_available(node):
    kinds = (node.capabilities or {}).get("kinds")
    if not isinstance(kinds, list):
        return False, "عاملِ این سرور قدیمی است (۲٫۱۱ به بعد لازم است)"
    missing = [k for k in PIPELINE_KINDS if k not in kinds]
    if missing:
        return False, "عاملِ این سرور این کارها را اعلام نکرده: %s" % "، ".join(missing)
    return True, ""


def _render_available(node):
    ok, why = _pipeline_available(node)
    if not ok:
        return ok, why
    edit = (node.capabilities or {}).get("edit")
    if isinstance(edit, dict) and edit.get("render") is True:
        return True, ""
    return False, "ffmpegِ این سرور برای رندر کامل نیست"


# ------------------------------------------------------------------ words


def _speech(ctx):
    job = ctx.job("tts_piper")
    return ctx.read_output(job, "speech.wav") if job else None


def build_words(ctx):
    raw = _speech(ctx)
    if not raw:
        return None
    from services.editing import captions

    return Spec(captions.WHISPER_KIND, captions.whisper_payload([ctx.node]), files={"audio.wav": raw}, timeout_s=1800)


def check_words(ctx, job):
    from services.editing import captions

    from .asr import EXPECTED

    data = ctx.read_json(job, "transcript.json")
    if not isinstance(data, dict):
        return Verdict.failed("transcript.json نرسید")
    meta = ctx.meta(job)
    res = _st().check_words(captions.words_from_asr(data), float(data.get("duration") or 0) or 30.0, expected=EXPECTED)
    detail = "؛ ".join(c["detail"] for c in res["checks"])
    if not res["ok"]:
        return Verdict.failed(detail, device=meta.get("device", ""))
    return Verdict.passed(detail, device=meta.get("device", ""), extra={"words": len(data.get("words") or [])})


# ------------------------------------------------------------------ the mixed render (the owner's «overlapping sound» bug)


def _work_root() -> Path:
    from .. import services as SV

    root = SV.data_root() / "selftest-autoedit"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state(ctx) -> dict:
    return dict(((ctx.result.extra if ctx.result is not None else None) or {}).get("autoedit_mix") or {})


def _start_mix(ctx) -> Verdict:
    from services.editing import noderender

    from .. import services as SV
    from .. import transfer

    ST = _st()
    folder = _work_root() / uuid.uuid4().hex[:12]
    try:
        media = ST.make_media(folder)
        bundle = noderender.build(ST.build_timeline(ST.mix_project(), media), None)
        # held for a moment so the node cannot claim it before its files are registered (exactly as the editor's own render does)
        job = SV.enqueue(noderender.KIND, bundle.payload, None, origin="selftest", priority=15, timeout_s=MIX_BUDGET_S, node="__hold__", dedupe=False,
                         require_online=False, category="selftest", max_attempts=1, max_wait_s=6 * 3600)
        job.max_attempts = 1
        job.node_wanted = ctx.node.name
        transfer.register_assets(job, bundle.files)
        job.save(update_fields=["max_attempts", "node_wanted"])
    except Exception as exc:  # noqa: BLE001 — the sample could not even be made on the site: that is a failure with its reason
        shutil.rmtree(folder, ignore_errors=True)
        logger.exception("autoedit selftest: the sample render could not be queued")
        return Verdict.failed("نمونهٔ رندر ساخته نشد: %s" % str(exc)[:200])
    return Verdict.waiting("رندرِ نمونهٔ میکس (گفتار + موسیقی) در صفِ سرورِ پردازش است", extra={"autoedit_mix": {"job": str(job.uid), "dir": str(folder)}})


def virtual_mix(ctx) -> Verdict:
    from ..models import ComputeJob

    st = _state(ctx)
    if not st.get("job"):
        return _start_mix(ctx)
    job = ComputeJob.objects.filter(uid=st["job"]).first()
    if job is None:
        return Verdict.failed("کارِ رندرِ نمونه پیدا نشد")
    if not job.final:
        return Verdict.waiting("رندرِ نمونه روی سرورِ پردازش: %s" % ((job.message or job.state or "")[:80]))
    if st.get("dir"):
        shutil.rmtree(st["dir"], ignore_errors=True)
    if job.state != ComputeJob.State.COMPLETED:
        return Verdict.failed("رندرِ نمونه ناموفق بود: %s" % ((job.error or job.message or "لغو شد")[-300:]))
    from services.editing import noderender

    out = ctx.output_path(job, noderender.OUT_NAME)
    res = _st().check_mix(out) if Path(out).is_file() else {"ok": False, "checks": [{"detail": "render.mp4 نرسید"}]}
    meta = ctx.meta(job)
    detail = "؛ ".join(c["detail"] for c in res["checks"])
    encoder = str(meta.get("encoder") or "")
    if encoder:
        detail += " · رمزگذار: %s" % encoder
    if not res["ok"]:
        return Verdict.failed(detail)
    edit = ctx.caps.get("edit") or {}
    warning = ""
    if (edit.get("nvenc") or {}).get("h264") and "NVENC" not in encoder.upper():
        warning = "کارت NVENC دارد ولی رندر با %s انجام شد" % (encoder or "رمزگذارِ پردازنده")
    return Verdict.passed(detail, warning=warning)


register(SelfTest(key="autoedit_words", label="تدوینِ خودکار: کلمه‌ها با زمان (برای برش و زیرنویس)", group="video", kind="asr.transcribe", build=build_words,
                  check=check_words, available=_pipeline_available, after=("tts_piper",), order=72,
                  describe="برشِ روی مرزِ کلمه، دوباره‌گویی و زیرنویسِ خودکار روی زمانِ کلمه‌ها ایستاده است"))
def build_words_large(ctx):
    raw = _speech(ctx)
    if not raw:
        return None
    from services.editing import captions

    return Spec(captions.WHISPER_KIND, {**captions.WHISPER_PAYLOAD, "model": "large-v3-turbo"}, files={"audio.wav": raw}, timeout_s=3600)


def check_words_large(ctx, job):
    """The same pass check as `autoedit_words`, plus: the node really used the large model (a quiet fall-back to `small` is a finding, not a pass)."""
    verdict = check_words(ctx, job)
    meta = ctx.meta(job)
    used = str(meta.get("model") or "")
    if verdict.ok and "large-v3-turbo" not in used:
        return Verdict.failed("مدلِ بزرگ استفاده نشد (%s): %s" % (used or "?", meta.get("model_note") or "نصب نیست"), device=meta.get("device", ""))
    return verdict


def _large_available(node):
    ok, why = _pipeline_available(node)
    if not ok:
        return ok, why
    models = (node.capabilities or {}).get("asr_models")
    if not isinstance(models, list):
        return False, "عاملِ این سرور هنوز مدل‌های Whisperِ نصب‌شده را اعلام نمی‌کند (نسخهٔ ۲٫۱۹ به بعد)"
    return True, ""


register(SelfTest(key="autoedit_words_large", label="تدوینِ خودکار: Whisper large-v3-turbo (فارسیِ دقیق‌تر)", group="video", kind="asr.transcribe",
                  build=build_words_large, check=check_words_large, available=_large_available, gpu_required=True, after=("tts_piper",), order=73,
                  needs_features=("asr-gpu", "asr-large"), wait_install_s=6 * 3600, requeue={"kinds": ("asr.transcribe",)},
                  describe="مدلِ بزرگ خودکار دانلود می‌شود؛ تا آماده شدن آزمون منتظر می‌ماند. جوابِ مدلِ کوچک «قبول» حساب نمی‌شود."))
register(SelfTest(key="autoedit_mix", label="تدوینِ خودکار: میکسِ گفتار و موسیقی (صدا روی هم نمی‌افتد)", group="video", virtual=virtual_mix,
                  kind="edit.render", available=_render_available, after=("edit_render",), order=56, wait_install_s=2 * 3600,
                  describe="گفتار + موسیقیِ بی‌تنظیم؛ گفتار یک بار شنیده شود، موسیقی زیرِ آن برود و بلندی نزدیکِ ‎−۱۴ LUFS باشد"))

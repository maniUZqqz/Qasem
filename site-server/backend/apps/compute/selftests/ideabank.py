# -*- coding: utf-8 -*-
"""آزمونِ خودکارِ «بانکِ ایده» (پیوندِ قراردادِ docs/selftests/ideabank.md).

· `ideabank_ai` (کارِ واقعی، روی کارت): پرسشِ واقعیِ «ایده بساز» برای چغر (شعار و جمله‌های تأییدشدهٔ برند، بدونِ هیچ قیمت و آمار) با مدلِ متنیِ خودِ مالک
  (qwen3:8b یا هر مدلِ کوچکِ نصب‌شده؛ هیچ مدلی عوض نمی‌شود) به‌صورتِ یک کارِ `ollama.generate`. قبول یعنی: JSON درست، دست‌کم یک ایدهٔ فارسیِ معتبر
  با قالبِ ناشناخته‌نبودن و بدونِ عدد/قیمت/آمارِ ساختگی. تا روشن‌شدنِ گره «منتظرِ گره» می‌ماند؛ بانکِ آماده و فرمول‌ها منتظرِ این نمی‌مانند.
· `ideabank_seeds` (مجازی، بی‌گره): ایده‌های آماده، پرکردنِ جای‌گیرها، فرمول‌های فارسی و مسیرِ هوش مصنوعی با جوابِ ساختگی (`apps.ideabank.selftest.run_offline`).

اگر اپِ `apps.ideabank` در این نسخه نیست، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید.
"""
try:  # pragma: no cover — بسته به این‌که وصلهٔ بانکِ ایده اعمال شده باشد
    from apps.ideabank import selftest as _ib
except Exception:  # noqa: BLE001
    _ib = None

from . import SelfTest, Spec, Verdict, register
from .ollama import _configured, _text_available, pick_text


def build(ctx):
    model = pick_text(ctx.installed_ollama(), _configured("text"))
    s = _ib.node_spec(model)
    return Spec(s["kind"], s["payload"], timeout_s=int(s.get("timeout_s") or 1800))


def check(ctx, job):
    data = ctx.read_json(job, "ollama.json")
    meta = ctx.meta(job)
    if not isinstance(data, dict):
        return Verdict.failed("جوابِ ollama.json نرسید.", device=meta.get("device", ""))
    text = str(data.get("response") or (data.get("message") or {}).get("content") or "").strip()
    model = (job.payload or {}).get("model")
    if len(text) < 40:
        return Verdict.failed("مدلِ «%s» جوابِ خیلی کوتاه داد (%d نویسه)." % (model, len(text)), device=meta.get("device", ""))
    ok, message = _ib.node_check(text)
    detail = "«%s» · %s" % (model, message)
    return Verdict.passed(detail, device=meta.get("device", "")) if ok else Verdict.failed(detail, device=meta.get("device", ""))


def virtual(ctx):
    res = _ib.run_offline()
    failed = [c for c in res["checks"] if not c["ok"]]
    if failed:
        return Verdict.failed("؛ ".join("%s: %s" % (c["key"], c["detail"]) for c in failed)[:400])
    return Verdict.passed("؛ ".join("%s ✓" % c["key"] for c in res["checks"]))


if _ib is not None:
    register(SelfTest(key="ideabank_ai", label="بانکِ ایده: «ایده بساز» با مدلِ خودِ شما", group="text", kind="ollama.generate", build=build, check=check,
                      available=_text_available, gpu_required=False, optional=True, order=33, after=("ollama_text",),
                      requeue={"kinds": ("ollama.generate",)},
                      describe="پرسشِ واقعیِ ایده‌ساز برای چغر؛ باید JSONِ فارسیِ معتبر و بی‌عدد و بی‌قیمت بدهد"))
    register(SelfTest(key="ideabank_seeds", label="بانکِ ایده: ایده‌های آماده و فرمول‌ها", group="system", virtual=virtual, optional=True, order=97,
                      describe="بی‌گره: ایده‌های آماده، جای‌گیرها، فرمول‌ها و مسیرِ هوش مصنوعی با جوابِ ساختگی"))

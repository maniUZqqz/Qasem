"""آزمونِ «تلفظِ فارسی»: چند جملهٔ ثابت با Piper (پیش و پس از لایهٔ تلفظ) روی گره گفته می‌شود، Whisper روی کارت گوش می‌دهد، سایت می‌سنجد.

قبول یعنی: (۱) گره Piper و تشخیصِ گفتار را خودش نصب کرده و هر دو کار می‌کنند، (۲) بیش از ۸۰٪ فایل‌ها چیزی شنیده شد، (۳) خطای واژه «پس از لایه» از
سقفِ منطقی کمتر است و از «پیش» بیشتر بدتر نشده. بعد از قبولی، سنجشِ کامل (همهٔ جمله‌های آزمون) خودش در صفِ ماندگار گذاشته می‌شود (apps.pronunciation.evalrun).
دستورِ کار: docs/pronunciation/README-fa.md.
"""
from . import SelfTest, Spec, Verdict, caps_ok, register

#: اندیسِ جمله‌های ثابتِ آزمون در fa_pron.eval_set (ع، ه، و/او، اضافه، عدد، تاریخ) — «فقط افزودنی» است، پس این اندیس‌ها همیشه همان جمله‌اند
SENTENCE_IDS = (0, 30, 61, 114, 134, 149,
                230, 244, 254)      # + دورِ دوم: «برنامه‌ی تمرینی» (ه‌ی)، «خروجی PDF» (سرواژه)، «او کشتی می‌گیرد» (هم‌نویسه با فعل)
VOICE = "fa_IR-amir-medium"
MAX_AFTER = 0.60            # بالاتر از این یعنی صدا یا تشخیص خراب است
MAX_WORSE = 0.15            # «پس» از «پیش» بیشتر از این بدتر نباشد


def _kinds_ok(node):
    kinds = (node.capabilities or {}).get("kinds")
    if isinstance(kinds, list) and "voice.pron_eval" not in kinds:
        return False, "عاملِ این سرور هنوز «voice.pron_eval» را نمی‌شناسد (به‌روزرسانیِ عامل لازم است)"
    if not isinstance(kinds, list):
        return False, "عاملِ این سرور قدیمی است (۲٫۱۱ به بعد لازم است)"
    return caps_ok(node, "voice", why="سرویسِ صدا (PersianAiKit.Voice) روی این سرور نیست")


def _items(engine="piper"):
    from apps.pronunciation import evalrun
    from services.audio.fa_pron import eval_set

    rows = [(i, eval_set.SENTENCES[i][0], eval_set.SENTENCES[i][1]) for i in SENTENCE_IDS if i < len(eval_set.SENTENCES)]
    items, _ = evalrun.build_items(engine, rows, store=None)
    return rows, items


def build(ctx):
    rows, items = _items()
    return Spec("voice.pron_eval", {"engine": "piper", "voice": VOICE, "language": "fa", "items": items}, timeout_s=1800)


def check(ctx, job):
    from services.audio.fa_pron import eval_set, quality

    data = ctx.read_json(job, "result.json")
    if not isinstance(data, dict) or not data.get("items"):
        return Verdict.failed("result.json نرسید یا خالی است")
    asr = data.get("asr") or {}
    heard = {(int(i["id"]), i["variant"]): i.get("hyp", "") for i in data["items"]}
    empty = sum(1 for v in heard.values() if not str(v).strip())
    if len(heard) < 2 * len(SENTENCE_IDS) or empty > 0.2 * len(heard):
        return Verdict.failed("تشخیصِ گفتار برای %d از %d فایل چیزی نشنید" % (empty, len(heard)), device=str(asr.get("device") or ""))
    before = quality.corpus_wer([(eval_set.SENTENCES[i][1], heard.get((i, "before"), "")) for i in SENTENCE_IDS])
    after = quality.corpus_wer([(eval_set.SENTENCES[i][1], heard.get((i, "after"), "")) for i in SENTENCE_IDS])
    device = str(asr.get("device") or "")
    warning = "تشخیصِ گفتار روی پردازنده اجرا شد (%s)" % (asr.get("note") or "کارت استفاده نشد") if device == "cpu" else ""
    if after > MAX_AFTER:
        return Verdict.failed("خطای واژه پس از لایه %d٪ است (سقف %d٪)" % (round(after * 100), round(MAX_AFTER * 100)), device=device)
    if after > before + MAX_WORSE:
        return Verdict.failed("لایه صدا را بدتر کرد: خطای واژه %d٪ ← %d٪" % (round(before * 100), round(after * 100)), device=device)
    try:
        from apps.pronunciation import evalrun

        evalrun.ensure_full_runs()
    except Exception:  # noqa: BLE001 — آزمونِ گره به سنجشِ کامل بستگی ندارد
        pass
    return Verdict.passed("Piper · خطای واژه %d٪ ← %d٪ (Whisper %s، %s)" % (round(before * 100), round(after * 100), asr.get("model") or "", device),
                          device=device, warning=warning, extra={"wer_before": round(before, 3), "wer_after": round(after, 3)})


register(SelfTest(key="pron_piper", label="تلفظِ فارسی: Piper پیش و پس از لایه + تشخیصِ گفتار", group="audio", kind="voice.pron_eval", build=build,
                  check=check, available=_kinds_ok, order=75, needs_features=("pron",),
                  files=("pron_jobs.py", "pron_synth_worker.py", "pron_asr_worker.py", "requirements.d/pron.json"),
                  requeue={"kinds": ("voice.pron_eval", "voice.pron_asr")},
                  describe="نُه جملهٔ ثابت (از جمله «ه‌ی»، سرواژه و هم‌نویسه با فعل) دو بار گفته و شنیده می‌شود؛ نصبِ Piper و Whisper خودکار است و تا آماده شدنش آزمون منتظر می‌ماند"))


# ---------------------------------------------------------------- «گوش‌دادن به صدای ساخته‌شدهٔ سایت» (voice.pron_asr)
# مسیرِ Edge در سنجش صدایی را که خودِ سایت ساخته به گره می‌فرستد و گره فقط گوش می‌دهد. این آزمون یک ضبطِ کوتاهِ Piperِ سایت را می‌فرستد و می‌سنجد
# که Whisperِ گره آن را می‌شنود؛ یعنی آزمونِ پذیرشِ نوعِ کارِ «voice.pron_asr» (همان شرطی که tests_catalog برای هر نوعِ کارِ نصب‌دار می‌خواهد).
ASR_SENTENCE = SENTENCE_IDS[0]


def _kinds_ok_asr(node):
    kinds = (node.capabilities or {}).get("kinds")
    if not isinstance(kinds, list) or "voice.pron_asr" not in kinds:
        return False, "عاملِ این سرور هنوز «voice.pron_asr» را نمی‌شناسد (به‌روزرسانیِ عامل لازم است)"
    return True, ""


def build_asr(ctx):
    import pathlib
    import tempfile

    from apps.pronunciation import services as pron_svc
    from services.audio import tts
    from services.audio.fa_pron import eval_set

    try:
        voice = pron_svc.site_piper_voice("")          # the site only has the voices audio_setup downloaded (gyro, mana, ganji ...), not always amir
        with tempfile.TemporaryDirectory(prefix="pron_asr_") as folder:
            provider = tts.PiperProvider(voice)
            provider.store, provider.language, provider.use_pron = None, "fa", False
            data = pathlib.Path(provider.synthesize(eval_set.SENTENCES[ASR_SENTENCE][1], pathlib.Path(folder) / "s.wav")).read_bytes()
    except Exception:  # noqa: BLE001 — صدای Piper روی سایت نیست: آزمون «ردشده» می‌شود، نه «رد»
        return None
    name = "pron_asr_before.wav"
    return Spec("voice.pron_asr", {"engine": "piper", "voice": voice, "files": [{"id": ASR_SENTENCE, "variant": "before", "name": name}]},
                files={name: data}, timeout_s=1800)


def check_asr(ctx, job):
    from services.audio.fa_pron import eval_set, quality

    data = ctx.read_json(job, "result.json")
    rows = (data or {}).get("items") or []
    asr = (data or {}).get("asr") or {}
    device = str(asr.get("device") or "")
    hyp = next((str(r.get("hyp") or "") for r in rows if r.get("variant") == "before"), "")
    if not hyp.strip():
        return Verdict.failed("تشخیصِ گفتار چیزی نشنید (result.json نرسید یا خالی است)", device=device)
    wer = quality.corpus_wer([(eval_set.SENTENCES[ASR_SENTENCE][1], hyp)])
    if wer > MAX_AFTER:
        return Verdict.failed("خطای واژه %d٪ است (سقف %d٪): صدا یا تشخیص خراب است" % (round(wer * 100), round(MAX_AFTER * 100)), device=device)
    warning = "تشخیصِ گفتار روی پردازنده اجرا شد (%s)" % (asr.get("note") or "کارت استفاده نشد") if device == "cpu" else ""
    return Verdict.passed("Whisper %s روی %s · خطای واژه %d٪" % (asr.get("model") or "", device or "؟", round(wer * 100)), device=device, warning=warning,
                          extra={"wer": round(wer, 3)})


register(SelfTest(key="pron_asr", label="تلفظِ فارسی: گوش‌دادن به صدای ساخته‌شدهٔ سایت (Whisper)", group="audio", kind="voice.pron_asr", build=build_asr,
                  check=check_asr, available=_kinds_ok_asr, order=76, after=("pron_piper",), needs_features=("pron",),
                  files=("pron_jobs.py", "pron_asr_worker.py", "requirements.d/pron.json"),
                  requeue={"kinds": ("voice.pron_asr",)},
                  describe="یک جملهٔ ثابت را سایت با Piper می‌سازد و گره فقط گوش می‌دهد (همان مسیری که صدای Edge در سنجش می‌رود)"))

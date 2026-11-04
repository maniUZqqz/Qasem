"""«پرکردنِ هوشمند»: ترجمهٔ توضیحِ فارسی به انگلیسی — با مترجمِ ساختگی (هیچ آزمونی هوشِ مصنوعیِ واقعی یا اعتبارِ متیس صرف نمی‌کند).

* ماژولِ ``translate``: فارسی، انگلیسی، ترکیبی، خروجیِ بد (تلاشِ دوباره)، مترجمِ ناموجود، کَش.
* سرویس/API: کارِ منتظرِ ترجمه (گره نمی‌گیردش)، آزادشدن با رسیدنِ مترجم یا با انگلیسیِ نوشتهٔ کاربر، شکست، لغو، پیش‌نمایش.
"""
import io
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode

from . import inpaint_graph as ig, services, translate
from .tests import ApiTestBase, photo
from .tests_inpaint import disc_mask, png_file


class FakeLLM:
    """همان رابطِ RoutedTextProvider: generate / describe / availability."""

    def __init__(self, replies=(), *, error=None, available=(True, ""), label="لوکال (gemma3:12b)"):
        self.replies = list(replies)
        self.error = error
        self.available = available
        self.calls: list[tuple[str, dict]] = []
        self.label = label

    def availability(self):
        return self.available

    def generate(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self.error is not None:
            raise self.error
        return self.replies.pop(0) if self.replies else ""

    def describe(self):
        return {"via": "local", "model": "gemma3:12b", "label": self.label, "fell_back": False, "fallback_reason": ""}


class AllFailed(Exception):
    """به نامِ کلاسِ routing.AllProvidersFailed تا explain() مثلِ تولید رفتار کند."""


AllFailed.__name__ = "AllProvidersFailed"
OFFLINE_WHY = "لوکال: سرورِ پردازش خاموش است؛ متیس: اعتبار حساب تمام شده است (۴۰۲)"


class CacheDirMixin:
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="nmtr-")
        self._ov = override_settings(NM_DATA_DIR=Path(self._tmp))
        self._ov.enable()
        self.store = SimpleNamespace(pk=7)

    def tearDown(self):
        self._ov.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().tearDown()


class TextTests(SimpleTestCase):
    def test_script_detection(self):
        self.assertTrue(translate.needs_translation("آسمان آبی"))
        self.assertTrue(translate.needs_translation("a red vase با گل"))        # ترکیبی
        self.assertFalse(translate.needs_translation("blue sky over 3 hills"))
        self.assertFalse(translate.needs_translation(""))
        self.assertFalse(translate.needs_translation("   "))

    def test_normalize_and_cache_key(self):
        self.assertEqual(translate.normalize("  سیبِ   قرمز \n "), "سیبِ قرمز")
        self.assertEqual(translate.normalize("كتاب ياقوت"), "کتاب یاقوت")          # ی/ک عربی ⇐ فارسی
        self.assertEqual(translate.for_model("۳ سیب و ٤ گلابی"), "3 سیب و 4 گلابی")
        self.assertEqual(translate.key_for("می‌خواهم ۳ سیب"), translate.key_for("می خواهم 3  سیب"))
        self.assertNotEqual(translate.key_for("سیب"), translate.key_for("گلابی"))

    def test_valid_english(self):
        self.assertTrue(translate.valid_english("blue sky"))
        self.assertFalse(translate.valid_english("آسمان آبی"))
        self.assertFalse(translate.valid_english("blue آبی"))
        self.assertFalse(translate.valid_english(""))
        self.assertFalse(translate.valid_english("12 34"))
        self.assertFalse(translate.valid_english("x" * 600))

    def test_output_checks(self):
        src = "یک گلدان آبی روی میز"
        ok, t = translate.check_output('English: "a blue vase on the table"', src)
        self.assertEqual((ok, t), (True, "a blue vase on the table"))             # برچسب و نقل‌قول برداشته می‌شود
        for bad in ("", "یک گلدان آبی", "a blue vase\nNote: kept literal", "Sure! Here is the translation: a blue vase",
                    "I'm sorry, I cannot translate that", "x", "a " * 200, "12 34 56"):
            self.assertFalse(translate.check_output(bad, src)[0], bad)
        # بیش‌ازحد بلند نسبت به ورودی (ورودیِ کوتاه، خروجیِ مقاله)
        self.assertFalse(translate.check_output("a beautiful " * 12, "گل")[0])

    def test_example_leak_is_rejected_but_a_matching_input_is_fine(self):
        fa, en = translate.EXAMPLES[0]
        self.assertFalse(translate.check_output(en, "یک ماشین قرمز در خیابان")[0])     # مدل مثال را بازگو کرده
        self.assertTrue(translate.check_output(en, fa.replace("ِ", ""))[0])           # ورودیِ همان مثال ⇒ درست


class TranslateTests(CacheDirMixin, SimpleTestCase):
    def test_persian_is_translated_with_the_dedicated_low_temperature_instruction(self):
        llm = FakeLLM(["a blue glass vase on 3 wooden shelves"])
        tr = translate.translate("یک گلدان شیشه‌ای آبی روی ۳ قفسهٔ چوبی", store=self.store, provider=llm)
        self.assertEqual((tr.en, tr.source, tr.cached), ("a blue glass vase on 3 wooden shelves", "auto", False))
        self.assertEqual((tr.via, tr.model, tr.label), ("local", "gemma3:12b", "لوکال (gemma3:12b)"))
        self.assertEqual(len(llm.calls), 1)
        prompt, kw = llm.calls[0]
        self.assertEqual(kw["temperature"], 0.1)
        self.assertLessEqual(kw["num_predict"], 200)
        self.assertEqual(kw["system"], translate.SYSTEM)
        for rule in ("Translate only", "Do not add", "one short line", "digits"):
            self.assertIn(rule, translate.SYSTEM)
        self.assertIn("3 قفسهٔ چوبی", prompt)                                         # رقمِ فارسی به ASCII رفت
        self.assertNotIn("۳", prompt)

    def test_english_and_empty_skip_the_translator(self):
        llm = FakeLLM(["should never be used"])
        for text in ("blue sky over the sea", "", "   "):
            tr = translate.translate(text, store=self.store, provider=llm)
            self.assertEqual((tr.source, tr.en), ("none", translate.normalize(text)))
        self.assertEqual(llm.calls, [])

    def test_mixed_text_is_translated_and_keeps_english_words(self):
        llm = FakeLLM(["a red vase with flowers"])
        tr = translate.translate("یک vase قرمز با گل", store=self.store, provider=llm)
        self.assertEqual(tr.en, "a red vase with flowers")
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("vase", llm.calls[0][0])

    def test_bad_output_is_retried_once_then_accepted(self):
        llm = FakeLLM(["آسمان آبی", "blue sky"])                  # پژواکِ فارسی ⇒ ردّ ⇒ تلاشِ دوم
        tr = translate.translate("آسمان آبی", store=self.store, provider=llm)
        self.assertEqual(tr.en, "blue sky")
        self.assertEqual(len(llm.calls), 2)
        self.assertNotIn(translate.RETRY_HINT, llm.calls[0][0])
        self.assertIn(translate.RETRY_HINT, llm.calls[1][0])

    def test_bad_output_twice_fails_and_nothing_is_cached(self):
        for first, second in (("Sure! Here is the translation: blue sky", "blue sky\nNote: literal"), ("", "x"),
                              ("آسمان آبی", "یک آسمان")):
            llm = FakeLLM([first, second])
            with self.assertRaises(translate.Failed) as cm:
                translate.translate("آسمان آبی", store=self.store, provider=llm)
            self.assertEqual(len(llm.calls), 2)                  # فقط یک بار تلاشِ دوباره
            self.assertIn("ترجمهٔ خودکار درست درنیامد", str(cm.exception))
            self.assertIsNone(translate.cache_get(self.store, "آسمان آبی"))

    def test_translator_unavailable(self):
        # ۱) مسیریاب از پیش می‌گوید هیچ مسیری نیست (گره خاموش و متیس ۴۰۲) ⇒ حتی صدا هم زده نمی‌شود
        off = FakeLLM(["x"], available=(False, OFFLINE_WHY))
        with self.assertRaises(translate.Unavailable) as cm:
            translate.translate("آسمان آبی", store=self.store, provider=off)
        self.assertEqual(off.calls, [])
        self.assertIn("هیچ مترجمی در دسترس نیست", str(cm.exception))
        self.assertEqual(cm.exception.reason, OFFLINE_WHY)
        # ۲) هر دو مسیر در لحظهٔ صدا زدن شکست خوردند (AllProvidersFailed با متنِ فارسیِ دلیل)
        boom = FakeLLM(error=AllFailed("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — " + OFFLINE_WHY))
        with self.assertRaises(translate.Unavailable) as cm:
            translate.translate("آسمان آبی", store=self.store, provider=boom)
        self.assertIn("۴۰۲", cm.exception.reason)
        # ۳) خطای HTTP ۴۰۲ خام ⇒ همان جملهٔ فارسیِ priority.classify
        pay = FakeLLM(error=RuntimeError("HTTP 402 payment required"))
        with self.assertRaises(translate.Unavailable) as cm:
            translate.translate("آسمان آبی", store=self.store, provider=pay)
        self.assertIn("اعتبار", cm.exception.reason)
        # ۴) خودِ ساختنِ مترجم شکست خورد (مثلاً سیاستِ داده)
        with mock.patch.object(translate, "get_provider", side_effect=RuntimeError("سیاستِ داده اجازه نمی‌دهد")):
            with self.assertRaises(translate.Unavailable) as cm:
                translate.translate("آسمان آبی", store=self.store)
        self.assertIn("سیاستِ داده", cm.exception.reason)

    def test_real_gateway_is_never_called_under_test(self):
        with self.assertRaises(translate.Unavailable) as cm:
            translate.translate("آسمان آبی", store=self.store)
        self.assertIn("زیرِ آزمون", str(cm.exception))

    def test_cache_hit_skips_the_translator(self):
        llm = FakeLLM(["blue sky with white clouds"])
        first = translate.translate("آسمانِ آبی با ابرهای سفید", store=self.store, provider=llm)
        self.assertFalse(first.cached)
        # همان متن با نیم‌فاصله/ارقام/فاصلهٔ متفاوت ⇒ همان ردیفِ کَش
        again = FakeLLM(["SHOULD NOT BE USED"])
        second = translate.translate("  آسمانِ  آبی با ابرهای سفید ", store=self.store, provider=again)
        self.assertEqual((second.en, second.cached, second.source), ("blue sky with white clouds", True, "cache"))
        self.assertEqual(second.label, "لوکال (gemma3:12b)")
        self.assertEqual(again.calls, [])
        # فروشگاهِ دیگر ⇐ کَشِ جدا
        other = translate.translate("آسمانِ آبی با ابرهای سفید", store=SimpleNamespace(pk=8), provider=FakeLLM(["clear blue sky"]))
        self.assertEqual(other.en, "clear blue sky")
        # حتی با مترجمِ ناموجود، کَش جواب می‌دهد
        self.assertEqual(translate.translate("آسمانِ آبی با ابرهای سفید", store=self.store,
                                             provider=FakeLLM(available=(False, "x"))).en, "blue sky with white clouds")

    def test_user_correction_is_remembered(self):
        translate.translate("سیب", store=self.store, provider=FakeLLM(["apple"]))
        translate.remember_user(self.store, "سیب", "a red apple")
        got = translate.translate("سیب", store=self.store, provider=FakeLLM(available=(False, "x")))
        self.assertEqual((got.en, got.cached), ("a red apple", True))
        translate.remember_user(self.store, "سیب", "سیب فارسی")       # فارسی را نمی‌پذیرد
        self.assertEqual(translate.cache_get(self.store, "سیب").en, "a red apple")

    def test_cache_survives_version_bump_by_ignoring_old_rows(self):
        translate.translate("سیب", store=self.store, provider=FakeLLM(["apple"]))
        with mock.patch.object(translate, "VERSION", "99"):
            self.assertIsNone(translate.cache_get(self.store, "سیب"))


class PreviewTests(CacheDirMixin, SimpleTestCase):
    def run_now(self, store_id, fa):
        translate.run_preview(self.store, fa)

    def test_states(self):
        calls = []

        def dispatch(sid, fa):
            calls.append(fa)
            self.run_now(sid, fa)

        none = translate.preview_request(self.store, "blue sky", dispatch)
        self.assertEqual((none["state"], none["needed"], none["en"]), ("none", False, "blue sky"))
        self.assertEqual(calls, [])
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["blue sky"])):
            ok = translate.preview_request(self.store, "آسمان آبی", dispatch)
        self.assertEqual((ok["state"], ok["en"], ok["needed"]), ("ok", "blue sky", True))
        again = translate.preview_request(self.store, "آسمان آبی", dispatch)             # کَش ⇒ بی‌صدا زدن
        self.assertEqual((again["state"], again["cached"]), ("ok", True))
        self.assertEqual(len(calls), 1)
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(available=(False, OFFLINE_WHY))):
            off = translate.preview_request(self.store, "گربهٔ سیاه", dispatch)
        self.assertEqual(off["state"], "unavailable")
        self.assertIn("هیچ مترجمی در دسترس نیست", off["message"])
        self.assertIn("۴۰۲", off["message"])
        n = len(calls)
        self.assertEqual(translate.preview_request(self.store, "گربهٔ سیاه", dispatch)["state"], "unavailable")
        self.assertEqual(len(calls), n)                                                  # چند ثانیه نگه داشته می‌شود
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["", "x"])):
            bad = translate.preview_request(self.store, "اسبِ سفید", dispatch)
        self.assertEqual(bad["state"], "failed")
        self.assertIn("درست درنیامد", bad["message"])

    def test_pending_is_reported_while_the_worker_has_not_finished(self):
        res = translate.preview_request(self.store, "آسمان آبی", lambda sid, fa: None)        # celery هنوز کاری نکرده
        self.assertEqual(res["state"], "pending")
        # دوباره پرسیدن در همان فاصله ⇒ باز pending و کارِ دومی صف نمی‌شود
        calls = []
        res = translate.preview_request(self.store, "آسمان آبی", lambda sid, fa: calls.append(fa))
        self.assertEqual((res["state"], calls), ("pending", []))


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class GenFillTranslationApiTests(ApiTestBase):
    W, H = 900, 700

    def setUp(self):
        super().setUp()
        (self.aid,) = self.upload(photo(self.W, self.H, seed=5))
        self.scene = photo(self.W, self.H, seed=9)
        self.mask = disc_mask(self.W, self.H, 450, 350, 55)
        self.url = f"{self.base}/genfill/"

    def post(self, **fields):
        body = {"image": png_file(self.scene, "image.png"), "mask": png_file(self.mask, "mask.png"), "asset": self.aid} | fields
        return self.api.post(self.url, body, format="multipart")

    def job(self, uid):
        return ComputeJob.objects.get(uid=uid)

    def comfy_node(self):
        return ComputeNode.objects.create(name="gpu-comfy", last_seen=timezone.now(),
                                          capabilities={"photo": True} | services.genfill_fake_caps())

    def graph_text(self, uid):
        return self.job(uid).payload["graph"]["20"]["inputs"]["text"]

    # ── مترجم نیست: کار گم نمی‌شود

    def test_persian_without_a_translator_is_held_and_no_node_can_take_it(self):
        node = self.comfy_node()
        r = self.post(prompt="یک آسمان آبی با ابر", seed="3")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["state"], "QUEUED")
        tr = body["translation"]
        self.assertEqual(tr["state"], "waiting")
        self.assertEqual(tr["fa"], "یک آسمان آبی با ابر")
        for part in ("هیچ مترجمی در دسترس نیست", "کار گم نمی‌شود", "انگلیسی بنویسید"):
            self.assertIn(part, body["message"])
        job = self.job(body["job"])
        self.assertEqual(job.node_wanted, services.GENFILL_HOLD)
        self.assertEqual(job.state, ComputeJob.State.QUEUED)
        self.assertIsNone(compute.claim(node))                     # گرهٔ آنلاین هم آن را نمی‌گیرد
        st = self.api.get(f"{self.url}{body['job']}/").json()
        self.assertEqual((st["state"], st["translation"]["state"]), ("QUEUED", "waiting"))
        self.assertIn("هیچ مترجمی در دسترس نیست", st["message"])
        self.assertGreater(st["progress"], 0)
        self.assertEqual(self.job(body["job"]).payload["x_genfill"]["prompt_fa"], "یک آسمان آبی با ابر")

    def test_translator_arrives_later_job_is_translated_released_and_runs(self):
        node = self.comfy_node()
        body = self.post(prompt="یک آسمان آبی با ابر", seed="3").json()
        uid = body["job"]
        self.assertIsNone(compute.claim(node))
        self.assertEqual(services.genfill_translate_step(uid), "waiting")             # هنوز بی‌مترجم (زیرِ آزمون)
        self.assertEqual(self.job(uid).payload["x_genfill"]["tr"]["attempts"], 2)       # یکی از ثبت (eager) و یکی از همین گام
        llm = FakeLLM(["a blue sky with clouds"])
        with mock.patch.object(translate, "get_provider", return_value=llm):
            self.assertEqual(services.genfill_translate_step(uid), "done")
        job = self.job(uid)
        self.assertEqual(job.node_wanted, "")                                          # به مقدارِ اصلی برگشت
        g = job.payload["graph"]
        self.assertIn("a blue sky with clouds", g["20"]["inputs"]["text"])
        self.assertNotIn("آسمان", g["20"]["inputs"]["text"])
        self.assertEqual(ig.validate(g), [])
        meta = job.payload["x_genfill"]
        self.assertEqual((meta["prompt"], meta["prompt_fa"]), ("a blue sky with clouds", "یک آسمان آبی با ابر"))
        self.assertEqual(meta["tr"]["state"], "ok")
        self.assertEqual(meta["tr"]["label"], "لوکال (gemma3:12b)")
        self.assertEqual(services.genfill_translate_step(uid), "gone")                 # دوباره‌کاری نمی‌کند
        claimed = compute.claim(node)
        self.assertIsNotNone(claimed)                                                  # حالا گره می‌گیرد
        self.assertEqual(str(claimed.uid), uid)

    def test_translated_job_shows_translation_on_the_result(self):
        node = self.comfy_node()
        uid = self.post(prompt="یک آسمان آبی", seed="3").json()["job"]
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["a blue sky"])):
            services.genfill_translate_step(uid)
        services.genfill_finish_for_test(self.job(uid), node)
        st = self.api.get(f"{self.url}{uid}/").json()
        self.assertEqual(st["state"], "READY", st)
        self.assertEqual((st["translation"]["state"], st["translation"]["en"], st["translation"]["fa"]),
                         ("ok", "a blue sky", "یک آسمان آبی"))

    def test_translator_ready_at_request_time_releases_immediately(self):
        llm = FakeLLM(["a red apple on a table"])
        with mock.patch.object(translate, "get_provider", return_value=llm):
            r = self.post(prompt="یک سیب قرمز روی میز")
        body = r.json()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(body["translation"]["state"], "ok")
        self.assertEqual(body["translation"]["en"], "a red apple on a table")
        self.assertNotIn("هیچ مترجمی", body["message"])
        job = self.job(body["job"])
        self.assertEqual(job.node_wanted, "")
        self.assertIn("a red apple on a table", self.graph_text(body["job"]))
        self.assertEqual(len(llm.calls), 1)

    def test_cached_translation_needs_no_hold_and_no_call(self):
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["a red apple"])):
            translate.translate("سیب قرمز", store=self.store)
        body = self.post(prompt="سیب قرمز").json()                                       # مترجم دیگر در دسترس نیست؛ کَش هست
        self.assertEqual(body["translation"]["state"], "ok")
        self.assertEqual(body["translation"]["source"], "cache")
        self.assertEqual(self.job(body["job"]).node_wanted, "")
        self.assertIn("a red apple", self.graph_text(body["job"]))

    # ── انگلیسیِ نوشتهٔ کاربر / ترجمهٔ ویرایش‌شده

    def test_edited_translation_is_used_as_is_and_remembered(self):
        body = self.post(prompt="سیب قرمز", prompt_en="a shiny red apple").json()
        self.assertEqual(body["translation"]["state"], "ok")
        self.assertEqual(body["translation"]["source"], "user")
        job = self.job(body["job"])
        self.assertEqual(job.node_wanted, "")
        self.assertIn("a shiny red apple", self.graph_text(body["job"]))
        self.assertEqual(job.payload["x_genfill"]["prompt_fa"], "سیب قرمز")
        self.assertEqual(translate.cache_get(self.store, "سیب قرمز").en, "a shiny red apple")

    def test_english_prompt_and_empty_prompt_are_untouched(self):
        for prompt, want_state in (("blue sky", "none"), ("", "none")):
            body = self.post(prompt=prompt).json()
            self.assertEqual(body["translation"]["state"], want_state)
            self.assertEqual(self.job(body["job"]).node_wanted, "")
        # prompt_en برای متنِ انگلیسی نادیده است
        body = self.post(prompt="blue sky", prompt_en="something else").json()
        self.assertIn("blue sky", self.graph_text(body["job"]))
        self.assertNotIn("something else", self.graph_text(body["job"]))
        # خالی ⇒ هنوز «حذف و پر کردن»
        body = self.post().json()
        self.assertEqual(self.graph_text(body["job"]), ig.DEFAULT_PROMPT)

    def test_persian_in_the_english_field_is_refused(self):
        r = self.post(prompt="سیب", prompt_en="سیب قرمز")
        self.assertEqual(r.status_code, 400)
        self.assertIn("حرفِ لاتین", r.json()["error"]["message"])
        self.assertEqual(ComputeJob.objects.filter(origin="photogenfill").count(), 0)

    def test_user_types_english_for_a_held_job_and_it_is_released(self):
        node = self.comfy_node()
        uid = self.post(prompt="گربهٔ سیاه روی مبل").json()["job"]
        self.assertEqual(self.job(uid).node_wanted, services.GENFILL_HOLD)
        r = self.api.post(f"{self.url}{uid}/prompt/", {"prompt_en": "a black cat on a sofa"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        st = r.json()
        self.assertEqual((st["translation"]["state"], st["translation"]["source"], st["translation"]["en"]),
                         ("ok", "user", "a black cat on a sofa"))
        job = self.job(uid)
        self.assertEqual(job.node_wanted, "")
        self.assertIn("a black cat on a sofa", self.graph_text(uid))
        self.assertEqual(str(compute.claim(node).uid), uid)
        # بار دوم: دیگر منتظر نیست
        r = self.api.post(f"{self.url}{uid}/prompt/", {"prompt_en": "again"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("دیگر منتظرِ ترجمه نیست", r.json()["error"]["message"])

    def test_prompt_endpoint_validation_and_isolation(self):
        uid = self.post(prompt="گربهٔ سیاه").json()["job"]
        for bad in ("", "گربه", "x", "12"):
            r = self.api.post(f"{self.url}{uid}/prompt/", {"prompt_en": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.job(uid).node_wanted, services.GENFILL_HOLD)
        self.assertEqual(self.api.post(f"{self.url}00000000-0000-0000-0000-000000000000/prompt/", {"prompt_en": "a cat"},
                                       format="json").status_code, 404)

    # ── شکست و لغو

    def test_bad_translator_output_twice_fails_the_job_with_a_persian_reason(self):
        node = self.comfy_node()
        uid = self.post(prompt="گربهٔ سیاه").json()["job"]
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["گربه", "Sure! cat\nmore"])):
            self.assertEqual(services.genfill_translate_step(uid), "failed")
        job = self.job(uid)
        self.assertEqual(job.state, ComputeJob.State.FAILED)
        self.assertIsNone(compute.claim(node))
        st = self.api.get(f"{self.url}{uid}/").json()
        self.assertEqual(st["state"], "FAILED")
        self.assertIn("ترجمهٔ خودکار درست درنیامد", st["error"])
        self.assertIn("انگلیسی بنویسید", st["error"])
        self.assertNotIn("ساختنِ تصویر روی سرورِ پردازش ناموفق", st["error"])

    def test_cancel_a_held_job(self):
        node = self.comfy_node()
        uid = self.post(prompt="گربهٔ سیاه").json()["job"]
        self.assertEqual(self.api.delete(f"{self.url}{uid}/").status_code, 204)
        self.assertEqual(self.job(uid).state, ComputeJob.State.CANCELLED)
        self.assertEqual(services.genfill_translate_step(uid), "gone")
        self.assertIsNone(compute.claim(node))

    def test_a_job_waiting_for_three_days_gives_up_clearly(self):
        uid = self.post(prompt="گربهٔ سیاه").json()["job"]
        job = self.job(uid)
        payload = job.payload
        payload["x_genfill"]["tr"]["since"] = (timezone.now() - timedelta(hours=services.GENFILL_TR_GIVE_UP_H + 1)).isoformat()
        ComputeJob.objects.filter(pk=job.pk).update(payload=payload)
        self.assertEqual(services.genfill_translate_step(uid), "failed")
        st = self.api.get(f"{self.url}{uid}/").json()
        self.assertEqual(st["state"], "FAILED")
        self.assertIn("۷۲ ساعت", st["error"])

    def test_two_steps_at_once_do_not_clash(self):
        uid = self.post(prompt="گربهٔ سیاه").json()["job"]
        job = self.job(uid)
        lock = services._genfill_dir(job.store, job.payload["x_genfill"]["asset"]) / f"{uid[:12]}.tr.lock"
        lock.write_text("x")
        self.assertEqual(services.genfill_translate_step(uid), "busy")
        lock.unlink()

    def test_status_poll_restarts_a_dead_retry_chain(self):
        uid = self.post(prompt="گربهٔ سیاه").json()["job"]
        job = self.job(uid)
        payload = job.payload
        payload["x_genfill"]["tr"]["last_try"] = (timezone.now() - timedelta(seconds=services.GENFILL_TR_STALE_S + 5)).isoformat()
        ComputeJob.objects.filter(pk=job.pk).update(payload=payload)
        attempts = self.job(uid).payload["x_genfill"]["tr"]["attempts"]
        self.api.get(f"{self.url}{uid}/")                      # eager ⇒ همین‌جا یک گامِ تازه
        self.assertEqual(self.job(uid).payload["x_genfill"]["tr"]["attempts"], attempts + 1)
        again = self.job(uid).payload["x_genfill"]["tr"]["attempts"]
        self.api.get(f"{self.url}{uid}/")                      # تازه امتحان شده ⇒ بی‌دلیل تکرار نمی‌شود
        self.assertEqual(self.job(uid).payload["x_genfill"]["tr"]["attempts"], again)

    # ── پیش‌نمایشِ پنل

    def test_preview_endpoint(self):
        url = f"{self.url}translate/"
        r = self.api.post(url, {"prompt": "blue sky"}, format="json")
        self.assertEqual((r.status_code, r.json()["state"], r.json()["needed"]), (200, "none", False))
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["a blue sky"])):
            r = self.api.post(url, {"prompt": "آسمان آبی"}, format="json")
        self.assertEqual((r.json()["state"], r.json()["en"], r.json()["label"]), ("ok", "a blue sky", "لوکال (gemma3:12b)"))
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(available=(False, OFFLINE_WHY))):
            r = self.api.post(url, {"prompt": "گربهٔ سیاه"}, format="json")
        body = r.json()
        self.assertEqual((r.status_code, body["state"]), (200, "unavailable"))
        self.assertIn("هیچ مترجمی در دسترس نیست", body["message"])
        self.assertEqual(self.api.post(url, {"prompt": ""}, format="json").json()["state"], "none")

    def test_preview_requires_login_and_store_access(self):
        from rest_framework.test import APIClient

        self.assertIn(APIClient().post(f"{self.url}translate/", {"prompt": "سیب"}, format="json").status_code, (401, 403))

    def test_old_clients_without_prompt_en_still_work(self):
        # نسخهٔ قدیمیِ پنل فقط prompt می‌فرستد: با مترجمِ آماده ترجمه می‌شود، بی مترجم منتظر می‌ماند — در هر دو حال ۲۰۱
        with mock.patch.object(translate, "get_provider", return_value=FakeLLM(["a pear"])):
            self.assertEqual(self.post(prompt="گلابی").status_code, 201)
        self.assertEqual(self.post(prompt="هلو").status_code, 201)

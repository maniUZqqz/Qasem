"""«تلفظ»، دورِ چهارم: متنِ بی‌صدا (فقط علامت/شکلک) پیامِ فارسی می‌گیرد، ردیفِ کهنهٔ «مشکل‌دار» بسته می‌شود، شمارشِ اضافه در API."""
from unittest import mock

from rest_framework.test import APIClient

from services.audio import tts

from . import services as svc
from .models import ProblemWord
from .tests import Base


class NothingToSpeakInTheApi(Base):
    """«...» used to end in HTTP 502 and the English «Piper synthesis failed ... # channels not specified»."""

    def listen(self, text, engine="piper"):
        return self.api.post(f"{self.base}/listen/", {"text": text, "engine": engine, "variant": "after"}, format="json")

    def test_only_marks_is_a_clear_422_for_every_engine(self):
        for engine in ("piper", "edge", "moss"):
            for text in ("...", "؟؟؟", "🙂", "• •", "—"):
                r = self.listen(text, engine)
                self.assertEqual(r.status_code, 422, (engine, text, r.content))
                body = r.json()
                self.assertIn("متنی برای خواندن نیست", body["detail"] if "detail" in body else str(body))
                self.assertNotIn("channels", r.content.decode())

    def test_a_text_with_words_still_goes_to_the_engine(self):
        class Boom(tts.PiperProvider):
            def synthesize(self, text, out_path):          # noqa: ARG002
                raise tts.TTSError("engine said no")

        with mock.patch("services.audio.tts.PiperProvider", Boom):
            r = self.listen("سلام")
        self.assertEqual(r.status_code, 502, r.content)

    def test_the_voice_settings_preview_says_the_same(self):
        url = f"/api/v1/stores/{self.store.pk}/voice/preview/"
        provider = tts.PiperProvider("fa_IR-gyro-medium")
        provider.store, provider.language = self.store, "fa"
        with mock.patch("services.audio.tts.get_tts_provider", return_value=provider):
            r = self.api.post(url, {"text": "..."}, format="json")
        self.assertEqual(r.status_code, 422, r.content)
        self.assertIn("متنی برای خواندن نیست", r.content.decode())
        self.assertNotIn("channels", r.content.decode())


class ObsoleteProblemRows(Base):
    """A row the layer raised itself («gym.ir» once left «ir» to a guess) is closed once the layer no longer guesses the word."""

    def add(self, word, context, status="open"):
        return ProblemWord.objects.create(store=self.store, word=word, source="latin", context=context, status=status, engine="piper")

    def test_a_word_the_layer_now_knows_is_closed(self):
        old = self.add("ir", "سایت باشگاه gym.ir را ببین")
        svc.refresh_problems(self.store)
        old.refresh_from_db()
        self.assertEqual(old.status, "fixed")
        self.assertIn("بسته شد", old.detail)

    def test_a_word_that_is_still_a_guess_stays_open(self):
        keep = self.add("blorptix", "محصول blorptix را امتحان کن")
        svc.refresh_problems(self.store)
        keep.refresh_from_db()
        self.assertEqual(keep.status, "open")

    def test_rows_of_other_kinds_and_other_stores_are_untouched(self):
        manual = ProblemWord.objects.create(store=self.store, word="ir", source="manual", context="gym.ir", status="open")
        mine_elsewhere = ProblemWord.objects.create(store=self.store2, word="ir", source="latin", context="gym.ir", status="open")
        svc.refresh_problems(self.store)
        manual.refresh_from_db()
        mine_elsewhere.refresh_from_db()
        self.assertEqual(manual.status, "open")
        self.assertEqual(mine_elsewhere.status, "open")

    def test_a_row_without_a_sentence_is_left_alone(self):
        row = self.add("ir", "")
        svc.refresh_problems(self.store)
        row.refresh_from_db()
        self.assertEqual(row.status, "open")

    def test_the_tab_and_the_counter_do_not_show_it(self):
        self.add("ir", "سایت باشگاه gym.ir را ببین")
        self.add("blorptix", "محصول blorptix را امتحان کن")
        rows = self.api.get(f"{self.base}/problems/").json()["rows"]
        self.assertEqual([r["word"] for r in rows], ["blorptix"])
        self.assertEqual(self.api.get(f"{self.base}/").json()["counts"]["problems"], 1)
        all_rows = self.api.get(f"{self.base}/problems/?status=all").json()["rows"]
        self.assertEqual({r["word"]: r["status"] for r in all_rows}, {"ir": "fixed", "blorptix": "open"})

    def test_the_layer_does_not_record_the_address_any_more(self):
        from services.audio import pronounce
        pronounce.prepare("سایت gym.ir را ببین", "piper", store=self.store)
        self.assertFalse(ProblemWord.objects.filter(store=self.store, word="ir").exists())


class EzafeCheckEndpoint(Base):
    def test_the_table_has_every_set_before_previous_and_after(self):
        """Round 5: four sets (main, held-out and the two sets of the determiner / light-verb round) x three algorithms (round 3 first version,
        the rules as they ran until round 5, the rules of today)."""
        r = self.api.get(f"{self.base}/ezafe-check/")
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json()["rows"]
        self.assertEqual([(x["set"], x["which"]) for x in rows],
                         [(s, w) for s in ("main", "heldout", "det", "det_heldout") for w in ("before", "previous", "after")])
        for key in ("main", "heldout", "det", "det_heldout"):
            before = next(x for x in rows if x["set"] == key and x["which"] == "before")
            previous = next(x for x in rows if x["set"] == key and x["which"] == "previous")
            after = next(x for x in rows if x["set"] == key and x["which"] == "after")
            self.assertLess(after["wrong"], before["wrong"])
            self.assertLessEqual(after["wrong"], previous["wrong"])
            self.assertEqual(after["correct"] + after["missing"], after["gold"])
            self.assertEqual(after["correct"] + after["wrong"], after["said"])
        self.assertGreaterEqual(rows[0]["sentences"], 150)

    def test_login_and_ownership(self):
        self.assertEqual(APIClient().get(f"{self.base}/ezafe-check/").status_code, 401)
        stranger = APIClient()
        stranger.force_authenticate(self.other)
        self.assertIn(stranger.get(f"{self.base}/ezafe-check/").status_code, (403, 404))

    def test_it_is_computed_once_per_layer_version(self):
        svc._EZAFE_CHECK.clear()
        first = svc.ezafe_check()
        with mock.patch("services.audio.fa_pron.ezafe_gold.measure", side_effect=AssertionError("computed twice")):
            self.assertIs(svc.ezafe_check(), first)


class PreviewShowsTheConservativeEzafe(Base):
    def preview(self, text):
        r = self.api.post(f"{self.base}/preview/", {"text": text, "depth": "lexicon"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_the_brand_in_a_call_to_action_is_not_linked(self):
        d = self.preview("با چغر برنامه بساز.")
        self.assertNotIn("tʃaq1are", d["engines"]["piper"]["ipa"])
        self.assertNotIn("چَغَرِ", d["engines"]["edge"]["text"])
        self.assertFalse(any(w["ezafe"] for w in d["words"] if w["text"] == "چغر"))

    def test_a_real_phrase_still_is(self):
        d = self.preview("برنامه ورزشی بساز.")
        self.assertTrue(next(w for w in d["words"] if w["text"] == "برنامه")["ezafe"])

    def test_the_normalized_date_carries_its_ezafe_to_the_voice(self):
        d = self.preview("۲۶ آبان ۱۴۰۵")
        self.assertIn("آبانِ", d["normalized"])
        self.assertIn("ɑbɑne", d["engines"]["piper"]["ipa"], "the preview shows the phonemes without the stress marks")

"""«تلفظ»، دورِ دوم: هر نکتهٔ بازبینی یک آزمون دارد (کش، سیاستِ Edge، اعتبارسنجی، ۴۰۴، نگهداریِ فایل‌ها، نشانگرِ IPA، سرنخِ موشن، قلابِ سه‌بعدی)."""
import os
import time
from pathlib import Path
from unittest import mock

from apps.ai.models import AudioAsset, StoreAIPolicy
from apps.content.tests_audio_studio import wav_bytes
from apps.motion import sound as motion_sound
from services.audio import fa_pron, pronounce, studio, tts

from . import evalrun
from . import services as svc
from .models import EvalRun
from .tests import Base


def fake_synth(self_, text, out_path):
    out = Path(out_path).with_suffix(".wav")
    out.write_bytes(wav_bytes(1.0, 22050))
    return out


class StudioReuseFollowsTheLayer(Base):
    """«Fix the word, listen again» must play the NEW recording."""

    def speak(self, text="سلام دوستان چغر"):
        with mock.patch.object(tts.PiperProvider, "synthesize", fake_synth):
            return studio.create_speech(self.store, self.owner, text=text, voice_id="piper:fa_IR-gyro-medium", speed=1.0)

    def test_identical_request_is_reused_while_nothing_changed(self):
        a, b = self.speak(), self.speak()
        self.assertEqual(a.pk, b.pk)
        self.assertTrue(a.params.get("pron"))

    def test_a_new_store_word_makes_a_new_take(self):
        a = self.speak()
        svc.save_entry(self.store, "دوستان", "دُستان")
        b = self.speak()
        self.assertNotEqual(a.pk, b.pk, "the lexicon changed: the old take must not come back")
        self.assertEqual(b.pk, self.speak().pk, "and the new one is reused again")

    def test_editing_or_deleting_a_word_makes_a_new_take(self):
        row = svc.save_entry(self.store, "دوستان", "دُستان")
        a = self.speak()
        svc.save_entry(self.store, "دوستان", "دوستان", pk=row.pk)
        b = self.speak()
        self.assertNotEqual(a.pk, b.pk)
        row.delete()
        c = self.speak()
        self.assertNotEqual(b.pk, c.pk)

    def test_switching_the_layer_off_or_changing_depth_makes_a_new_take(self):
        a = self.speak()
        svc.save_settings(self.store, enabled=False)
        b = self.speak()
        self.assertNotEqual(a.pk, b.pk)
        svc.save_settings(self.store, enabled=True)
        self.assertEqual(self.speak().pk, a.pk, "back to the same layer state: the first take again")
        svc.save_settings(self.store, depth={"piper": "full"})
        self.assertNotEqual(self.speak().pk, a.pk)

    def test_fingerprint_is_stable_and_engine_specific(self):
        self.assertEqual(pronounce.fingerprint(self.store, "piper"), pronounce.fingerprint(self.store, "piper"))
        before = pronounce.fingerprint(self.store, "piper")
        svc.save_settings(self.store, depth={"edge": "lexicon"})
        self.assertEqual(pronounce.fingerprint(self.store, "piper"), before, "another engine's depth does not matter for piper")
        self.assertNotEqual(pronounce.fingerprint(self.store, "edge"), pronounce.fingerprint(self.store2, "edge") + "x")


class EdgeEvalFollowsThePolicy(Base):
    def test_local_only_store_cannot_start_an_edge_run(self):
        StoreAIPolicy.objects.update_or_create(store=self.store, defaults={"mode": "LOCAL_ONLY"})
        r = self.api.post(f"{self.base}/eval/", {"engine": "edge", "sample": "quick"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("فقط لوکال", r.json()["error"]["message"])
        self.assertFalse(EvalRun.objects.filter(engine="edge", baseline=False).exists())

    def test_an_allowed_store_still_can(self):
        with mock.patch.object(evalrun, "_spawn") as spawn, mock.patch("services.audio.engines.local_only", return_value=False):
            r = self.api.post(f"{self.base}/eval/", {"engine": "edge", "sample": "quick"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(spawn.called)


class SmallApiFixes(Base):
    def test_invalid_depth_is_an_error_and_keeps_the_map(self):
        svc.save_settings(self.store, depth={"piper": "full", "edge": "lexicon"})
        for bad in ({"piper": "wrong"}, {"nope": "full"}, "full", ["piper"]):
            r = self.api.patch(f"{self.base}/settings/", {"depth": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(svc.settings_for(self.store)["depth"], {"piper": "full", "edge": "lexicon"})
        ok = self.api.patch(f"{self.base}/settings/", {"depth": {"piper": "normalize"}}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["depth"], {"piper": "normalize"})
        self.assertEqual(self.api.patch(f"{self.base}/settings/", {"depth": {}}, format="json").json()["depth"], {})

    def test_listen_result_with_a_junk_token_is_404(self):
        for token in ("not-a-token", "12345", "../x"):
            r = self.api.get(f"{self.base}/listen/{token}/")
            self.assertEqual(r.status_code, 404, token)

    def test_preview_marks_words_the_voice_reads_itself(self):
        r = self.api.post(f"{self.base}/preview/", {"text": "ژنراتور برنامهٔ ورزشی", "depth": "lexicon"}, format="json").json()
        piper = r["engines"]["piper"]
        self.assertIn("‹ژنراتور›", piper["ipa"])
        self.assertGreaterEqual(piper["engine_words"], 1)

    def test_preview_shows_the_acronym_with_letter_names(self):
        r = self.api.post(f"{self.base}/preview/", {"text": "خروجی PDF"}, format="json").json()
        self.assertEqual(r["normalized"], "خروجی پی‌دی‌اف")
        self.assertEqual(r["engines"]["piper"]["depth"], "lexicon")            # the default depth: letter by letter
        self.assertIn("pˈiː dˈiː ˈɛf", r["engines"]["piper"]["ipa"])
        self.assertNotIn("pej", r["engines"]["piper"]["ipa"])
        self.assertEqual(r["engines"]["piper"]["letter_words"], 1)
        plain = self.api.post(f"{self.base}/preview/", {"text": "خروجی PDF", "depth": "normalize"}, format="json").json()
        self.assertEqual(plain["engines"]["piper"]["depth"], "normalize")      # and at the lighter depth too
        self.assertIn("pˈiː dˈiː ˈɛf", plain["engines"]["piper"]["ipa"])

    def test_preview_spelled_ezafe(self):
        r = self.api.post(f"{self.base}/preview/", {"text": "وعده‌ی غذایی سالم", "depth": "lexicon"}, format="json").json()
        self.assertIn("eje", r["engines"]["piper"]["ipa"])
        self.assertTrue(any(w["text"] == "وعده" and w["ezafe"] for w in r["words"]))

    def test_the_brand_comes_back_with_ghayn(self):
        row = svc.save_entry(self.store, "چغر", "چَغَر")
        self.assertEqual(svc.entry_dict(row)["heard_as"], "چَغَر")
        r = self.api.post(f"{self.base}/convert/", {"respelling": "چِغِر"}, format="json").json()
        self.assertEqual(r["respelling"], "چِغِر")

    def test_overview_says_which_voices_the_site_has(self):
        ov = self.api.get(f"{self.base}/").json()
        self.assertIn("site_voices", ov)
        self.assertEqual(ov["layer_version"], fa_pron.VERSION)
        self.assertIn("quick", ov["counts"])

    def test_the_overview_prefers_a_voice_the_site_has(self):
        svc.seed_baseline()
        sha = EvalRun.objects.filter(baseline=True).first().summary["baseline_sha"]
        EvalRun.objects.filter(baseline=True, engine="piper").update(voice="fa_IR-amir-medium", depth="lexicon")
        mine = EvalRun.objects.create(store=None, engine="piper", voice="fa_IR-gyro-medium", sample="full", depth="normalize",
                                      state=EvalRun.State.DONE, baseline=True,
                                      summary={"overall": {"n": 1, "before": 0.2, "after": 0.1}, "baseline_sha": sha})
        with mock.patch.object(svc, "site_piper_voices", return_value=["fa_IR-gyro-medium"]):
            ov = self.api.get(f"{self.base}/").json()
        self.assertEqual(ov["latest"]["piper"]["id"], mine.pk)


class Retention(Base):
    def folder(self):
        d = Path(self.media) / "pronunciation" / str(self.store.pk)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def touch(self, name, age_h):
        p = self.folder() / name
        p.write_bytes(b"RIFF")
        t = time.time() - age_h * 3600
        os.utime(p, (t, t))
        return p

    def test_old_test_box_files_are_removed(self):
        old = self.touch("aaaaaaaaaaaa.wav", 30)
        new = self.touch("bbbbbbbbbbbb.wav", 1)
        other = self.folder() / "notes.txt"
        other.write_text("x")
        self.assertEqual(svc.cleanup_store_audio(self.store.pk), 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue(other.exists(), "only the recordings are touched")

    def test_never_more_than_the_cap_per_store(self):
        files = [self.touch(f"{i:012x}.wav", 0.1 * (i + 1)) for i in range(8)]
        self.assertEqual(svc.cleanup_store_audio(self.store.pk, keep=5), 3)
        self.assertEqual(sum(f.exists() for f in files), 5)
        self.assertTrue(files[0].exists() and not files[7].exists(), "the newest are kept")

    def test_listening_cleans_up_after_itself(self):
        old = self.touch("cccccccccccc.wav", 48)
        self.use_lexicon()
        with mock.patch.object(tts.PiperProvider, "synthesize", fake_synth), \
                mock.patch.object(svc, "site_piper_voice", return_value="fa_IR-gyro-medium"):
            r = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "piper", "variant": "after"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(old.exists())

    def test_deleting_a_run_removes_its_files(self):
        run = EvalRun.objects.create(store=self.store, engine="edge", sample="quick", state=EvalRun.State.FAILED)
        d = Path(self.media) / "pronunciation" / "runs" / str(run.pk)
        d.mkdir(parents=True)
        (d / "0_before.mp3").write_bytes(b"x")
        self.assertEqual(self.api.delete(f"{self.base}/eval/{run.pk}/").status_code, 204)
        self.assertFalse(EvalRun.objects.filter(pk=run.pk).exists())
        self.assertFalse(d.exists())

    def test_housekeeping_removes_orphan_and_finished_run_folders(self):
        root = Path(self.media) / "pronunciation" / "runs"
        orphan = root / "98765"
        orphan.mkdir(parents=True)
        (orphan / "a.mp3").write_bytes(b"x")
        run = EvalRun.objects.create(store=None, engine="edge", sample="full", state=EvalRun.State.FAILED)
        failed = root / str(run.pk)
        failed.mkdir()
        t = time.time() - 7200
        os.utime(failed, (t, t))
        live = EvalRun.objects.create(store=None, engine="edge", sample="full", state=EvalRun.State.RUNNING)
        running = root / str(live.pk)
        running.mkdir()
        out = svc.cleanup_media()
        self.assertEqual(out["runs"], 2)
        self.assertFalse(orphan.exists() or failed.exists())
        self.assertTrue(running.exists(), "a run that is still going keeps its files")

    def test_the_periodic_task_cleans_hourly(self):
        from . import tasks

        with mock.patch.object(svc, "cleanup_media", return_value={"audio": 0, "runs": 0}) as m:
            tasks._LAST_CLEAN[0] = 0.0
            self.assertIn("cleanup", tasks.step())
            first = m.call_count
            tasks.step()
            self.assertEqual(m.call_count, first, "not again within the hour")


class MotionCuesAndUp3d(Base):
    def test_cues_are_regrouped_onto_the_written_words(self):
        written = "قیمت ۲۵۰ تومان است"
        spoken = "قیمت دویست و پنجاه تومان است"
        cues = [{"w": w, "s": float(i), "e": i + 0.8} for i, w in enumerate(spoken.split())]
        out = motion_sound.regroup_cues(cues, written, spoken, store=self.store)
        self.assertEqual([c["w"] for c in out], ["قیمت", "۲۵۰", "تومان", "است"])
        self.assertEqual((out[1]["s"], out[1]["e"]), (1.0, 3.8), "the number spans the three words it was spoken as")
        self.assertEqual(out[0]["s"], 0.0)
        self.assertEqual(out[-1]["e"], 5.8)

    def test_cues_with_fewer_cues_than_words_still_give_every_word_a_time(self):
        written = "یک دو سه چهار"
        cues = [{"w": "الف", "s": 0.0, "e": 1.0}, {"w": "ب", "s": 1.0, "e": 2.0}]
        out = motion_sound.regroup_cues(cues, written, "x", store=self.store)
        self.assertEqual(len(out), 4)
        self.assertTrue(all(c["e"] >= c["s"] for c in out))

    def test_edge_cues_use_the_spoken_text(self):
        seen = {}

        async def fake_stream():
            yield {"type": "audio", "data": b"abc"}
            for i, w in enumerate("قیمت دویست و پنجاه تومان".split()):
                yield {"type": "WordBoundary", "text": w, "offset": i * 10_000_000, "duration": 8_000_000}

        class FakeComm:
            def __init__(self, text, voice, **kw):
                seen["text"] = text

            def stream(self):
                return fake_stream()

        class FakeEdge:
            Communicate = FakeComm

        out = Path(self.media) / "x.mp3"
        with mock.patch.dict("sys.modules", {"edge_tts": FakeEdge}):
            got = motion_sound._edge_with_cues("fa-IR-FaridNeural", "قیمت ۲۵۰ تومان", out, store=self.store)
        self.assertEqual(seen["text"], "قیمت دویست و پنجاه تومان", "numbers are spoken as words")
        self.assertEqual([c["w"] for c in got["cues"]], ["قیمت", "۲۵۰", "تومان"], "captions still match the written words")

    def test_the_3d_engine_speaks_through_the_layer(self):
        from up3d import tts as up3d_tts

        self.assertIsNotNone(up3d_tts.TEXT_FILTER)
        self.assertIn("دویست", up3d_tts.TEXT_FILTER("قیمت ۲۵۰ تومان", "openai", {}))
        self.assertEqual(up3d_tts.TEXT_FILTER("Hello 250", "openai", {}), "Hello 250", "English is untouched")


class PiperDefaultAndNormalizeDepth(Base):
    """Piper's default depth is «lexicon» (the owner's ع/ه/و/اضافه words are what the layer is for; the small Vosk cannot rank it against the
    normaliser: it does not hear a reduced «و»), «normalize» is one setting away. Both must work: the OWNER's words and the spelled-out
    acronyms go in as phonemes at either depth, plain text goes in as text only at «normalize»."""

    def provider(self, voice):
        p = tts.PiperProvider("fa_IR-gyro-medium")
        p.store, p.language, p.use_pron = self.store, "fa", True
        patcher = mock.patch.object(tts.PiperProvider, "_load", lambda self_: voice)
        patcher.start()
        self.addCleanup(patcher.stop)
        return p

    def use_normalize(self):
        svc.save_settings(self.store, depth={"piper": "normalize"})

    def test_the_default_depths(self):
        self.assertEqual(svc.effective_default("piper"), "lexicon")
        self.assertEqual(svc.effective_default("edge"), "normalize")
        self.assertEqual(svc.effective_default("moss"), "normalize")
        self.assertEqual(svc.settings_for(self.store)["depth"], {})

    def test_the_default_says_the_words_the_voice_gets_wrong(self):
        from .tests import FakeVoice
        v = FakeVoice()
        self.provider(v).synthesize("هزار و چهار", self.media / "d.wav")
        self.assertEqual(v.synth_calls, [], "phoneme input")
        heard = "".join("".join(c) for c in v.id_calls)
        self.assertIn("hazɑr", heard)               # espeak says hezɑr
        self.assertIn("o", heard)                   # the reduced «و», not espeak's stressed «va»
        self.assertNotIn("va", heard)

    def test_plain_text_goes_to_the_voice_as_text_at_the_normalize_depth(self):
        from .tests import FakeVoice
        self.use_normalize()
        v = FakeVoice()
        self.provider(v).synthesize("برنامهٔ ورزشی ۳ جلسه", self.media / "a.wav")
        self.assertEqual(v.id_calls, [])
        self.assertEqual(len(v.synth_calls), 1)
        self.assertIn("سه جلسه", v.synth_calls[0])          # the normaliser still ran
        self.assertIn("برنامهٔ", v.synth_calls[0])           # the writer's ezafe mark is left for the voice

    def test_the_owners_word_is_honoured_at_every_depth(self):
        from .tests import FakeVoice
        svc.save_entry(self.store, "چغر", "چُغُر")
        for depth in (None, "normalize"):
            if depth:
                self.use_normalize()
            v = FakeVoice()
            self.provider(v).synthesize("سلام چغر", self.media / f"b{depth}.wav")
            self.assertEqual(v.synth_calls, [])                  # phoneme input: the owner's word could not go in as text
            heard = "".join("".join(c) for c in v.id_calls)
            self.assertIn("tʃoq1", heard)
            self.assertIn("or", heard)

    def test_the_owners_word_reaches_the_text_engines_at_the_default_depth(self):
        svc.save_entry(self.store, "چغر", "چُغُر")
        self.assertIn("چُغُر", pronounce.text_for("سلام چغر", "moss", store=self.store))
        self.assertIn("چُغُر", pronounce.text_for("سلام چغر", "edge", store=self.store))

    def test_a_spelled_out_acronym_goes_in_as_letters_at_every_depth(self):
        from .tests import FakeVoice
        for depth in (None, "normalize"):
            if depth:
                self.use_normalize()
            v = FakeVoice()
            self.provider(v).synthesize("خروجی PDF", self.media / f"c{depth}.wav")
            self.assertEqual(v.synth_calls, [])
            flat = "".join("".join(c) for c in v.id_calls)
            self.assertIn("pˈiː dˈiː ˈɛf", flat)
            self.assertNotIn("pˈej", flat)

    def test_the_test_box_can_try_another_depth(self):
        base = self.api.post(f"{self.base}/preview/", {"text": "برنامه‌ی تمرینی چغر"}, format="json").json()
        self.assertEqual(base["engines"]["piper"]["depth"], "lexicon")
        self.assertIn("barnɑm", base["engines"]["piper"]["ipa"])
        plain = self.api.post(f"{self.base}/preview/", {"text": "برنامه‌ی تمرینی چغر", "depth": "normalize"}, format="json").json()
        self.assertEqual(plain["engines"]["piper"]["depth"], "normalize")
        self.assertNotIn("ipa", plain["engines"]["piper"])
        self.assertEqual(svc.settings_for(self.store)["depth"], {})        # the store's own setting is untouched
        bad = self.api.post(f"{self.base}/preview/", {"text": "سلام", "depth": "nope"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_the_test_box_listen_depth_reaches_the_provider(self):
        seen = {}

        def fake(self_, text, out_path):
            seen["depth"] = self_.depth_override
            out = Path(out_path).with_suffix(".wav")
            out.write_bytes(__import__("apps.content.tests_audio_studio", fromlist=["wav_bytes"]).wav_bytes(1.0, 22050))
            return out

        with mock.patch.object(tts.PiperProvider, "synthesize", fake):
            r = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "piper", "variant": "after", "depth": "lexicon"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(seen["depth"], "lexicon")
        bad = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "piper", "variant": "after", "depth": "x"}, format="json")
        self.assertEqual(bad.status_code, 400)


class BaselineFollowsTheShippedFile(Base):
    """A new version of the shipped measurement replaces the rows of the old one; the owner's own runs stay."""

    def write(self, name, before, after, voice="fa_IR-gyro-medium", depth="normalize"):
        import json
        data = {"runs": [{"engine": "piper", "voice": voice, "sample": "full", "depth": depth, "n": 272, "asr": "vosk",
                          "summary": {"overall": {"n": 272, "before": before, "after": after}}, "rows": []}]}
        f = self.media / name
        f.write_text(json.dumps(data), encoding="utf-8")
        return f

    def test_a_new_file_replaces_the_old_rows_once(self):
        a, b = self.write("a.json", 0.3, 0.2), self.write("b.json", 0.3, 0.1)
        mine = EvalRun.objects.create(store=self.store, engine="piper", voice="x", sample="quick", state=EvalRun.State.DONE)
        with mock.patch.object(svc, "BASELINE_FILE", a):
            self.assertEqual(svc.seed_baseline(), 1)
            self.assertEqual(svc.seed_baseline(), 0)
        with mock.patch.object(svc, "BASELINE_FILE", b):
            self.assertEqual(svc.seed_baseline(), 1)
            self.assertEqual(svc.seed_baseline(), 0)
        rows = EvalRun.objects.filter(baseline=True)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows[0].summary["overall"]["after"], 0.1)
        self.assertTrue(EvalRun.objects.filter(pk=mine.pk).exists(), "an owner's own run is never touched")

    def test_rows_seeded_by_the_first_round_have_no_fingerprint_and_are_replaced(self):
        EvalRun.objects.create(store=None, engine="piper", voice="fa_IR-amir-medium", sample="full", depth="lexicon",
                               state=EvalRun.State.DONE, baseline=True, summary={"overall": {"n": 230, "before": 0.27, "after": 0.2}})
        with mock.patch.object(svc, "BASELINE_FILE", self.write("c.json", 0.12, 0.08)):
            self.assertEqual(svc.seed_baseline(), 1)
        self.assertEqual(list(EvalRun.objects.filter(baseline=True).values_list("voice", flat=True)), ["fa_IR-gyro-medium"])

"""«تلفظ»: واژه‌نامهٔ فروشگاه، API، لایه روی هر موتور، سنجش (با کارهای ساختگیِ گره) و آزمونِ خودکارِ گره — بدونِ گره، بدونِ شبکه، بدونِ صدای واقعی."""
import json
import shutil
import sys
import tempfile
import types
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.compute import services as compute
from apps.compute.models import ComputeJob
from apps.stores.models import Store
from services.audio import fa_pron, node_audio, pronounce, tts
from services.audio.fa_pron import eval_set

from . import evalrun
from . import services as svc
from .models import EvalRun, LexiconEntry, ProblemWord, PronSettings

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmpron-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmpron-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("pron-owner", password="x")
        self.other = User.objects.create_user("pron-other", password="x")
        self.staff = User.objects.create_user("pron-staff", password="x", is_staff=True)
        self.store = Store.objects.create(owner=self.owner, name="چغر")
        self.store2 = Store.objects.create(owner=self.other, name="دیگری")
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/pronunciation"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def use_lexicon(self, *engines):
        """Respelled text for the text engines (their built-in depth is «normalize»)."""
        svc.save_settings(self.store, depth={e: "lexicon" for e in engines})


# ───────────────────────────────────────────────────────────── services

class LexiconServices(Base):
    def test_convert_respelling(self):
        out = svc.convert("چَغَر")
        self.assertEqual(out["pn"], "Caqar")
        self.assertEqual(out["respelling"], "چَقَر")
        self.assertEqual(out["syllables"], 2)
        self.assertEqual(svc.convert("Caqar")["pn"], "Caqar")

    def test_convert_errors_are_persian(self):
        for bad in ("", "   ", "x" * 200):
            with self.assertRaises(svc.PronError):
                svc.convert(bad)
        with self.assertRaises(svc.PronError):
            svc.convert("ca?ar")

    def test_save_entry_and_runtime(self):
        row = svc.save_entry(self.store, "چغر", "چِغِر", user=self.owner)
        self.assertEqual(row.pn, "Ceqer")
        dic = svc.dictionary_for(self.store)
        self.assertEqual(dic.lookup("چغر").pn, "Ceqer")
        self.assertEqual(dic.lookup("چغر").source, "store")
        # another store keeps the shared reading
        self.assertEqual(svc.dictionary_for(self.store2).lookup("چغر").pn, "Caqar")

    def test_cache_follows_edits(self):
        svc.save_entry(self.store, "چغر", "چِغِر")
        self.assertEqual(svc.dictionary_for(self.store).lookup("چغر").pn, "Ceqer")
        svc.save_entry(self.store, "چغر", "چُغُر")
        self.assertEqual(svc.dictionary_for(self.store).lookup("چغر").pn, "Coqor")
        LexiconEntry.objects.filter(store=self.store).update(enabled=False)
        LexiconEntry.objects.filter(store=self.store).first().save()          # touches updated_at
        self.assertEqual(svc.dictionary_for(self.store).lookup("چغر").pn, "Caqar")

    def test_global_entry_applies_to_every_store_and_store_wins(self):
        svc.save_entry(None, "کشتی", "کوشتی")
        self.assertEqual(svc.dictionary_for(self.store2).lookup("کشتی").pn, "kuSti")
        svc.save_entry(self.store2, "کشتی", "کِشتی")
        self.assertEqual(svc.dictionary_for(self.store2).lookup("کشتی").pn, "keSti")

    def test_word_is_canonical(self):
        row = svc.save_entry(self.store, "كتاب", "کِتاب")
        self.assertEqual(row.word, "کتاب")

    def test_saving_resolves_the_problem(self):
        svc.record_problems(self.store, ["چغر"], source="manual")
        svc.save_entry(self.store, "چغر", "چَغَر")
        self.assertEqual(ProblemWord.objects.get(store=self.store, word="چغر").status, "fixed")

    def test_record_problems_counts_and_skips_known(self):
        svc.record_problems(self.store, ["Zork", "Zork", "Blip"], source="latin")
        self.assertEqual(ProblemWord.objects.get(store=self.store, word="zork").count, 2)
        svc.save_entry(self.store, "blip", "بلیپ")
        svc.record_problems(self.store, ["Blip"], source="latin")
        self.assertFalse(ProblemWord.objects.filter(store=self.store, word="blip").exists() and
                         ProblemWord.objects.get(store=self.store, word="blip").status == "open")

    def test_settings_roundtrip(self):
        self.assertEqual(svc.settings_for(self.store), {"enabled": True, "ezafe": True, "depth": {}})
        out = svc.save_settings(self.store, enabled=False, ezafe=False, depth={"piper": "full", "bogus": "full", "edge": "nope"})
        self.assertEqual(out, {"enabled": False, "ezafe": False, "depth": {"piper": "full"}})

    def test_preview_explains_each_engine(self):
        self.use_lexicon("moss")
        out = svc.preview(self.store, "معنی ۲۵۰,۰۰۰ تومان")
        self.assertIn("دویست و پنجاه هزار", out["normalized"])
        self.assertIn("ipa", out["engines"]["piper"])
        self.assertIn("مَعنی", out["engines"]["moss"]["text"])
        self.assertEqual(out["words"][0]["pn"], "ma'ni")
        with self.assertRaises(svc.PronError):
            svc.preview(self.store, "  ")
        with self.assertRaises(svc.PronError):
            svc.preview(self.store, "الف" * 2000)

    def test_shared_rows_search_and_category(self):
        out = svc.shared_rows("معنی")
        self.assertTrue(any(r["word"] == "معنی" for r in out["rows"]))
        cat = out["categories"][0]["name"]
        self.assertTrue(all(r["category"] == cat for r in svc.shared_rows("", cat, 50)["rows"]))


# ───────────────────────────────────────────────────────────── API

class Api(Base):
    def test_overview(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual([e["key"] for e in b["engines"]], ["piper", "edge", "moss"])
        self.assertTrue(b["settings"]["enabled"])
        self.assertGreaterEqual(b["counts"]["shared"], 900)
        self.assertGreaterEqual(b["counts"]["sentences"], 200)
        self.assertIn("ayn", b["tags"])
        self.assertIn("node", b)

    def test_access_is_per_store(self):
        self.assertEqual(self.api.get(f"/api/v1/stores/{self.store2.pk}/pronunciation/").status_code, 404)
        self.assertEqual(APIClient().get(f"{self.base}/").status_code, 401)

    def test_settings_patch(self):
        r = self.api.patch(f"{self.base}/settings/", {"enabled": False, "depth": {"piper": "full"}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])
        self.assertEqual(r.json()["depth"], {"piper": "full"})
        self.assertFalse(PronSettings.objects.get(store=self.store).enabled)

    def test_preview_and_convert(self):
        r = self.api.post(f"{self.base}/preview/", {"text": "معنی عالی است"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("engines", r.json())
        self.assertEqual(self.api.post(f"{self.base}/preview/", {"text": ""}, format="json").status_code, 400)
        r = self.api.post(f"{self.base}/convert/", {"respelling": "مَعنی"}, format="json")
        self.assertEqual(r.json()["pn"], "ma'ni")
        r = self.api.post(f"{self.base}/convert/", {"respelling": "ca?"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("message", r.json()["error"])

    def test_lexicon_crud_and_isolation(self):
        r = self.api.post(f"{self.base}/lexicon/", {"word": "چغر", "respelling": "چِغِر", "note": "برند"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()["id"]
        self.assertEqual(r.json()["heard_as"], "چِقِر")
        rows = self.api.get(f"{self.base}/lexicon/").json()["rows"]
        self.assertEqual([x["word"] for x in rows], ["چغر"])
        r = self.api.patch(f"{self.base}/lexicon/{pk}/", {"respelling": "چُغُر"}, format="json")
        self.assertEqual(r.json()["pn"], "Coqor")
        r = self.api.patch(f"{self.base}/lexicon/{pk}/", {"enabled": False}, format="json")
        self.assertFalse(r.json()["enabled"])
        # the other owner sees nothing of it
        other = APIClient()
        other.force_authenticate(self.other)
        self.assertEqual(other.get(f"/api/v1/stores/{self.store2.pk}/pronunciation/lexicon/").json()["rows"], [])
        self.assertEqual(other.delete(f"/api/v1/stores/{self.store2.pk}/pronunciation/lexicon/{pk}/").status_code, 404)
        self.assertEqual(self.api.delete(f"{self.base}/lexicon/{pk}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/lexicon/").json()["rows"], [])

    def test_lexicon_errors(self):
        r = self.api.post(f"{self.base}/lexicon/", {"word": "", "respelling": "ا"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"{self.base}/lexicon/", {"word": "x", "respelling": "ca?"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_global_scope_is_staff_only(self):
        r = self.api.post(f"{self.base}/lexicon/", {"word": "گل", "respelling": "گُل", "scope": "global"}, format="json")
        self.assertEqual(r.status_code, 403)
        staff = APIClient()
        staff.force_authenticate(self.staff)
        Store.objects.filter(pk=self.store.pk).update(owner=self.staff)
        r = staff.post(f"{self.base}/lexicon/", {"word": "گل", "respelling": "گُل", "scope": "global"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["scope"], "global")
        self.assertTrue(LexiconEntry.objects.filter(store__isnull=True, word="گل").exists())

    def test_shared_list(self):
        r = self.api.get(f"{self.base}/shared/", {"q": "عضله"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(x["word"] == "عضله" for x in r.json()["rows"]))

    def test_problems_flow(self):
        r = self.api.post(f"{self.base}/problems/", {"word": "زورک", "context": "جمله"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()["id"]
        self.assertEqual(len(self.api.get(f"{self.base}/problems/").json()["rows"]), 1)
        r = self.api.patch(f"{self.base}/problems/{pk}/", {"respelling": "زُرَک"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["entry"]["pn"], "zorak")
        self.assertEqual(self.api.get(f"{self.base}/problems/").json()["rows"], [])
        self.assertEqual(len(self.api.get(f"{self.base}/problems/", {"status": "all"}).json()["rows"]), 1)
        self.assertEqual(self.api.delete(f"{self.base}/problems/{pk}/").status_code, 204)

    def test_problem_ignore(self):
        pk = self.api.post(f"{self.base}/problems/", {"word": "زورک"}, format="json").json()["id"]
        r = self.api.patch(f"{self.base}/problems/{pk}/", {"status": "ignored"}, format="json")
        self.assertEqual(r.json()["problem"]["status"], "ignored")

    def test_listen_piper_before_and_after(self):
        calls = []

        def fake(self_, text, out_path):
            calls.append((self_.use_pron, self_.store.pk))
            p = Path(out_path).with_suffix(".wav")
            p.write_bytes(b"RIFF0000WAVE")
            return p

        with mock.patch.object(tts.PiperProvider, "synthesize", fake):
            a = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "piper", "variant": "before"}, format="json")
            b = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "piper", "variant": "after"}, format="json")
        self.assertEqual(a.status_code, 200, a.content)
        self.assertEqual(calls, [(False, self.store.pk), (True, self.store.pk)])
        url = b.json()["url"]
        self.assertTrue(url.startswith(f"/stores/{self.store.pk}/pronunciation/audio/"))
        got = self.api.get("/api/v1" + url)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(self.api.get(f"{self.base}/audio/../../etc.wav").status_code, 404)
        self.assertEqual(self.api.get(f"{self.base}/audio/nothing.wav").status_code, 404)

    def test_listen_edge_refused_for_local_only_store(self):
        with mock.patch("services.audio.engines.local_only", return_value=True):
            r = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "edge", "variant": "after"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "policy")

    def test_listen_validation(self):
        self.assertEqual(self.api.post(f"{self.base}/listen/", {"text": "", "engine": "piper"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "bogus"}, format="json").status_code, 400)

    def test_listen_moss_goes_to_the_queue(self):
        self.use_lexicon("moss")
        job = types.SimpleNamespace(uid="11111111-1111-1111-1111-111111111111")
        with mock.patch.object(node_audio, "enqueue", return_value=job) as enq:
            r = self.api.post(f"{self.base}/listen/", {"text": "معنی", "engine": "moss", "variant": "after"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["state"], "queued")
        payload = enq.call_args.args[2]
        self.assertIn("مَعنی", payload["text"])               # the layer's text, not the plain one
        self.assertTrue(enq.call_args.kwargs["durable"])

    def test_eval_list_seeds_the_shipped_baseline(self):
        r = self.api.get(f"{self.base}/eval/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("runs", r.json())

    def test_full_eval_is_staff_only(self):
        r = self.api.post(f"{self.base}/eval/", {"engine": "piper", "sample": "full"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_eval_start_validates_engine(self):
        r = self.api.post(f"{self.base}/eval/", {"engine": "bogus"}, format="json")
        self.assertEqual(r.status_code, 400)


# ───────────────────────────────────────────────────────────── the layer in front of each engine

class FakeVoice:
    """Stands in for piper.PiperVoice: records what it was given."""

    def __init__(self, fail_ids=False):
        self.config = types.SimpleNamespace(sample_rate=22050, phoneme_id_map={}, length_scale=1.0)
        self.synth_calls, self.id_calls, self.fail_ids = [], [], fail_ids

    def phonemize(self, word):
        return [list("n" + "a" * 2)]

    def phonemes_to_ids(self, phonemes):
        if self.fail_ids:
            raise RuntimeError("boom")
        self.id_calls.append(list(phonemes))
        return [1] + [3] * len(phonemes)

    def phoneme_ids_to_audio(self, ids, cfg=None, include_alignments=False):
        import numpy as np

        return np.ones(2205, dtype="float32") * 0.5

    def synthesize(self, text, syn_config=None):
        self.synth_calls.append(text)
        chunk = types.SimpleNamespace(sample_rate=22050, sample_width=2, sample_channels=1, audio_int16_bytes=b"\x01\x00" * 2205)
        return [chunk]


class ProviderHooks(Base):
    def piper(self, voice, use=True):
        p = tts.PiperProvider("fa_IR-amir-medium")
        p.store, p.language, p.use_pron = self.store, "fa", use
        patcher = mock.patch.object(tts.PiperProvider, "_load", lambda self_: voice)
        patcher.start()
        self.addCleanup(patcher.stop)
        return p

    def test_piper_uses_phoneme_input(self):
        v = FakeVoice()
        out = self.piper(v).synthesize("معنی ورزش.", self.media / "a.wav")
        self.assertTrue(Path(out).exists())
        self.assertEqual(v.synth_calls, [])
        flat = "".join("".join(c) for c in v.id_calls)
        self.assertIn("ʔ", flat)                       # the glottal stop of «معنی» went in as a phoneme
        self.assertTrue(any(isinstance(x, str) and len(x) == 1 for x in v.id_calls[0]))

    def test_piper_plain_when_layer_is_off(self):
        v = FakeVoice()
        self.piper(v, use=False).synthesize("معنی", self.media / "b.wav")
        self.assertEqual(v.synth_calls, ["معنی"])
        self.assertEqual(v.id_calls, [])

    def test_piper_falls_back_to_plain_text_when_phonemes_fail(self):
        v = FakeVoice(fail_ids=True)
        out = self.piper(v).synthesize("معنی", self.media / "c.wav")
        self.assertTrue(Path(out).exists())
        self.assertEqual(v.synth_calls, ["معنی"])

    def test_store_switch_turns_the_layer_off(self):
        svc.save_settings(self.store, enabled=False)
        v = FakeVoice()
        self.piper(v).synthesize("معنی", self.media / "d.wav")
        self.assertEqual(v.synth_calls, ["معنی"])

    def test_store_lexicon_reaches_piper(self):
        svc.save_entry(self.store, "چغر", "چُغُر")
        v = FakeVoice()
        self.piper(v).synthesize("چغر", self.media / "e.wav")
        self.assertIn("tʃoq1ˈor", "".join("".join(c) for c in v.id_calls))

    def test_english_is_never_touched(self):
        p = tts.PiperProvider("fa_IR-amir-medium")
        p.language = "en"
        self.assertIsNone(p._pron("hello world", "piper"))
        self.assertIsNone(pronounce.prepare("hello", "piper", store=self.store, language="en"))

    def test_layer_errors_never_stop_a_narration(self):
        with mock.patch.object(fa_pron, "prepare", side_effect=RuntimeError("bug")):
            self.assertIsNone(pronounce.prepare("معنی", "piper", store=self.store))
            self.assertEqual(pronounce.text_for("معنی", "moss", store=self.store), "معنی")

    def test_edge_gets_normalised_text_by_default_and_respelled_text_on_request(self):
        seen = {}

        class FakeComm:
            def __init__(self, text, voice, **kw):
                seen["text"], seen["voice"] = text, voice

            async def save(self, path):
                Path(path).write_bytes(b"ID3")

        fake = types.ModuleType("edge_tts")
        fake.Communicate = FakeComm
        with mock.patch.dict(sys.modules, {"edge_tts": fake}):
            p = tts.EdgeTTSProvider(voice="fa-IR-DilaraNeural")
            p.store = self.store
            p.synthesize("معنی ورزش ۲۵۰,۰۰۰ تومان", self.media / "e.mp3")
            self.assertEqual(seen["text"], "معنی ورزش دویست و پنجاه هزار تومان")       # measured best for Edge: text only
            self.use_lexicon("edge")
            p.synthesize("معنی ورزش ۲۵۰,۰۰۰ تومان", self.media / "e2.mp3")
        self.assertIn("مَعنی", seen["text"])
        self.assertIn("دویست و پنجاه هزار", seen["text"])
        self.assertNotIn("<", seen["text"])            # the free endpoint takes plain text only (measured)

    def test_moss_provider_sends_the_layer_text(self):
        sent = {}

        def fake_run(key, kind, payload, **kw):
            sent.update(payload)
            p = self.media / "m.wav"
            p.write_bytes(b"RIFF")
            return p

        self.use_lexicon("moss")
        with mock.patch.object(node_audio, "run_and_wait", fake_run):
            prov = node_audio.NodeMossProvider("arash")
            prov.store = self.store
            prov.synthesize("معنی عالی است", self.media / "out.wav")
        self.assertIn("مَعنی", sent["text"])

    def _fake_requests(self, posted):
        class Resp:
            status_code = 200
            content = b"ID3"
            text = ""

        def post(url, data=None, json=None, headers=None, timeout=None, **kw):
            posted.update({"url": url, "data": data, "json": json})
            return Resp()

        fake = types.ModuleType("requests")
        fake.post = post
        return fake

    def test_azure_gets_sub_tags_in_its_ssml(self):
        self.use_lexicon("edge")                  # Azure shares Edge's setting; SSML <sub> is what a lexicon depth gives it
        posted = {}
        engine = types.SimpleNamespace(base_url="westeurope", api_key="k", timeout_s=5)
        with mock.patch.dict(sys.modules, {"requests": self._fake_requests(posted)}):
            p = tts.AzureTTSProvider(engine, "fa-IR-FaridNeural")
            p.store = self.store
            p.synthesize("معنی.", self.media / "az.mp3")
        ssml = posted["data"].decode("utf-8")
        self.assertIn('<sub alias="مَعنی">معنی</sub>', ssml)
        self.assertIn("<break", ssml)
        self.assertTrue(ssml.startswith("<speak"))

    def test_openai_like_engines_only_get_the_normaliser(self):
        posted = {}
        engine = types.SimpleNamespace(base_url="https://x.test", api_key="k", timeout_s=5, model_name="m", options={})
        with mock.patch.dict(sys.modules, {"requests": self._fake_requests(posted)}):
            p = tts.OpenAITTSProvider(engine, "onyx")
            p.store = self.store
            p.synthesize("معنی ۲۵۰,۰۰۰ تومان", self.media / "oa.mp3")
        text = posted["json"]["input"]
        self.assertIn("دویست و پنجاه هزار", text)
        self.assertNotIn("َ", text)              # no short-vowel marks for a multilingual model

    def test_every_cloned_voice_job_goes_through_the_layer(self):
        from services.audio import voice_clone as vc

        self.use_lexicon("moss")
        voice = types.SimpleNamespace(engine="moss-fa", store=self.store)
        with mock.patch.object(vc, "_enqueue_moss_tts", side_effect=lambda v, text, **kw: text):
            out = vc.enqueue_tts(voice, "معنی عالی")
        self.assertIn("مَعنی", out)

    def test_chain_builds_providers_with_store_and_language(self):
        engines_mod = mock.Mock()
        eng = types.SimpleNamespace(kind="PIPER", name="p", options={}, model_name="fa_IR-gyro-medium", row_id=1,
                                    voice=lambda lang, g: "fa_IR-gyro-medium", has_voice=lambda lang, g: True)
        res = types.SimpleNamespace(engines=[eng], explain=lambda: "")
        with mock.patch.object(tts.engine_registry, "resolve", return_value=res), \
                mock.patch.object(tts.engine_registry, "local_only", return_value=False):
            prov = tts.get_tts_provider("fa", self.store)
        self.assertEqual((prov.store, prov.language), (self.store, "fa"))
        _ = engines_mod


class MotionCues(Base):
    def test_cue_text_keeps_its_word_count(self):
        from apps.motion import sound

        captured = {}

        class Comm:
            def __init__(self, text, voice, **kw):
                captured["text"] = text

            async def stream(self):
                yield {"type": "audio", "data": b"x"}
                yield {"type": "WordBoundary", "text": "a", "offset": 0, "duration": 1000000}
                yield {"type": "WordBoundary", "text": "b", "offset": 1000000, "duration": 1000000}

        fake = types.ModuleType("edge_tts")
        fake.Communicate = Comm
        self.use_lexicon("edge")
        with mock.patch.dict(sys.modules, {"edge_tts": fake}):
            sound._edge_with_cues("fa-IR-DilaraNeural", "معنی ورزش", self.media / "c.mp3", store=self.store)
            self.assertEqual(len(captured["text"].split()), 2)
            self.assertIn("مَعنی", captured["text"])
            # a price spelled out would change the word count: such a text is read as written
            sound._edge_with_cues("fa-IR-DilaraNeural", "قیمت ۲۵۰۰۰۰ تومان", self.media / "c2.mp3", store=self.store)
            self.assertEqual(captured["text"], "قیمت ۲۵۰۰۰۰ تومان")


# ───────────────────────────────────────────────────────────── the audio check against fake node jobs

def fake_result(engine, items, wrong_before=True):
    """What pron_jobs.py would write: «before» hears a word wrong, «after» hears everything."""
    rows = []
    for it in items:
        idx = it["id"]
        ref = eval_set.SENTENCES[idx][1]
        hyp = ref
        if it["variant"] == "before" and wrong_before:
            hyp = " ".join(ref.split()[:-1])        # drops the last word
        rows.append({"id": idx, "variant": it["variant"], "hyp": hyp, "error": "", "audio_s": 3.0, "synth_s": 0.4})
    return {"engine": engine, "voice": "fa_IR-amir-medium", "asr": {"model": "faster-whisper-small", "device": "cuda",
                                                                    "compute_type": "float16", "note": ""}, "items": rows}


class EvalFlow(Base):
    def setUp(self):
        super().setUp()
        from django.utils import timezone

        from apps.compute.models import ComputeNode

        # a registered node that is switched off: the durable queue parks the jobs for it
        ComputeNode.objects.create(name="gpu", capabilities={"voice": True, "kinds": ["voice.pron_eval", "voice.pron_asr"]},
                                   last_seen=timezone.now() - timedelta(days=3))
        patcher = mock.patch.object(evalrun, "_spawn", lambda rid, items: None)       # no threads in tests
        patcher.start()
        self.addCleanup(patcher.stop)

    def _finish_jobs(self, run, **kw):
        for uid in run.jobs:
            job = ComputeJob.objects.get(uid=uid)
            res = fake_result(run.engine, job.payload["items"], **kw)
            out = compute.output_path(job, "result.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            job.state = ComputeJob.State.COMPLETED
            job.save(update_fields=["state"])

    def test_sentences_are_stable_and_quick_is_a_subset(self):
        full = evalrun.sentences("full")
        quick = evalrun.sentences("quick")
        self.assertEqual(len(full), len(eval_set.SENTENCES))
        self.assertEqual({t for _, t, _ in quick}, set(eval_set.TAGS))
        self.assertTrue(set(i for i, _, _ in quick) <= set(i for i, _, _ in full))

    def test_build_items_piper_and_text(self):
        rows = evalrun.sentences("quick")[:3]
        items, shown = evalrun.build_items("piper", rows)
        self.assertEqual(len(items), 6)
        before = [i for i in items if i["variant"] == "before"]
        after = [i for i in items if i["variant"] == "after"]
        self.assertTrue(all("text" in i for i in before))
        self.assertTrue(all(i["ipa"] for i in after))
        self.assertTrue(any("{{" in s for i in after for s in i["ipa"]))       # hybrid: native words are marked for the node
        items, _ = evalrun.build_items("moss", rows)
        self.assertTrue(all("text" in i for i in items))

    def test_node_run_waits_then_collects(self):
        run = evalrun.start(self.owner, self.store, "piper", sample="quick")
        self.assertEqual(run.state, EvalRun.State.WAITING)
        self.assertEqual(len(run.jobs), 2)            # 32 sentences, 16 per job
        self.assertEqual(ComputeJob.objects.filter(kind="voice.pron_eval", origin="pron_eval").count(), 2)
        self.assertEqual(evalrun.advance_run(run), "waiting")
        self._finish_jobs(run)
        self.assertEqual(evalrun.advance_run(run), "done")
        run.refresh_from_db()
        self.assertEqual(run.state, EvalRun.State.DONE)
        s = run.summary
        self.assertGreater(s["overall"]["before"], s["overall"]["after"])
        self.assertEqual(s["overall"]["after"], 0.0)
        self.assertEqual(run.asr, "faster-whisper-small / cuda")
        self.assertTrue(all(r["before"] is not None and r["after"] is not None for r in run.rows))

    def test_a_running_job_shows_as_running(self):
        run = evalrun.start(self.owner, self.store, "piper", sample="quick")
        ComputeJob.objects.filter(uid=run.jobs[0]).update(state=ComputeJob.State.RUNNING)
        evalrun.advance_run(run)
        run.refresh_from_db()
        self.assertEqual(run.state, EvalRun.State.RUNNING)

    def test_failed_job_fails_the_run_with_the_reason(self):
        run = evalrun.start(self.owner, self.store, "piper", sample="quick")
        ComputeJob.objects.filter(uid=run.jobs[0]).update(state=ComputeJob.State.FAILED, error="Piper failed (exit 1)")
        evalrun.advance_run(run)
        run.refresh_from_db()
        self.assertEqual(run.state, EvalRun.State.FAILED)
        self.assertIn("Piper failed", run.message)

    def test_missed_words_become_problems(self):
        run = evalrun.start(self.owner, self.store, "piper", sample="quick")
        self._finish_jobs(run)
        for uid in run.jobs:                       # after hears the same wrong word in every sentence
            job = ComputeJob.objects.get(uid=uid)
            p = compute.output_path(job, "result.json")
            data = json.loads(p.read_text(encoding="utf-8"))
            for it in data["items"]:
                it["hyp"] = it["hyp"].replace("است", "")
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        evalrun.advance_run(run)
        self.assertTrue(ProblemWord.objects.filter(store=self.store, source="asr").exists())

    def test_only_one_run_per_engine_at_a_time(self):
        evalrun.start(self.owner, self.store, "piper", sample="quick")
        with self.assertRaises(evalrun.EvalError):
            evalrun.start(self.owner, self.store, "piper", sample="quick")

    def test_no_registered_node_fails_with_a_clear_message(self):
        with mock.patch.object(compute, "enqueue_durable", side_effect=compute.ComputeUnavailable("هیچ سرورِ پردازشی")):
            run = evalrun.start(self.owner, self.store, "piper", sample="quick")
        self.assertEqual(run.state, EvalRun.State.FAILED)
        self.assertIn("سرورِ پردازش", run.message)

    def test_edge_is_refused_on_a_local_only_platform(self):
        with mock.patch("services.audio.engines.local_only", return_value=True):
            run = evalrun.start(self.owner, self.store, "edge", sample="quick")
        self.assertEqual(run.state, EvalRun.State.FAILED)
        self.assertIn("فقط لوکال", run.message)

    def test_ensure_full_runs_is_idempotent(self):
        with mock.patch("services.audio.engines.local_only", return_value=True), \
                mock.patch.object(node_audio, "moss_ready", return_value=(False, "")):
            first = evalrun.ensure_full_runs()
            second = evalrun.ensure_full_runs()
        self.assertEqual(len(first), 2)                       # piper: the full layer and the text-only normaliser
        self.assertEqual(second, [])
        runs = EvalRun.objects.filter(pk__in=first)
        self.assertEqual({r.depth for r in runs}, {"lexicon", "normalize"})
        self.assertEqual({r.sample for r in runs}, {"full"})
        self.assertTrue(all(r.store is None for r in runs))

    def test_normalize_depth_sends_plain_normalised_text(self):
        rows = evalrun.sentences("quick")[:2]
        items, _ = evalrun.build_items("piper", rows, depth="normalize")
        after = [i for i in items if i["variant"] == "after"]
        self.assertTrue(all("text" in i and "ipa" not in i for i in after))

    def test_two_depths_of_one_engine_may_run_side_by_side(self):
        evalrun.start(self.owner, self.store, "piper", sample="quick", depth="lexicon")
        evalrun.start(self.owner, self.store, "piper", sample="quick", depth="normalize")
        with self.assertRaises(evalrun.EvalError):
            evalrun.start(self.owner, self.store, "piper", sample="quick", depth="lexicon")

    def test_baseline_file_seeds_once(self):
        data = {"runs": [{"engine": "piper", "voice": "fa_IR-amir-medium", "sample": "full", "n": 2, "asr": "vosk",
                          "summary": {"overall": {"n": 2, "before": 0.3, "after": 0.2}}, "rows": []}]}
        f = self.media / "baseline.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(svc, "BASELINE_FILE", f):
            self.assertEqual(svc.seed_baseline(), 1)
            self.assertEqual(svc.seed_baseline(), 0)
        self.assertTrue(EvalRun.objects.get(baseline=True).state == EvalRun.State.DONE)

    def test_the_shipped_baseline_file_is_valid(self):
        if not svc.BASELINE_FILE.is_file():
            self.skipTest("no baseline shipped")
        data = json.loads(svc.BASELINE_FILE.read_text(encoding="utf-8"))
        for run in data["runs"]:
            self.assertIn(run["engine"], svc.ENGINES)
            o = run["summary"]["overall"]
            self.assertTrue(0 <= o["before"] <= 1 and 0 <= o["after"] <= 1)
            self.assertGreaterEqual(run["n"], 200)

    def test_edge_flow_synthesises_then_queues_listening(self):
        class Comm:
            def __init__(self, text, voice, **kw):
                self.text = text

            async def save(self, path):
                Path(path).write_bytes(b"ID3x")

        fake = types.ModuleType("edge_tts")
        fake.Communicate = Comm
        with mock.patch.dict(sys.modules, {"edge_tts": fake}), \
                mock.patch("services.audio.engines.local_only", return_value=False), \
                mock.patch.object(evalrun, "_spawn", lambda rid, items: evalrun._edge_synth(rid, items)):      # synchronously here
            run = evalrun.start(self.owner, self.store, "edge", sample="quick")
        run.refresh_from_db()
        self.assertEqual(run.state, EvalRun.State.WAITING, run.message)
        self.assertEqual(run.meta["stage"], "asr")
        self.assertTrue(ComputeJob.objects.filter(kind="voice.pron_asr").exists())
        job = ComputeJob.objects.filter(kind="voice.pron_asr").first()
        self.assertTrue(job.payload["files"])


# ───────────────────────────────────────────────────────────── the node self-test

class MeasuredDepth(Base):
    def run_with(self, engine, depth, after, **kw):
        return EvalRun.objects.create(store=None, engine=engine, depth=depth, sample="full", state=EvalRun.State.DONE,
                                      summary={"overall": {"n": 230, "before": 0.3, "after": after}}, **kw)

    def test_no_measurement_keeps_the_built_in_default(self):
        self.assertEqual(svc.measured_depths(), {})
        self.assertEqual(svc.effective_default("piper"), fa_pron.DEFAULT_DEPTH["piper"])

    def test_one_depth_is_not_enough(self):
        self.run_with("edge", "lexicon", 0.10)
        self.assertEqual(svc.measured_depths(), {})

    def test_the_better_depth_wins(self):
        self.run_with("moss", "lexicon", 0.12)
        self.run_with("moss", "normalize", 0.08)
        self.assertEqual(svc.measured_depths()["moss"], "normalize")
        self.assertEqual(svc.effective_default("moss"), "normalize")

    def test_a_difference_under_one_point_is_noise(self):
        base = fa_pron.DEFAULT_DEPTH["moss"]
        other = "normalize" if base == "lexicon" else "lexicon"
        self.run_with("moss", base, 0.100)
        self.run_with("moss", other, 0.095)
        self.assertEqual(svc.measured_depths()["moss"], base)

    def test_baseline_and_failed_runs_do_not_count(self):
        self.run_with("edge", "lexicon", 0.2, baseline=True)
        self.run_with("edge", "normalize", 0.1, baseline=True)
        self.assertEqual(svc.measured_depths(), {})

    def test_store_choice_beats_the_measurement(self):
        self.run_with("moss", "lexicon", 0.12)
        self.run_with("moss", "normalize", 0.08)
        svc.save_settings(self.store, depth={"moss": "full"})
        self.assertEqual(svc.runtime_for(self.store)[2]["moss"], "full")
        self.assertEqual(svc.runtime_for(self.store2)[2]["moss"], "normalize")

    def test_piper_normalize_depth_is_the_plain_text_path(self):
        svc.save_settings(self.store, depth={"piper": "normalize"})
        v = FakeVoice()
        p = tts.PiperProvider("fa_IR-amir-medium")
        p.store, p.language = self.store, "fa"
        with mock.patch.object(tts.PiperProvider, "_load", lambda self_: v):
            p.synthesize("قیمت ۲۵۰,۰۰۰ تومان", self.media / "n.wav")
        self.assertEqual(v.id_calls, [])
        self.assertEqual(v.synth_calls, ["قیمت دویست و پنجاه هزار تومان"])


class SelfTestModule(Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(evalrun, "_spawn", lambda rid, items: None)       # a pass queues the full runs: no threads here
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_registered(self):
        from apps.compute import selftests

        selftests.load_all(force=True)
        self.assertIn("pron_piper", selftests.REGISTRY)
        t = selftests.REGISTRY["pron_piper"]
        self.assertEqual(t.kind, "voice.pron_eval")
        self.assertEqual(t.group, "audio")

    def test_spec_has_six_sentences_twice(self):
        from apps.compute.selftests import pron

        spec = pron.build(None)
        self.assertEqual(spec.kind, "voice.pron_eval")
        self.assertEqual(len(spec.payload["items"]), 2 * len(pron.SENTENCE_IDS))
        self.assertEqual(spec.payload["engine"], "piper")

    def test_availability(self):
        from apps.compute.selftests import pron

        node = types.SimpleNamespace(capabilities={"kinds": ["echo"], "voice": True}, auto_switch=False)
        self.assertFalse(pron._kinds_ok(node)[0])
        node.capabilities = {"kinds": ["voice.pron_eval"], "voice": True}
        self.assertTrue(pron._kinds_ok(node)[0])
        node.capabilities = {"voice": True}
        self.assertFalse(pron._kinds_ok(node)[0])

    def _ctx(self, data):
        return types.SimpleNamespace(read_json=lambda job, name: data)

    def test_check_passes_when_the_layer_helps(self):
        from apps.compute.selftests import pron

        _rows, items = pron._items()
        data = fake_result("piper", items)
        v = pron.check(self._ctx(data), None)
        self.assertTrue(v.ok, v.detail)
        self.assertEqual(v.device, "cuda")
        self.assertLess(v.extra["wer_after"], v.extra["wer_before"])

    def test_check_fails_when_the_layer_makes_it_worse(self):
        from apps.compute.selftests import pron

        _rows, items = pron._items()
        data = fake_result("piper", items, wrong_before=False)
        for it in data["items"]:
            if it["variant"] == "after":
                it["hyp"] = " ".join(it["hyp"].split()[:2])
        v = pron.check(self._ctx(data), None)
        self.assertFalse(v.ok)

    def test_check_fails_when_nothing_was_heard(self):
        from apps.compute.selftests import pron

        _rows, items = pron._items()
        data = fake_result("piper", items)
        for it in data["items"]:
            it["hyp"] = ""
        self.assertFalse(pron.check(self._ctx(data), None).ok)
        self.assertFalse(pron.check(self._ctx(None), None).ok)

    def test_cpu_device_is_a_warning_not_a_failure(self):
        from apps.compute.selftests import pron

        _rows, items = pron._items()
        data = fake_result("piper", items)
        data["asr"]["device"] = "cpu"
        v = pron.check(self._ctx(data), None)
        self.assertTrue(v.ok)
        self.assertTrue(v.warning)

    def test_fixed_sentence_ids_exist(self):
        from apps.compute.selftests import pron

        self.assertTrue(all(i < len(eval_set.SENTENCES) for i in pron.SENTENCE_IDS))
        self.assertEqual(len({eval_set.SENTENCES[i][0] for i in pron.SENTENCE_IDS}), len(pron.SENTENCE_IDS))


class Migration(TestCase):
    def test_tables_exist(self):
        self.assertEqual(LexiconEntry.objects.count(), 0)
        self.assertEqual(ProblemWord.objects.count(), 0)
        self.assertEqual(EvalRun.objects.filter(store=None, baseline=False).count(), 0)

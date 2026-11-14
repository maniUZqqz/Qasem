"""Speech language of the automatic edit and the subtitles (review of 2026-11-13): the brief asks for Persian AND English.

The site used to send ``language: "fa"`` for every video, so an English talking video was forced through the Persian setting and its word cuts,
fillers, retakes and subtitles came out wrong.  Now the editor's «زبانِ گفتار» (Persian default / English / auto) reaches the node's
``asr.transcribe`` job, Persian keeps every old behaviour (payload, cache key), and "auto" is only sent to an agent that advertises it.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from services.editing import captions


def node(**caps):
    return SimpleNamespace(capabilities=caps)


class LanguageChoiceTests(SimpleTestCase):
    def test_unknown_values_fall_back_to_persian(self):
        self.assertEqual([captions.clean_language(v) for v in ("fa", "en", "auto", "EN ", "", None, "de", "xx")],
                         ["fa", "en", "auto", "en", "fa", "fa", "fa", "fa"])
        for key in captions.LANGUAGES:
            self.assertTrue(captions.LANGUAGE_LABELS[key])

    def test_the_default_payload_is_the_old_persian_one(self):
        self.assertEqual(captions.whisper_payload([node(asr_models=["small"])])["language"], "fa")
        self.assertEqual(captions.WHISPER_PAYLOAD["language"], "fa")

    def test_english_is_sent_to_any_whisper_node(self):
        self.assertEqual(captions.whisper_payload([node(kinds=["asr.transcribe"])], "en")["language"], "en")
        self.assertEqual(captions.whisper_payload([node(asr_models=["small"])], "en")["language"], "en")

    def test_auto_is_an_empty_language_only_for_agents_that_understand_it(self):
        new = node(asr_models=["small"], asr_languages=["fa", "en", "auto"])
        old = node(asr_models=["small"])
        self.assertEqual(captions.whisper_payload([new], "auto")["language"], "")
        self.assertEqual(captions.whisper_payload([old], "auto")["language"], "fa", "an older worker would refuse the value")
        self.assertEqual(captions.whisper_payload([new, old], "auto")["language"], "fa", "one old node is enough to stay safe")
        self.assertEqual(captions.whisper_payload([], "auto")["language"], "fa")

    def test_the_shared_constant_is_never_mutated(self):
        captions.whisper_payload([node(asr_languages=["auto"])], "auto")
        captions.whisper_payload([node(asr_languages=["auto"])], "en")
        self.assertEqual(captions.WHISPER_PAYLOAD["language"], "fa")


class TranscribeRouteTests(SimpleTestCase):
    """What `transcribe_wav` sends for each language (the compute queue is replaced by a recorder)."""

    def run_route(self, language, whisper, voice_nodes, local=False, registered=True):
        sent = []

        def enqueue(kind, payload, **kw):
            sent.append((kind, dict(payload)))
            return SimpleNamespace(kind=kind)

        words = [{"w": "hello", "s": 0.0, "e": 0.4}]
        with mock.patch("apps.compute.services.online_nodes", lambda cap="any": voice_nodes),                 mock.patch("apps.compute.services.enqueue", enqueue),                 mock.patch("apps.compute.services.wait", lambda job, *a, **k: job),                 mock.patch.object(captions, "whisper_nodes", lambda compute: whisper),                 mock.patch.object(captions, "_result_words", lambda compute, job: words),                 mock.patch.object(captions, "_local_ready", lambda: local),                 mock.patch.object(captions, "node_registered", lambda cap="voice": registered):
            try:
                result = captions.transcribe_wav("x.wav", language=language)
            except captions.CaptionsUnavailable as exc:
                result = exc
        return sent, result

    def test_persian_is_unchanged_whisper_first_then_the_voice_recogniser(self):
        n = node(asr_models=["small"], asr_languages=["fa", "en", "auto"])
        sent, result = self.run_route("fa", [n], [n])
        self.assertEqual([k for k, _p in sent], ["asr.transcribe"])
        self.assertEqual(sent[0][1]["language"], "fa")
        self.assertEqual(result["language"], "fa")

    def test_english_goes_to_whisper_with_en(self):
        n = node(asr_models=["small"], asr_languages=["fa", "en", "auto"])
        sent, result = self.run_route("en", [n], [n])
        self.assertEqual(sent[0][0], "asr.transcribe")
        self.assertEqual(sent[0][1]["language"], "en")
        self.assertEqual(result["language"], "en")

    def test_auto_sends_an_empty_language_to_a_new_agent(self):
        n = node(asr_models=["small"], asr_languages=["fa", "en", "auto"])
        sent, result = self.run_route("auto", [n], [n])
        self.assertEqual(sent[0][1]["language"], "")
        self.assertEqual(result["language"], "auto")

    def test_english_never_uses_the_persian_only_voice_recogniser(self):
        """No Whisper agent, only the PersianAiKit's `voice.asr`: English must wait for Whisper, not be recognised as Persian."""
        voice_only = node(kinds=["voice.asr"])
        sent, result = self.run_route("en", [], [voice_only], local=False, registered=True)
        self.assertEqual(sent, [], "voice.asr hears Persian only")
        self.assertIsInstance(result, captions.CaptionsUnavailable)
        self.assertEqual(getattr(result, "node_waiting", ""), "voice")                 # parked until the node has Whisper

    def test_persian_still_falls_back_to_the_voice_recogniser(self):
        voice_only = node(kinds=["voice.asr"])
        sent, _result = self.run_route("fa", [], [voice_only])
        self.assertEqual([k for k, _p in sent], ["voice.asr"])


class PolishPayloadTests(SimpleTestCase):
    def test_the_language_reaches_the_director_options_only_when_it_is_not_persian(self):
        from apps.content.views_autoedit import autoedit_payload

        self.assertNotIn("language", autoedit_payload(5)["options"])
        self.assertNotIn("language", autoedit_payload(5, language="fa")["options"])
        self.assertEqual(autoedit_payload(5, language="en")["options"]["language"], "en")
        self.assertEqual(autoedit_payload(5, language="auto")["options"]["language"], "auto")
        self.assertNotIn("language", autoedit_payload(5, language="klingon")["options"])


class CaptionLookTests(SimpleTestCase):
    """The panel's «ظاهرِ زیرنویس» reaches the polish recipe: all seven looks are selectable (before, only karaoke or pop)."""

    def plan(self, brief):
        from services.editing.director import brief as brief_mod
        from services.editing.director import recipes

        assets = [{"ref": "video:1", "kind": "video", "duration": 30}]
        an = {"by_ref": {"video:1": {"kind": "video", "duration": 30, "box": {}}}, "has_speech": True, "has_words": False}
        ctx = {"an": an, "brief": brief, "assets": assets, "plat": brief_mod.PLATFORMS["reels"], "v": recipes.VARIANTS["a"], "pace": "normal", "music": ""}
        return recipes._polish(ctx)

    def test_every_look_is_chosen_by_the_panel_and_lands_in_the_captions_step(self):
        from services.editing.director.tools import CAPTION_STYLES

        self.assertEqual(set(CAPTION_STYLES), {"pop", "box", "karaoke", "clean", "neon", "typewriter", "lower"})
        for look in CAPTION_STYLES:
            steps = self.plan({"music": False, "caption_style": look})
            self.assertEqual([s["params"]["style"] for s in steps if s["tool"] == "add_captions"], [look], look)

    def test_without_a_choice_the_old_behaviour_stays(self):
        steps = self.plan({"music": False})
        self.assertIn([s["params"]["style"] for s in steps if s["tool"] == "add_captions"][0], ("pop", "karaoke"))
        steps = self.plan({"music": False, "caption_style": "bogus"})
        self.assertIn([s["params"]["style"] for s in steps if s["tool"] == "add_captions"][0], ("pop", "karaoke"))

    def test_the_override_only_accepts_known_looks(self):
        from services.editing.director import loop

        good, bad = {"matched": [], "notes": []}, {"matched": [], "notes": []}
        loop._apply_override(good, {"caption_style": "neon"})
        loop._apply_override(bad, {"caption_style": "bogus"})
        self.assertEqual(good["caption_style"], "neon")
        self.assertNotIn("caption_style", bad)

    def test_the_endpoint_payload_carries_the_look_in_the_override(self):
        from apps.content.views_autoedit import autoedit_payload

        self.assertEqual(autoedit_payload(5, caption_style="typewriter")["options"]["override"]["caption_style"], "typewriter")
        self.assertNotIn("caption_style", autoedit_payload(5)["options"]["override"])
        self.assertNotIn("caption_style", autoedit_payload(5, caption_style="bogus")["options"]["override"])

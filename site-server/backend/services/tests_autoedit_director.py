"""The automatic edit's director side: smart cuts (with the owner's remembered answers), the polish recipe and the tools it uses."""
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from services.editing import silence_intel as si
from services.editing.director import projectops as ops
from services.editing.director.spec import Ctx

from .tests_director import ASSETS, SPANS, check_valid, fake_ctx, run_tool, with_clip


class SmartCutsTests(SimpleTestCase):
    def test_dead_air_goes_short_pauses_tighten_and_the_unclear_one_is_left_for_the_owner(self):
        # video:3 speaks 0.5–3.0, 4.5–9.0, 11.0–19.0 of 20 s: gaps 3.0–4.5 (1.5 s, no cue → asked), 9.0–11.0 (2 s → asked), 19.0–20 (trail 1.0)
        p = with_clip("video:3", start=0, end=20)
        p, r = run_tool(p, "smart_cuts", {"clip": "all"})
        self.assertTrue(r["ok"], r)
        self.assertIn("مبهم", r["message"])
        total = ops.project_length(p)
        self.assertLess(total, 19.0, "the leading/trailing dead air is trimmed")
        self.assertGreater(total, 17.0, "the 1.5 s and 2 s pauses may be intended: they stay clearly audible pauses (about a second)")
        check_valid(self, p)

    def test_an_answer_cut_is_applied_and_remembered_across_runs(self):
        tmp = tempfile.mkdtemp(prefix="nm-smartcuts-")

        class Store:
            pk = 5

        ctx = fake_ctx(store=Store())
        with override_settings(NM_DATA_DIR=Path(tmp)):
            first, _ = run_tool(with_clip("video:3", start=0, end=20), "smart_cuts", {"clip": "all"}, ctx=ctx)
            si.save_answers(5, "video:3", [{"start": 9.0, "end": 11.0, "action": "cut"}, {"start": 3.0, "end": 4.5, "action": "keep"}])
            second, r = run_tool(with_clip("video:3", start=0, end=20), "smart_cuts", {"clip": "all"}, ctx=ctx)
            self.assertTrue(r["ok"], r)
            self.assertIn("پاسخِ", r["message"])
            # 20 s − lead 0.35 − trail 0.85 − the 2 s pause cut hard (2.0 − 2×0.12) − the 1.5 s pause kept whole
            self.assertAlmostEqual(ops.project_length(second), 17.04, delta=0.1)
            self.assertGreater(ops.project_length(first), ops.project_length(second), "unanswered, the 1.5 s pause was still tightened")

    def test_it_says_when_the_words_are_unknown_and_still_cuts(self):
        def no_asr(ref, a, b):
            raise RuntimeError("سرورِ پردازش خاموش است")

        p, r = run_tool(with_clip("video:3", start=0, end=20), "smart_cuts", {"clip": "all"}, ctx=fake_ctx(words=no_asr))
        self.assertTrue(r["ok"], r)
        self.assertIn("کلمه‌ها شناخته نشد", r["message"])

    def test_cuts_never_land_inside_a_known_word(self):
        # a word whose tail runs into the energy gap 3.0–4.5 (it ends at 3.3): the cut may only start after it
        words = [{"w": "سلام", "s": 0.6, "e": 1.0}, {"w": "محصول", "s": 2.4, "e": 3.3}, {"w": "عالیه", "s": 4.5, "e": 5.0}]
        ctx = fake_ctx(words=lambda ref, a, b: [{**w, "s": round(w["s"] - a, 3), "e": round(w["e"] - a, 3)} for w in words])
        with override_settings(NM_DATA_DIR=Path(tempfile.mkdtemp(prefix="nm-smartcuts-w-"))):
            class S:
                pk = 6
            ctx.store = S()
            si.save_answers(6, "video:3", [{"start": 3.0, "end": 4.5, "action": "cut"}])
            p, r = run_tool(with_clip("video:3", start=0, end=20), "smart_cuts", {"clip": "all"}, ctx=ctx)
            self.assertTrue(r["ok"], r)
            for clip in ops.main_track(p)["clips"]:
                for w in words:
                    self.assertFalse(w["s"] + 0.01 < clip["start"] < w["e"] - 0.01 or w["s"] + 0.01 < clip["end"] < w["e"] - 0.01,
                                     f"a piece boundary ({clip['start']}, {clip['end']}) is inside the word {w}")

    def test_no_speech_is_a_clear_refusal(self):
        p, r = run_tool(with_clip("video:1", start=0, end=8), "smart_cuts", {"clip": "all"})
        self.assertFalse(r["ok"], "a silent clip has nothing to cut")

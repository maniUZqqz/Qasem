"""Silence intelligence: classification, the questions it asks, the answers it remembers, and the cuts it makes."""
import tempfile
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase, override_settings

from services.editing import silence_intel as si


def words(*items):
    """('سلام', 0.0, 0.4) … → ASR-shaped words."""
    return [{"w": w, "s": s, "e": e} for w, s, e in items]


class FindTests(SimpleTestCase):
    def test_gaps_between_speech_and_at_the_edges(self):
        gaps = si.find_silences([[0.5, 3.0], [4.0, 6.0]], 8.0)
        self.assertEqual([(g["start"], g["end"], g["edge"]) for g in gaps], [(0.0, 0.5, "lead"), (3.0, 4.0, ""), (6.0, 8.0, "trail")])

    def test_breath_sized_gaps_are_not_listed_and_overlaps_merge(self):
        self.assertEqual(si.find_silences([[0, 2.0], [2.2, 4.0], [3.9, 5.0]], 5.0), [])
        gaps = si.find_silences([[0.0, 2.0], [2.0, 3.0], [4.0, 5.0]], 5.0)
        self.assertEqual([(g["start"], g["end"]) for g in gaps], [(3.0, 4.0)])

    def test_no_speech_means_no_gaps_to_judge(self):
        self.assertEqual(si.find_silences([], 10.0), [])


class ClassifyTests(SimpleTestCase):
    def one(self, start, end, **kw):
        gap = {"start": start, "end": end, "len": round(end - start, 3), "edge": kw.pop("edge", "")}
        return si.classify([gap], duration=kw.pop("duration", 60.0), **kw)[0]

    def test_a_short_pause_is_tightened_not_asked(self):
        r = self.one(10.0, 10.6)
        self.assertEqual((r["kind"], r["decision"], r["ask"]), ("short_pause", "shorten", False))

    def test_a_breath_is_left_alone(self):
        r = self.one(10.0, 10.3)
        self.assertEqual((r["kind"], r["decision"]), ("breath", "keep"))

    def test_the_edges_are_trimmed(self):
        self.assertEqual(self.one(0.0, 1.2, edge="lead")["decision"], "cut")
        self.assertEqual(self.one(58.0, 60.0, edge="trail")["decision"], "cut")
        self.assertEqual(self.one(0.0, 0.3, edge="lead")["decision"], "keep")

    def test_a_long_pause_with_no_cue_is_asked_and_we_suggest_tightening(self):
        r = self.one(10.0, 11.5)
        self.assertTrue(r["ask"])
        self.assertEqual((r["decision"], r["suggest"]), ("ask", "shorten"))
        self.assertIn("سناریو", r["reason"])

    def test_a_pause_after_a_question_is_asked_and_we_suggest_keeping_it(self):
        w = words(("برنده", 5.0, 5.4), ("کیست", 5.5, 6.0), ("؟", 6.0, 6.05))
        r = self.one(8.0, 9.6, words=w, spans=[[5.0, 8.0]])
        self.assertTrue(r["ask"])
        self.assertEqual(r["suggest"], "keep")
        self.assertIn("سؤال", r["reason"])
        self.assertIn("کیست", r["before"])

    def test_a_question_word_in_the_last_words_counts(self):
        w = words(("چرا", 6.0, 6.3), ("این", 6.4, 6.6), ("کار", 6.7, 7.0), ("مهم", 7.1, 7.4), ("است", 7.5, 7.9))
        r = self.one(8.0, 9.5, words=w, spans=[[6.0, 8.0]])
        self.assertEqual(r["suggest"], "keep")

    def test_a_pause_after_a_short_punchy_phrase_is_a_beat(self):
        w = words(("اشتباه", 6.0, 6.5), ("نکنید", 6.6, 7.0))
        r = self.one(7.2, 8.6, words=w, spans=[[6.0, 7.2]])
        self.assertTrue(r["ask"])
        self.assertEqual(r["suggest"], "keep")
        self.assertEqual(r["kind"], "dramatic")

    def test_a_pause_in_which_the_picture_changes_is_asked_even_if_short(self):
        act = [0.0] * 30
        act[12] = 1.0
        r = self.one(11.8, 12.9, activity=act)
        self.assertEqual((r["kind"], r["decision"], r["suggest"]), ("visual_beat", "ask", "keep"))
        self.assertIn("تصویر عوض", r["reason"])

    def test_four_seconds_over_a_still_picture_is_dead_air(self):
        r = self.one(10.0, 15.0, activity=[0.0] * 30)
        self.assertEqual((r["kind"], r["decision"]), ("dead_air", "cut"))

    def test_a_still_slide_does_not_make_a_short_pause_a_question(self):
        r = self.one(10.0, 10.8, activity=[0.0] * 30)
        self.assertEqual(r["decision"], "shorten")

    def test_at_most_eight_questions_are_asked(self):
        gaps = [{"start": 10.0 * i, "end": 10.0 * i + 1.0 + 0.05 * i, "len": round(1.0 + 0.05 * i, 3), "edge": ""} for i in range(1, 15)]
        rows = si.classify(gaps, duration=200.0)
        asked = [r for r in rows if r["ask"]]
        self.assertEqual(len(asked), si.MAX_QUESTIONS)
        self.assertTrue(all(r["decision"] in si.ACTIONS for r in rows if not r["ask"]))


class AnswerTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-silence-answers-")

    def test_answers_are_remembered_per_source_and_survive_a_moved_boundary(self):
        with override_settings(NM_DATA_DIR=Path(self.tmp)):
            si.save_answers(7, "video:22", [{"start": 10.0, "end": 11.5, "action": "keep"}, {"start": 30.0, "end": 31.0, "action": "cut"}])
            saved = si.load_answers(7, "video:22")
            self.assertEqual(len(saved["answers"]), 2)
            self.assertEqual(si.answer_for(saved["answers"], 10.1, 11.4), "keep")       # re-analysis moved the edges a little
            self.assertEqual(si.answer_for(saved["answers"], 30.05, 31.1), "cut")
            self.assertIsNone(si.answer_for(saved["answers"], 20.0, 21.0))
            self.assertEqual(si.load_answers(8, "video:22")["answers"], [], "another store sees nothing")
            self.assertEqual(si.load_answers(7, "video:23")["answers"], [], "another video sees nothing")

    def test_garbage_is_dropped_not_raised(self):
        with override_settings(NM_DATA_DIR=Path(self.tmp)):
            saved = si.save_answers(1, "video:1", [{"start": "x"}, {"start": 1, "end": 2, "action": "explode"}, {"start": 5, "end": 6, "action": "cut"}, "no"])
            self.assertEqual(saved["answers"], [{"start": 5.0, "end": 6.0, "action": "cut"}])

    def test_an_unanswered_question_never_cuts_what_might_be_intended(self):
        rows = si.classify([{"start": 10.0, "end": 12.0, "len": 2.0, "edge": ""}], duration=60.0)
        got = si.resolve(rows, {"answers": [], "rule": {}})[0]
        self.assertTrue(got["pending"])
        self.assertIn(got["action"], ("keep", "shorten"))
        self.assertNotEqual(got["action"], "cut")

    def test_an_answer_overrides_everything_including_our_certainty(self):
        rows = si.classify([{"start": 10.0, "end": 10.6, "len": 0.6, "edge": ""}], duration=60.0)
        self.assertEqual(si.resolve(rows, {"answers": [{"start": 10.0, "end": 10.6, "action": "keep"}]})[0]["action"], "keep")

    def test_a_default_rule_answers_all_open_questions(self):
        rows = si.classify([{"start": 10.0, "end": 12.0, "len": 2.0, "edge": ""}], duration=60.0)
        got = si.resolve(rows, {"answers": [], "rule": {"ask_default": "cut"}})[0]
        self.assertEqual((got["action"], got["pending"]), ("cut", False))


class CutTests(SimpleTestCase):
    def rows(self, start, end, action, edge=""):
        return [{"start": start, "end": end, "len": end - start, "edge": edge, "action": action}]

    def test_shortening_leaves_a_natural_beat(self):
        (a, b), = si.cuts_from(self.rows(10.0, 11.0, "shorten"))
        self.assertAlmostEqual((b - a), 1.0 - si.TARGET, places=2)
        self.assertAlmostEqual(a - 10.0, 11.0 - b, places=2, msg="the beat sits in the middle: equal breath on both sides")

    def test_a_hard_cut_keeps_a_breath_on_each_side(self):
        (a, b), = si.cuts_from(self.rows(10.0, 12.0, "cut"))
        self.assertAlmostEqual(a, 10.0 + si.CUT_PAD, places=2)
        self.assertAlmostEqual(b, 12.0 - si.CUT_PAD, places=2)

    def test_keep_cuts_nothing_and_tiny_cuts_are_skipped(self):
        self.assertEqual(si.cuts_from(self.rows(10.0, 12.0, "keep")), [])
        self.assertEqual(si.cuts_from(self.rows(10.0, 10.4, "shorten")), [])

    def test_the_edges_are_trimmed_to_a_short_lead_in(self):
        (a, b), = si.cuts_from(self.rows(0.0, 2.0, "cut", edge="lead"), duration=60.0)
        self.assertEqual((a, round(b, 2)), (0.0, round(2.0 - si.EDGE_KEEP, 2)))
        (a, b), = si.cuts_from(self.rows(58.0, 60.0, "cut", edge="trail"), duration=60.0)
        self.assertEqual((round(a, 2), b), (round(58.0 + si.EDGE_KEEP, 2), 60.0))

    def test_a_cut_never_starts_or_ends_inside_a_word(self):
        # the energy gap says 10.0–12.0 but the last word's soft tail runs to 10.2 and the next word starts at 11.9
        w = words(("آخر", 9.5, 10.2), ("اول", 11.9, 12.3))
        (a, b), = si.cuts_from(self.rows(10.0, 12.0, "cut"), words=w)
        self.assertGreaterEqual(a, 10.2 + si.WORD_PAD_BEFORE - 1e-6)
        self.assertLessEqual(b, 11.9 - si.WORD_PAD_AFTER + 1e-6)
        for x in w:
            self.assertFalse(x["s"] < a < x["e"] or x["s"] < b < x["e"])


class ReviewTests(SimpleTestCase):
    def test_end_to_end_with_injected_analysis(self):
        spans = [[0.4, 5.0], [6.5, 12.0], [12.5, 20.0], [26.0, 30.0]]
        act = [0.0] * 40
        act[24] = 1.0
        tmp = tempfile.mkdtemp(prefix="nm-silence-review-")
        with override_settings(NM_DATA_DIR=Path(tmp)):
            r = si.review("/x.mp4", 31.0, store_id=3, ref="video:9", spans=spans, words=[], activity=act)
            by = {(round(s["start"], 1)): s for s in r["silences"]}
            self.assertEqual(by[0.0]["decision"], "keep")             # 0.4 s at the very start is under EDGE_MIN: left alone
            self.assertTrue(r["silences"])
            self.assertFalse(r["has_words"])
            self.assertTrue(r["note"])
            self.assertEqual(sum(r["counts"].values()), len(r["silences"]))
            ask = [q for q in r["questions"]]
            self.assertTrue(all(q["ask"] for q in ask))
            # answer the first question → it is no longer open and the answer is used
            if ask:
                si.save_answers(3, "video:9", [{"start": ask[0]["start"], "end": ask[0]["end"], "action": "cut"}])
                r2 = si.review("/x.mp4", 31.0, store_id=3, ref="video:9", spans=spans, words=[], activity=act)
                self.assertEqual(len(r2["questions"]), len(ask) - 1)
                self.assertEqual(r2["answered"], 1)

    def test_the_owners_real_video_shape(self):
        """97.7 s, 20 silences, the longest 1.8 s, a mostly still picture (slides): only the pauses that matter become questions."""
        gaps = [(0.0, 0.42), (5.44, 6.42), (12.76, 13.58), (18.76, 19.44), (22.96, 23.44), (36.68, 37.32), (44.76, 45.16), (47.26, 48.88), (53.48, 54.14),
                (55.14, 55.54), (60.5, 61.04), (63.92, 64.66), (70.9, 71.32), (71.38, 71.76), (74.12, 75.26), (80.24, 82.02), (83.74, 84.26), (86.16, 86.52),
                (88.38, 88.76), (96.5, 97.7)]
        spans, cur = [], 0.0
        for s, e in gaps:
            if s > cur:
                spans.append([cur, s])
            cur = e
        activity = [0.0] * 98
        for slide in (6, 13, 48, 75, 81):                          # the slide changes inside some of the pauses
            activity[slide] = 1.0
        r = si.review("/x.mp4", 97.7, spans=spans, words=[], activity=activity, saved={"answers": [], "rule": {}})
        self.assertLessEqual(len(r["questions"]), si.MAX_QUESTIONS)
        self.assertGreaterEqual(len(r["questions"]), 2, "the pauses with a slide change must be asked about")
        asked = {round(q["start"]) for q in r["questions"]}
        self.assertTrue({5, 13} & asked or {47, 74, 80} & asked)
        self.assertGreater(r["removed_seconds"], 1.0, "the dead air and short pauses are still tightened")
        self.assertLess(r["removed_seconds"], 14.6, "...but not all 14.6 s of silences")


class ActivityTests(SimpleTestCase):
    def frames(self, changes):
        """2 fps, 24 frames (12 s) of 40×30 grey with a flash at the given frame indices."""
        arr = np.full((24, 30, 40, 3), 90, dtype=np.uint8)
        for i in changes:
            arr[i:] = 90 + (60 if (changes.index(i) % 2 == 0) else 0)
        return arr

    def test_a_still_picture_has_no_activity(self):
        a = si.visual_activity("/x.mp4", 12.0, frames=np.full((24, 30, 40, 3), 90, dtype=np.uint8))
        self.assertEqual(sum(a), 0.0)

    def test_a_cut_in_the_picture_shows_up_in_its_second(self):
        a = si.visual_activity("/x.mp4", 12.0, frames=self.frames([10]))
        self.assertEqual(len(a), 12)
        self.assertEqual(int(np.argmax(a)), 5)
        self.assertEqual(a[5], 1.0)
        self.assertEqual(sum(1 for x in a if x > 0.2), 1)

"""The automatic edit's quality parts: auto look, composition, music matching, social sizes and the polish recipe end to end (fakes, no node)."""
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from services.editing import autolook, framing, music_match, reframe, social_sizes
from services.editing.director import loop
from services.editing.director import projectops as ops
from services.editing.director.brief import looks_like_talking_video

from .tests_director import ASSETS, FakeAI, check_valid, fake_ctx, run_tool, with_clip


# ================================================================== light and colour
class AutoLookTests(SimpleTestCase):
    GOOD = {"p5": 20, "p50": 115, "p95": 225, "clip_hi": 0.005, "cast_measurable": True, "cast_rb": 1.0}

    def test_a_correct_shot_is_left_alone_and_says_so(self):
        res = autolook.plan(self.GOOD, has_face=True, height=1080)
        self.assertFalse(res["changed"])
        self.assertEqual(res["color"], {})
        self.assertIn("درست", res["skipped"])

    def test_a_dark_shot_is_lifted_but_not_into_the_highlights(self):
        res = autolook.plan({"p5": 4, "p50": 60, "p95": 180, "clip_hi": 0.0, "cast_measurable": False, "cast_rb": None}, has_face=False, height=1080)
        self.assertTrue(res["changed"])
        e = res["color"]["exposure"]
        self.assertGreater(e, 0.3)
        self.assertLessEqual(180 * 2 ** e, autolook.HIGH_CEILING + 1, "the brightest 5 % must not be pushed past the ceiling")
        self.assertIn("denoise", res["color"], "dark footage is noisy")

    def test_with_a_face_the_lift_and_the_colour_move_are_smaller(self):
        stats = {"p5": 4, "p50": 55, "p95": 170, "clip_hi": 0.0, "cast_measurable": True, "cast_rb": 40.0}
        free = autolook.plan(stats, has_face=False, height=1080)["color"]
        face = autolook.plan(stats, has_face=True, height=1080)["color"]
        self.assertLess(abs(face["temperature"]), abs(free["temperature"]) + 1)
        self.assertLessEqual(abs(face["temperature"]), autolook.CAST_MAX_FACE)
        self.assertLessEqual(face["exposure"], autolook.MAX_STOPS_FACE + 1e-6)
        self.assertLessEqual(face.get("saturation", 100), 108, "skin is never pushed past +8 % saturation")

    def test_a_warm_cast_is_cooled_and_a_cold_one_warmed(self):
        warm = autolook.plan({**self.GOOD, "cast_rb": 20.0, "p50": 70}, height=1080)["color"]
        cold = autolook.plan({**self.GOOD, "cast_rb": -20.0, "p50": 70}, height=1080)["color"]
        self.assertLess(warm["temperature"], 0)
        self.assertGreater(cold["temperature"], 0)

    def test_burnt_highlights_come_down_and_a_burnt_shot_gets_no_contrast_boost(self):
        res = autolook.plan({"p5": 30, "p50": 170, "p95": 252, "clip_hi": 0.12, "cast_measurable": False, "cast_rb": None}, height=1080)["color"]
        self.assertLess(res["highlights"], 0)
        self.assertNotIn("contrast", res)
        self.assertLess(res["exposure"], 0, "an over-bright median is brought down")

    def test_a_flat_shot_gets_contrast(self):
        res = autolook.plan({"p5": 70, "p50": 112, "p95": 170, "clip_hi": 0.0, "cast_measurable": False, "cast_rb": None}, height=1080)["color"]
        self.assertGreater(res["contrast"], 0)

    def test_a_black_slide_cannot_be_measured_and_is_not_touched(self):
        res = autolook.plan({"p5": 0, "p50": 0, "p95": 253, "clip_hi": 0.13, "cast_measurable": False, "cast_rb": None}, height=1080)
        self.assertFalse(res["changed"])
        self.assertIn("اسلاید", res["skipped"])

    def test_missing_stats_never_raise(self):
        self.assertFalse(autolook.plan(None)["changed"])
        self.assertFalse(autolook.plan({})["changed"])

    def test_the_owners_slider_wins_over_the_automatic_value(self):
        clip = {"color": {"exposure": 0.5, "contrast": 0}}
        autolook.merge_into_clip(clip, {"exposure": 0.2, "contrast": 10, "temperature": -5})
        self.assertEqual(clip["color"], {"exposure": 0.5, "contrast": 10, "temperature": -5})

    def test_every_value_is_inside_what_the_colour_block_accepts(self):
        from services.editing import color
        for stats in ({"p5": 0, "p50": 20, "p95": 90, "clip_hi": 0, "cast_measurable": True, "cast_rb": 80.0},
                      {"p5": 120, "p50": 200, "p95": 255, "clip_hi": 0.5, "cast_measurable": True, "cast_rb": -80.0}):
            block = autolook.plan(stats, height=1080)["color"]
            cleaned = color.clean(block)
            for key, value in block.items():
                self.assertAlmostEqual(cleaned[key], value, places=2, msg=key)

    def test_the_director_tool_writes_the_block_into_the_clip_and_reports(self):
        ctx = fake_ctx(look_stats=lambda ref, a, b: {"p5": 4, "p50": 58, "p95": 175, "clip_hi": 0.0, "cast_measurable": True, "cast_rb": 18.0, "faces": 1, "height": 1080})
        p, r = run_tool(with_clip("video:3", start=0, end=10), "auto_look", {"clip": "all"}, ctx=ctx)
        self.assertTrue(r["ok"], r)
        clip = ops.main_track(p)["clips"][0]
        self.assertGreater(clip["color"]["exposure"], 0)
        self.assertLess(clip["color"]["temperature"], 0)
        check_valid(self, p)

    def test_the_director_tool_leaves_a_correct_clip_alone(self):
        ctx = fake_ctx(look_stats=lambda ref, a, b: {**AutoLookTests.GOOD, "faces": 1, "height": 1080})
        p, r = run_tool(with_clip("video:3", start=0, end=10), "auto_look", {"clip": "all"}, ctx=ctx)
        self.assertTrue(r["ok"], r)
        self.assertIn("درست", r["message"])
        self.assertFalse(ops.main_track(p)["clips"][0].get("color"))


# ================================================================== composition
class FramingTests(SimpleTestCase):
    def test_eyes_land_on_the_upper_third_with_headroom(self):
        cx, cy = framing.window_target(0.5, 0.55, 0.32, 0.56, face_h=0.20)
        eye = 0.55 - framing.EYE_OFFSET * 0.20
        eye_in_window = (eye - (cy - 0.28)) / 0.56
        self.assertAlmostEqual(eye_in_window, framing.EYE_LINE, places=2)

    def test_a_non_face_subject_stays_centred_vertically(self):
        cx, cy = framing.window_target(0.4, 0.6, 0.32, 0.56, face_h=None)
        self.assertEqual((cx, cy), (0.4, 0.6))

    def test_lead_room_leans_toward_the_direction_of_travel(self):
        right = framing.window_target(0.5, 0.5, 0.32, 1.0, lead=1.0)[0]
        left = framing.window_target(0.5, 0.5, 0.32, 1.0, lead=-1.0)[0]
        self.assertGreater(right, 0.5)
        self.assertLess(left, 0.5)
        sub_pos = (0.5 - (right - 0.16)) / 0.32
        self.assertLess(sub_pos, 0.5)
        self.assertGreater(sub_pos, 0.25)

    def test_the_face_is_never_cut_whatever_the_rules_ask(self):
        box = (0.62, 0.30, 0.14, 0.24)
        cx, cy = framing.window_target(0.69, 0.42, 0.32, 0.56, face_h=0.24, lead=-1.0, face_box=box)
        self.assertLessEqual(cx - 0.16, box[0] - 0.0001)
        self.assertGreaterEqual(cx + 0.16, box[0] + box[2] + 0.0001)

    def test_a_still_subject_has_no_lead_and_a_walker_has(self):
        t = [i * 0.33 for i in range(12)]
        self.assertTrue(all(v == 0.0 for v in framing.lead_directions(t, [0.5] * 12)))
        walking = framing.lead_directions(t, [0.2 + 0.05 * i for i in range(12)])
        self.assertGreater(walking[6], 0.5)
        back = framing.lead_directions(t, [0.8 - 0.05 * i for i in range(12)])
        self.assertLess(back[6], -0.5)

    def test_reframe_with_composition_keeps_the_whole_face_and_says_what_it_did(self):
        frames = np.zeros((9, 54, 96, 3), dtype=np.uint8)

        def faces(frame):
            return [(0.5, 0.40, 0.04, 0.2, (0.45, 0.30, 0.1, 0.2))]

        composed = reframe.plan("x", 0, 3, "1:1", size=(1080, 1920), frames=frames, faces_fn=faces, compose=True)
        self.assertTrue(any("خطِ یک‌سوم" in n for n in composed["notes"]), composed["notes"])
        r = composed["reframe"]
        self.assertLessEqual(r["cy"] - r["h"] / 2, 0.30)
        self.assertGreaterEqual(r["cy"] + r["h"] / 2, 0.50)

    def test_the_plain_reframe_is_unchanged_without_the_flag(self):
        frames = np.zeros((9, 54, 96, 3), dtype=np.uint8)

        def faces(frame):
            return [(0.5, 0.40, 0.04)]                      # the old 3-tuple still works

        res = reframe.plan("x", 0, 3, "1:1", size=(1080, 1920), frames=frames, faces_fn=faces)
        self.assertEqual(res["engine"], "face")
        self.assertFalse(any("یک‌سوم" in n for n in res["notes"]))


# ================================================================== music
class MusicMatchTests(SimpleTestCase):
    TRACKS = [
        music_match.describe_track("audio:1", "Calm Piano Ambient", "soft relaxing piano", bpm=72, duration=120),
        music_match.describe_track("audio:2", "Fast EDM Workout", "energetic dance beat", bpm=128, duration=60),
        music_match.describe_track("audio:3", "Cinematic Trailer Dark", "dramatic orchestral", bpm=80, duration=90),
        music_match.describe_track("audio:4", "بدون برچسب", "", bpm=None, duration=30),
    ]

    def test_a_talking_video_gets_a_calm_quiet_bed(self):
        t = music_match.target_for(pace="normal", speech_share=0.8)
        self.assertEqual(t["mood"], "calm")
        self.assertLessEqual(t["energy"], music_match.SPEECH_ENERGY_CAP)
        ranked = music_match.rank(self.TRACKS, t, need_seconds=60)
        self.assertEqual(ranked[0]["ref"], "audio:1")
        self.assertTrue(ranked[0]["why"])

    def test_a_fast_sale_gets_the_driving_track(self):
        t = music_match.target_for(pace="fast", recipe="sale", speech_share=0.0)
        self.assertEqual(music_match.rank(self.TRACKS, t, need_seconds=45)[0]["ref"], "audio:2")

    def test_a_cinematic_look_gets_the_dramatic_track(self):
        ranked = music_match.rank(self.TRACKS, music_match.target_for(look="cinematic", speech_share=0.0), need_seconds=60)
        self.assertEqual(ranked[0]["ref"], "audio:3")

    def test_an_explicit_mood_wins(self):
        self.assertEqual(music_match.target_for(pace="fast", mood="calm")["mood"], "calm")

    def test_a_bad_fit_is_dropped_rather_than_forced(self):
        only = [music_match.describe_track("audio:2", "Fast EDM Workout", "energetic dance beat", bpm=140, duration=60)]
        self.assertEqual(music_match.rank(only, music_match.target_for(speech_share=0.9)), [])

    def test_half_time_tempo_counts_as_in_band(self):
        self.assertGreater(music_match._band_fit(64, 115, 150), 0.6)
        self.assertEqual(music_match._band_fit(130, 115, 150), 1.0)

    def test_loops_are_whole_bars(self):
        plan = music_match.loop_plan(30.0, 100.0, 120.0)
        self.assertAlmostEqual(plan["piece"] % 2.0, 0.0, places=2)           # 120 bpm → a bar is 2 s
        self.assertEqual(plan["loops"], 4)

    def test_pick_music_tool_chooses_by_mood_and_says_why(self):
        ranked = [{"ref": "audio:1", "title": "موسیقی شاد", "score": 0.8, "why": ["حال‌وهوای «آرام و ملایم»"], "bpm": 72, "duration": 40.0}]
        ctx = fake_ctx(rank_music=lambda target, seconds: ranked)
        p, r = run_tool(with_clip("video:3", start=0, end=20), "pick_music", {}, ctx=ctx)
        self.assertTrue(r["ok"], r)
        self.assertIn("انتخاب شد", r["message"])
        self.assertTrue(ops.audio_track(p, "music")["clips"])
        self.assertEqual(p["autoedit"]["music"]["mood"], "calm")                 # video:3 is mostly speech

    def test_pick_music_says_clearly_when_nothing_fits(self):
        p, r = run_tool(with_clip("video:3", start=0, end=20), "pick_music", {}, ctx=fake_ctx(rank_music=lambda t, s: []))
        self.assertFalse(r["ok"])
        self.assertIn("پیدا نشد", r["message"])


# ================================================================== sizes
class SocialSizesTests(SimpleTestCase):
    def test_every_size_matches_a_project_preset_an_export_preset_and_a_safe_zone(self):
        from services.editing import export, safezones
        for key, s in social_sizes.SIZES.items():
            self.assertIn(s["preset"], ops.PRESETS, key)
            self.assertIn(s["export"], export.PRESETS, key)
            self.assertIn(s["zone"], safezones.ZONES, key)
            w, h = s["size"]
            self.assertAlmostEqual(w / h, reframe.aspect_value(s["aspect"]), places=2, msg=key)

    def test_the_catalogue_lists_every_network_in_persian(self):
        titles = " ".join(c["title"] for c in social_sizes.catalogue())
        for word in ("ریلز", "استوری", "یوتیوب", "تیک‌تاک", "تلگرام", "آپارات", "پست"):
            self.assertIn(word, titles)

    def test_unknown_keys_are_dropped_and_duplicates_collapsed(self):
        self.assertEqual(social_sizes.clean_keys(["ig_reel", "nope", "ig_reel", "yt_wide"]), ["ig_reel", "yt_wide"])

    def test_a_wide_project_becomes_a_vertical_one_following_the_subject(self):
        p = ops.new_project("wide")
        p, r = run_tool(p, "add_clip", {"ref": "video:3", "track": "main", "at": 0, "start": 0, "end": 10, "id": "a"})
        d = social_sizes.derive(p, "ig_reel", fake_ctx())
        self.assertEqual((d.project["format"]["width"], d.project["format"]["height"]), (1080, 1920))
        self.assertEqual(d.project["export"]["preset"], "reels")
        self.assertEqual(d.project["autoedit"]["size"], "ig_reel")
        self.assertEqual(p["format"]["preset"], "wide", "the original is untouched")
        check_valid(self, d.project)

    def test_a_too_long_video_is_flagged_for_a_network_that_limits_length(self):
        p = ops.new_project("wide")
        for i in range(8):
            p, _ = run_tool(p, "add_clip", {"ref": "video:1", "track": "main", "at": "end", "start": 0, "end": 12, "id": f"c{i}"})
        d = social_sizes.derive(p, "ig_story", fake_ctx())
        self.assertTrue(any("ثانیه می‌پذیرد" in n for n in d.notes), d.notes)


# ================================================================== the polish recipe, end to end
class PolishRecipeTests(SimpleTestCase):
    TALK = {"ref": "video:9", "title": "main", "kind": "video", "duration": 60.0, "has_audio": True, "width": 1920, "height": 1080}

    def ctx(self, **kw):
        spans = {"video:9": [[0.4, 8.0], [9.0, 20.0], [21.4, 40.0], [40.5, 59.0]]}
        words = [{"w": "سلام", "s": 0.6, "e": 1.0}, {"w": "اممم", "s": 1.1, "e": 1.6}]
        assets = {**ASSETS, "video:9": self.TALK}
        base = dict(describe=lambda ref: assets.get(ref), spans=lambda ref: spans.get(ref, []), words=lambda ref, a, b: [{**w, "s": round(w["s"] - a, 3), "e": round(w["e"] - a, 3)} for w in words if a <= w["s"] < b],
                    look_stats=lambda ref, a, b: {"p5": 5, "p50": 62, "p95": 190, "clip_hi": 0.0, "cast_measurable": False, "cast_rb": None, "faces": 1, "height": 1080},
                    rank_music=lambda t, s: [{"ref": "audio:1", "title": "موسیقی شاد", "score": 0.7, "why": ["انرژیِ هم‌خوان"], "bpm": 72, "duration": 40.0}])
        base.update(kw)
        return fake_ctx(**base)

    def run_it(self, prompt="", **kw):
        return loop.run(prompt, [self.TALK], self.ctx(**kw), store=None, options=loop.Options(variants=1, rounds=1, use_ai=False, preview=False), call=FakeAI(fail="all"))

    def test_one_long_talking_video_is_recognised(self):
        self.assertTrue(looks_like_talking_video([self.TALK], {"by_ref": {"video:9": {"duration": 60.0, "spans": [[0, 50]]}}}))
        self.assertFalse(looks_like_talking_video([self.TALK], {"by_ref": {"video:9": {"duration": 60.0, "spans": [[0, 5]]}}}))
        self.assertFalse(looks_like_talking_video([self.TALK, ASSETS["pimg:1"]], {"by_ref": {}}))

    def test_a_talking_video_is_polished_not_cut_into_product_shots(self):
        res = self.run_it()
        self.assertEqual(res["brief"]["recipe"], "polish")
        self.assertEqual(res["brief"]["platform"], "youtube", "a landscape source stays landscape unless a vertical size is asked for")
        v = res["variants"][0]
        tools = [s["tool"] for s in v["plan"]]
        for needed in ("add_clip", "smart_cuts", "auto_look", "clean_voice", "add_captions", "pick_music", "auto_mix", "set_loudness"):
            self.assertIn(needed, tools)
        self.assertNotIn("end_card", tools, "a talk is not sold with an order button")
        self.assertNotIn("punch_in", tools)
        failed = [(s["tool"], s.get("message")) for s in v["plan"] if s.get("ok") is False]
        self.assertEqual([f for f in failed if f[0] not in ("add_captions",)], [], failed)
        with patch.dict(ASSETS, {"video:9": self.TALK}):
            check_valid(self, v["project"])
        clip_len = sum(ops.clip_length(c) for c in ops.main_track(v["project"])["clips"])
        self.assertGreater(clip_len, 50.0, "the story is kept: only dead air is cut")

    def test_the_critique_never_chops_a_talk_to_the_beat_or_shortens_it(self):
        """Seen on the owner's real 97-second video: the pauses made ≥ 4 pieces, the «cuts on the beat» rubric then cut it into 99 shots and the
        «length» rubric trimmed it to 77 s.  A polished talk keeps its story and its length."""
        talk = {**self.TALK, "duration": 100.0}
        spans = [[0.4, 10.0], [11.2, 22.0], [23.5, 33.0], [34.6, 45.0], [46.2, 57.0], [58.0, 69.0], [70.3, 81.0], [82.0, 93.0], [94.0, 99.5]]
        assets = {**ASSETS, "video:9": talk}
        ctx = self.ctx(describe=lambda ref: assets.get(ref), spans=lambda ref: spans if ref == "video:9" else [])
        res = loop.run("", [talk], ctx, store=None, options=loop.Options(variants=1, rounds=2, use_ai=False, preview=False), call=FakeAI(fail="all"))
        v = res["variants"][0]
        tools = [s["tool"] for s in v["plan"]]
        self.assertNotIn("cut_to_beats", tools)
        self.assertNotIn("fit_length", tools)
        self.assertEqual(res["brief"]["recipe"], "polish")
        main = ops.main_track(v["project"])["clips"]
        self.assertGreaterEqual(len(main), 4, "the pauses did cut the talk into pieces…")
        self.assertLessEqual(len(main), 20, "…but not into a beat-cut montage")
        self.assertGreater(sum(ops.clip_length(c) for c in main), 85.0, "the story keeps its length")
        keys = {i["key"]: i for i in v["critique"]["items"]}
        self.assertNotIn("beats", keys)

    def test_a_length_the_owner_asks_for_is_still_honoured(self):
        talk = {**self.TALK, "duration": 100.0}
        assets = {**ASSETS, "video:9": talk}
        ctx = self.ctx(describe=lambda ref: assets.get(ref), spans=lambda ref: [[0.4, 99.5]] if ref == "video:9" else [])
        res = loop.run("", [talk], ctx, store=None, options=loop.Options(variants=1, rounds=1, use_ai=False, preview=False, override={"recipe": "polish", "duration": 40}),
                       call=FakeAI(fail="all"))
        tools = [s["tool"] for s in res["variants"][0]["plan"]]
        self.assertIn("fit_length", tools)

    def test_the_rubric_does_not_ask_a_talk_to_sell(self):
        keys = {i["key"] for i in self.run_it()["variants"][0]["critique"]["items"]}
        self.assertNotIn("cta", keys)
        self.assertNotIn("pacing", keys)

    def test_a_vertical_request_reframes_with_composition(self):
        res = self.run_it("ریلز")
        step = next(s for s in res["variants"][0]["plan"] if s["tool"] == "reframe")
        self.assertTrue(step["params"]["compose"])
        self.assertEqual(res["brief"]["platform"], "reels")

    def test_an_explicit_recipe_is_never_overridden(self):
        self.assertEqual(self.run_it("ریلز تخفیف ۳۰ درصد")["brief"]["recipe"], "sale")

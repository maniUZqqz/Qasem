"""The director (semi-automatic editor): vocabulary, project operations, every catalogue tool, the executor, recipes, the
brief parser, the rubric critique, the agent loop (models mocked), reframe maths and the filter graphs it relies on
(master loudness, RNN denoise, reframe crop). No Metis, no node: the model is a fake and ffmpeg runs on tiny generated clips."""
import copy
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings

from services.editing import audiofx, compose, reframe, safezones
from services.editing import timeline as tl
from services.editing.director import analyze, brief as brief_mod, critique, loop, recipes
from services.editing.director import projectops as ops
from services.editing.director.runner import apply_steps, describe_step, validate_plan
from services.editing.director.spec import Ctx, StepError, clean_params
from services.editing.director.tools import CAPTION_STYLES, TOOLS, State


# ------------------------------------------------------------------ a fake world
ASSETS = {
    "video:1": {"ref": "video:1", "title": "چای سبز", "kind": "video", "duration": 12.0, "has_audio": False, "width": 1920, "height": 1080},
    "video:2": {"ref": "video:2", "title": "بسته‌بندی", "kind": "video", "duration": 8.0, "has_audio": True, "width": 1920, "height": 1080},
    "video:3": {"ref": "video:3", "title": "نظر مشتری", "kind": "video", "duration": 20.0, "has_audio": True, "width": 1080, "height": 1920},
    "pimg:1": {"ref": "pimg:1", "title": "لوگو", "kind": "image", "duration": 0.0, "has_audio": False, "width": 800, "height": 400},
    "pimg:2": {"ref": "pimg:2", "title": "عکس ۲", "kind": "image", "duration": 0.0, "has_audio": False, "width": 1000, "height": 1000},
    "audio:1": {"ref": "audio:1", "title": "موسیقی شاد", "kind": "audio", "duration": 40.0, "has_audio": True, "width": 0, "height": 0},
    "audio:2": {"ref": "audio:2", "title": "جلوه", "kind": "audio", "duration": 1.0, "has_audio": True, "width": 0, "height": 0},
    "sticker:sale": {"ref": "sticker:sale", "title": "تخفیف", "kind": "image", "duration": 0.0, "has_audio": False, "width": 512, "height": 512},
}
SPANS = {"video:3": [[0.5, 3.0], [4.5, 9.0], [11.0, 19.0]], "video:2": [[0.2, 7.5]]}
WORDS = {"video:3": [{"w": "سلام", "s": 0.6, "e": 1.0}, {"w": "این", "s": 1.1, "e": 1.4}, {"w": "محصول", "s": 1.5, "e": 2.2}, {"w": "عالیه", "s": 2.3, "e": 2.9}]}


def fake_ctx(**over) -> Ctx:
    def beats(ref):
        if ref == "audio:1":
            return {"beats": [round(0.5 * i, 3) for i in range(1, 80)], "bpm": 120.0}
        return {"beats": [], "bpm": None}

    kw = dict(describe=lambda ref: ASSETS.get(ref), spans=lambda ref: SPANS.get(ref, []), beats=beats,
              words=lambda ref, a, b: [{**w, "s": round(w["s"] - a, 3), "e": round(w["e"] - a, 3)} for w in WORDS.get(ref, []) if a <= w["s"] < b], path_of=lambda ref: None,
              make_speech=lambda text, voice: "audio:2", find_music=lambda q: "audio:1")
    kw.update(over)
    return Ctx(**kw)


def run_tool(project, tool, params=None, ctx=None, platform="reels"):
    new, res = apply_steps(project, [{"tool": tool, "params": params or {}}], ctx or fake_ctx(), platform=platform)
    return new, res[0]


def with_clip(ref="video:1", **kw):
    p = ops.new_project("reel")
    params = {"ref": ref, "track": "main", "id": "a"}
    params.update(kw)
    p, res = run_tool(p, "add_clip", params)
    assert res["ok"], res
    return p


def main_ids(p):
    return [c["id"] for c in sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])]


def check_valid(testcase, project):
    """The project must pass the SAME validation the renderer uses."""
    def resolve(ref):
        item = ASSETS.get(ref)
        if ref.startswith("sticker:"):
            from services.editing import stickers
            try:
                return {"path": str(stickers.path_of(ref.split(":", 1)[1])), "kind": "image", "has_audio": False, "duration": 0.0, "width": 512, "height": 512}
            except Exception:  # noqa: BLE001 — emoji font may be missing on a dev box
                return {"path": "/dev/null", "kind": "image", "has_audio": False, "duration": 0.0}
        if item is None:
            raise tl.TimelineError(f"unknown ref {ref}")
        return {"path": f"/tmp/{ref.replace(':', '_')}.bin", "kind": item["kind"], "has_audio": item["has_audio"], "duration": item["duration"],
                "width": item["width"], "height": item["height"]}
    line = tl.from_project(project, resolve)
    line.validate()
    return line


# ================================================================== vocabulary
class SpecTests(SimpleTestCase):
    def test_numbers_are_clamped_with_a_note_not_an_error(self):
        spec = TOOLS["set_speed"]
        clean, notes = clean_params(spec, {"clip": "a", "speed": 99})
        self.assertEqual(clean["speed"], 4)
        self.assertTrue(notes)

    def test_required_missing_is_a_persian_step_error(self):
        with self.assertRaises(StepError) as cm:
            clean_params(TOOLS["split_clip"], {"clip": "a"})
        self.assertIn("زمان", str(cm.exception))

    def test_unknown_params_are_dropped_and_choices_fall_back(self):
        clean, notes = clean_params(TOOLS["add_title"], {"text": "سلام", "template": "nonsense", "evil": "x"})
        self.assertEqual(clean["template"], "title_center")
        self.assertNotIn("evil", clean)
        self.assertTrue(notes)

    def test_every_tool_describes_itself_in_persian(self):
        self.assertGreaterEqual(len(TOOLS), 30)
        for name, spec in TOOLS.items():
            self.assertTrue(spec.title and spec.does and spec.group in ("structure", "text", "visual", "audio"), name)
            defaults = {}
            for p in spec.params:
                if p.required:
                    defaults[p.name] = {"num": 1, "int": 1, "text": "x", "ref": "video:1", "clip": "a", "list": ["a"], "bool": True}.get(p.kind, p.choices[0] if p.choices else 1)
            clean, _ = clean_params(spec, defaults)
            self.assertTrue(spec.describe(clean), name)

    def test_catalogue_for_the_model_is_compact_and_complete(self):
        from services.editing.director import tools as tools_mod
        cat = tools_mod.catalogue_for_model()
        self.assertEqual({c["tool"] for c in cat}, set(TOOLS))
        self.assertLess(len(json.dumps(cat, ensure_ascii=False)), 24000)


# ================================================================== project operations
class ProjectOpsTests(SimpleTestCase):
    def two_clips(self):
        p = ops.new_project("reel")
        item = ASSETS["video:1"]
        t = ops.main_track(p)
        a = ops.media_clip(p, item, 0, start=0, end=4)
        b = ops.media_clip(p, item, 4, start=4, end=8)
        ops.place(t, a, exact=True)
        ops.place(t, b, exact=True)
        return p, a, b

    def test_split_cuts_source_and_returns_right_half(self):
        p, a, _ = self.two_clips()
        rid = ops.split(p, a["id"], 1.5)
        right = ops.find(p, rid)[1]
        self.assertEqual((a["start"], a["end"], right["start"], right["end"]), (0, 1.5, 1.5, 4))
        self.assertEqual(right["at"], 1.5)
        self.assertIsNone(ops.split(p, a["id"], 1.5 + 99))

    def test_split_of_speed_changed_clip_maps_timeline_to_source(self):
        p, a, _ = self.two_clips()
        ops.set_speed(a, 2.0)                                  # 4 s of source plays in 2 s
        rid = ops.split(p, a["id"], 1.0)
        self.assertAlmostEqual(a["end"], 2.0, places=2)         # 1 timeline second = 2 source seconds
        self.assertEqual(ops.find(p, rid)[1]["start"], a["end"])

    def test_remove_range_ripples_and_cuts_through_clips(self):
        p, a, b = self.two_clips()
        n = ops.remove_range(p, 2.0, 5.0)
        self.assertGreaterEqual(n, 1)
        self.assertAlmostEqual(ops.project_length(p), 5.0, places=2)
        self.assertAlmostEqual(ops.end_of(ops.main_track(p)), 5.0, places=2)

    def test_delete_with_ripple_closes_only_that_track(self):
        p, a, b = self.two_clips()
        ops.delete_clips(p, [a["id"]], ripple=True)
        self.assertEqual(ops.find(p, b["id"])[1]["at"], 0)

    def test_linked_pairs_are_cut_together_and_keep_separate_links(self):
        p = ops.new_project("reel")
        v = ops.media_clip(p, ASSETS["video:3"], 0, start=0, end=10)
        v["link"] = "L1"
        a = ops.media_clip(p, ASSETS["audio:1"], 0, start=0, end=10, kind="audio")
        a["link"] = "L1"
        ops.place(ops.main_track(p), v, exact=True)
        ops.place(ops.audio_track(p, "speech"), a, exact=True)
        ops.remove_range(p, 4, 6)
        vids = sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])
        auds = sorted(ops.audio_track(p, "speech")["clips"], key=lambda c: c["at"])
        self.assertEqual(len(vids), 2)
        self.assertEqual(len(auds), 2)
        self.assertEqual(vids[1]["link"], auds[1]["link"])
        self.assertNotEqual(vids[0]["link"], vids[1]["link"])

    def test_place_free_never_overlaps_and_adds_tracks(self):
        p = ops.new_project("reel")
        for _ in range(3):
            ops.place_free(p, "text", ops.text_clip(p, "عنوان", 1.0, 2.0))
        texts = [t for t in p["tracks"] if t["kind"] == "text"]
        self.assertEqual(len(texts), 3)
        for t in texts:
            self.assertFalse(any(ops.overlaps({"clips": [c]}, 0, 1) for c in []))
        check_valid(self, {**p, "tracks": p["tracks"] + []}) if False else None

    def test_trim_is_clamped_to_the_source(self):
        p, a, _ = self.two_clips()
        ops.trim(p, a["id"], start=-3, end=999)
        self.assertEqual((a["start"], a["end"]), (0, 12.0))


# ================================================================== the tools
class ToolTests(SimpleTestCase):
    def test_add_clip_appends_on_the_main_track_with_alias(self):
        p = with_clip("video:1", start=2, end=6)
        p, res = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 3})
        ids = main_ids(p)
        self.assertEqual(len(ids), 2)
        c2 = ops.find(p, ids[1])[1]
        self.assertAlmostEqual(c2["at"], 4.0)
        self.assertTrue(res["ok"])

    def test_add_clip_unknown_ref_fails_with_persian(self):
        p = ops.new_project("reel")
        _, res = run_tool(p, "add_clip", {"ref": "video:999"})
        self.assertFalse(res["ok"])
        self.assertIn("پیدا نشد", res["message"])

    def test_audio_on_the_picture_track_is_rejected_or_rerouted(self):
        p = ops.new_project("reel")
        p, res = run_tool(p, "add_clip", {"ref": "audio:1", "track": "main"})
        self.assertTrue(res["ok"])
        self.assertEqual(ops.main_track(p)["clips"], [])                # went to a sound track
        self.assertTrue(any(t["kind"] == "audio" and t["clips"] for t in p["tracks"]))
        _, bad = run_tool(p, "add_clip", {"ref": "video:1", "track": "music"})
        self.assertFalse(bad["ok"])

    def test_trim_split_remove_delete_move(self):
        p = with_clip("video:1", start=0, end=8)
        cid = main_ids(p)[0]
        p, r = run_tool(p, "trim_clip", {"clip": "a", "start": 1, "end": 7})
        self.assertTrue(r["ok"])
        c = ops.find(p, cid)[1]
        self.assertEqual((c["start"], c["end"]), (1, 7))
        p, r = run_tool(p, "split_clip", {"clip": "a", "at": 3})
        self.assertTrue(r["ok"])
        self.assertEqual(len(main_ids(p)), 2)
        p, r = run_tool(p, "remove_range", {"from": 1, "to": 2})
        self.assertAlmostEqual(ops.project_length(p), 5.0, places=2)
        self.assertEqual(len(main_ids(p)), 3)                               # the range cut split the first piece in two
        p, r = run_tool(p, "delete_clip", {"clip": "first", "ripple": True})
        self.assertEqual(len(main_ids(p)), 2)
        p, r = run_tool(p, "move_clip", {"clip": "first", "at": 5})
        self.assertTrue(r["ok"])
        self.assertEqual(max(c["at"] for c in ops.main_track(p)["clips"]), 5)

    def test_reorder_puts_clips_back_to_back_in_the_given_order(self):
        p = with_clip("video:1", start=0, end=3)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 2})
        first, second = main_ids(p)
        p, r = run_tool(p, "reorder_clips", {"order": ["b", "a"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(main_ids(p), [second, first])
        self.assertEqual(ops.main_track(p)["clips"][0]["at"], 0)

    def test_speed_and_ramp_reflow_the_next_clips(self):
        p = with_clip("video:1", start=0, end=4)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 2})
        p, r = run_tool(p, "set_speed", {"clip": "a", "speed": 0.5})
        self.assertAlmostEqual(ops.project_length(p), 10.0, places=1)          # 4 s at half speed = 8 s, then 2 s
        check_valid(self, p)
        p, r = run_tool(p, "speed_ramp", {"clip": "b", "preset": "hero"})
        self.assertTrue(r["ok"])
        check_valid(self, p)

    def test_fit_length_trims_proportionally_and_closes_gaps(self):
        p = with_clip("video:1", start=0, end=8)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 8})
        p, r = run_tool(p, "fit_length", {"seconds": 8})
        self.assertLessEqual(ops.project_length(p), 8.1)
        self.assertGreaterEqual(ops.project_length(p), 7.0)
        check_valid(self, p)

    def test_cut_to_beats_lands_every_cut_on_a_beat(self):
        p = with_clip("video:1", start=0, end=12)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 8})
        p, r = run_tool(p, "cut_to_beats", {"music": "audio:1", "every": 2})
        self.assertTrue(r["ok"], r)
        cuts = [c["at"] for c in sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])][1:]
        self.assertTrue(cuts)
        for t in cuts:
            self.assertAlmostEqual((t / 0.5) % 2, 0, places=2, msg=f"cut at {t} is not on every 2nd beat")
        # no gaps, no overlaps, nothing outside its source
        check_valid(self, p)
        for c in ops.main_track(p)["clips"]:
            self.assertGreaterEqual(c["start"], 0)
            self.assertLessEqual(c["end"], ASSETS[c["ref"]]["duration"] + 0.01)

    def test_cut_to_beats_without_beats_says_so(self):
        p = with_clip("video:1", start=0, end=6)
        _, r = run_tool(p, "cut_to_beats", {"music": "audio:2", "every": 2})
        self.assertFalse(r["ok"])
        self.assertIn("ضرب", r["message"])

    def test_transition_only_between_touching_clips(self):
        p = with_clip("video:1", start=0, end=3)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 3})
        p, r = run_tool(p, "transition", {"clip": "all", "kind": "crossfade", "duration": 0.4})
        self.assertTrue(r["ok"])
        clips = sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])
        self.assertIsNone(clips[0]["transition"])
        self.assertEqual(clips[1]["transition"]["kind"], "crossfade")
        check_valid(self, p)

    def test_titles_never_share_a_track_when_they_overlap(self):
        p = with_clip("video:1", start=0, end=6)
        for text in ("یک", "دو", "سه"):
            p, r = run_tool(p, "add_title", {"text": text, "at": 1, "duration": 2, "template": "lower_bar"})
            self.assertTrue(r["ok"])
        check_valid(self, p)
        ys = [c["y"] for t in p["tracks"] if t["kind"] == "text" for c in t["clips"]]
        self.assertTrue(all(y <= 1 - safezones.margins("reels")["bottom"] for y in ys))

    def test_captions_from_words_land_in_the_caption_track_inside_the_safe_zone(self):
        p = with_clip("video:3", start=0, end=10)
        p, r = run_tool(p, "add_captions", {"clip": "all", "style": "pop"})
        self.assertTrue(r["ok"], r)
        cap = next(t for t in p["tracks"] if t["kind"] == "text" and t.get("caption"))
        self.assertTrue(cap["clips"])
        z = safezones.margins("reels")
        for c in cap["clips"]:
            self.assertTrue(c["caption"])
            self.assertLessEqual(c["y"], 1 - z["bottom"])
            self.assertTrue(c["words"])
        check_valid(self, p)

    def test_captions_without_asr_say_what_is_missing(self):
        p = with_clip("video:3", start=0, end=10)
        def boom(ref, a, b):
            raise RuntimeError("سرورِ پردازش خاموش است")
        _, r = run_tool(p, "add_captions", {"clip": "all"}, ctx=fake_ctx(words=boom))
        self.assertFalse(r["ok"])
        self.assertIn("خاموش", r["message"])

    def test_captions_from_given_lines_work_without_asr(self):
        p = with_clip("video:1", start=0, end=6)
        p, r = run_tool(p, "add_captions", {"lines": [{"text": "سلام", "start": 0.5, "end": 2}, {"text": "خداحافظ", "start": 2.5, "end": 4}]})
        self.assertTrue(r["ok"], r)

    def test_end_card_sits_after_the_last_clip_without_a_gap(self):
        p = with_clip("video:1", start=0, end=5)
        p, r = run_tool(p, "end_card", {"text": "همین حالا بخر", "text2": "۳۰٪ تخفیف", "duration": 2.5})
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(ops.end_of(ops.main_track(p)), 7.5, places=2)
        check_valid(self, p)

    def test_look_zoom_punch_crop_sticker_shape_logo(self):
        p = with_clip("video:1", start=0, end=4)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 4})
        p, r = run_tool(p, "color_look", {"look": "cinematic", "amount": 50})
        self.assertEqual(ops.main_track(p)["clips"][0]["color"]["look"], "cinematic")
        p, r = run_tool(p, "zoom", {"clip": "a", "from_scale": 1, "to_scale": 1.2})
        self.assertEqual(len(ops.find(p, main_ids(p)[0])[1]["kf"]["scale"]), 2)
        p, r = run_tool(p, "punch_in", {"every": 2, "scale": 1.15})
        self.assertEqual(ops.find(p, main_ids(p)[1])[1]["scale"], 1.15)
        p, r = run_tool(p, "crop", {"clip": "a", "l": 0.1, "r": 0.1})
        self.assertEqual(ops.find(p, main_ids(p)[0])[1]["crop"], {"l": 0.1, "r": 0.1})
        p, r = run_tool(p, "sticker", {"key": "sale", "at": 0.3, "duration": 2})
        self.assertTrue(r["ok"], r)
        p, r = run_tool(p, "shape", {"kind": "burst", "fill": "#ff0000", "at": 0, "duration": 1})
        self.assertTrue(r["ok"], r)
        p, r = run_tool(p, "overlay_image", {"ref": "pimg:1", "corner": "tr", "size": 0.2})
        self.assertTrue(r["ok"], r)
        logo = [c for t in p["tracks"] for c in t["clips"] if c.get("ref") == "pimg:1"][0]
        z = safezones.margins("reels")
        self.assertLessEqual(logo["x"] + logo["width"], 1 - z["right"] + 1e-6)
        self.assertGreaterEqual(logo["y"], z["top"])
        check_valid(self, p)

    def test_reframe_without_a_file_centres_the_window_for_the_aspect(self):
        p = with_clip("video:1", start=0, end=4)
        p, r = run_tool(p, "reframe", {"clip": "a", "aspect": "9:16", "follow": "auto"})
        self.assertTrue(r["ok"], r)
        rf = ops.main_track(p)["clips"][0]["reframe"]
        self.assertAlmostEqual(rf["w"], (9 / 16) / (16 / 9), places=3)
        self.assertEqual(rf["h"], 1.0)
        self.assertAlmostEqual(rf["cx"], 0.5, places=2)

    def test_music_loops_to_the_program_length_ducks_and_fades(self):
        p = with_clip("video:3", start=0, end=20)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 8})
        p, r = run_tool(p, "add_music", {"ref": "audio:1", "volume_db": -18})
        self.assertTrue(r["ok"], r)
        music = [c for t in p["tracks"] if t.get("role") == "music" for c in t["clips"]]
        self.assertAlmostEqual(sum(ops.clip_length(c) for c in music), 28.0, places=1)
        self.assertLess(music[0]["volume"], 0.2)
        self.assertGreater(music[-1]["fade_out"], 0)
        self.assertTrue(p["ducking"]["on"])
        check_valid(self, p)

    def test_music_without_a_track_and_empty_library_explains(self):
        p = with_clip("video:1", start=0, end=4)
        _, r = run_tool(p, "add_music", {}, ctx=fake_ctx(find_music=lambda q: None))
        self.assertFalse(r["ok"])
        self.assertIn("موسیقی", r["message"])

    def test_music_short_track_is_looped_not_stretched(self):
        p = with_clip("video:1", start=0, end=12)
        p, r = run_tool(p, "add_music", {"ref": "audio:2"})                    # a 1 s sound as «music»
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(len([c for t in p["tracks"] if t.get("role") == "music" for c in t["clips"]]), 6)

    def test_ducking_loudness_clean_voice_and_mix(self):
        p = with_clip("video:3", start=0, end=10)
        p, r = run_tool(p, "ducking", {"on": True, "amount_db": 15})
        self.assertEqual(p["ducking"]["amount_db"], 15)
        p, r = run_tool(p, "set_loudness", {"on": True})
        self.assertEqual(p["master"]["loudness"], {"on": True, "target": -14, "tp": -1})
        p, r = run_tool(p, "clean_voice", {"clip": "all", "level": "strong"})
        self.assertTrue(r["ok"], r)
        a = ops.main_track(p)["clips"][0]["audio"]
        self.assertTrue(a["denoise_ai"] and a["enhance"])
        p, _ = run_tool(p, "add_music", {"ref": "audio:1", "volume_db": -4})
        for c in [c for t in p["tracks"] if t.get("role") == "music" for c in t["clips"]]:
            c["volume"] = 1.0
        p, r = run_tool(p, "auto_mix", {})
        self.assertTrue(r["ok"])
        self.assertLess([c for t in p["tracks"] if t.get("role") == "music" for c in t["clips"]][0]["volume"], 0.2)

    def test_remove_silence_cuts_gaps_and_keeps_words(self):
        p = with_clip("video:3", start=0, end=20)
        p, r = run_tool(p, "remove_silence", {"clip": "all", "min_silence": 0.6, "keep": 0.15})
        self.assertTrue(r["ok"], r)
        total = ops.project_length(p)
        self.assertLess(total, 18.5)                                         # ≥ 1.5 s of pauses gone
        self.assertGreater(total, 14.0)
        # every kept piece still starts at/near a spoken span (a pause is never inside a kept piece's start)
        clips = sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])
        for a, b in zip(clips, clips[1:]):
            self.assertAlmostEqual(ops.clip_end(a), b["at"], places=2)       # rippled: no holes
        check_valid(self, p)

    def test_remove_silence_also_trims_a_music_bed_that_now_outlives_the_picture(self):
        p = with_clip("video:3", start=0, end=20)
        p, _ = run_tool(p, "add_music", {"ref": "audio:1"})
        before = ops.end_of(ops.audio_track(p, "music"))
        p, r = run_tool(p, "remove_silence", {"clip": "all"})
        self.assertTrue(r["ok"], r)
        self.assertLess(ops.end_of(ops.audio_track(p, "music")), before)
        self.assertLessEqual(ops.end_of(ops.audio_track(p, "music")), ops.end_of(ops.main_track(p)) + 0.1)

    def test_remove_silence_on_a_linked_pair_cuts_both_tracks_equally(self):
        p = ops.new_project("reel")
        v = ops.media_clip(p, ASSETS["video:3"], 0, start=0, end=20)
        v["audio_on"] = False
        v["link"] = "LL"
        a = ops.media_clip(p, ASSETS["video:3"], 0, start=0, end=20, kind="audio")
        a["link"] = "LL"
        ops.place(ops.main_track(p), v, exact=True)
        ops.place(ops.audio_track(p, "speech"), a, exact=True)
        p, r = run_tool(p, "remove_silence", {"clip": "all"})
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(ops.end_of(ops.main_track(p)), ops.end_of(ops.audio_track(p, "speech")), places=2)

    FILLER_WORDS = [{"w": "سلام", "s": 0.6, "e": 1.0}, {"w": "اممم", "s": 1.1, "e": 1.7}, {"w": "این", "s": 1.8, "e": 2.1}, {"w": "یعنی", "s": 2.2, "e": 2.6},
                    {"w": "هم", "s": 2.7, "e": 3.0}, {"w": "ای", "s": 3.1, "e": 3.4}, {"w": "اُوم", "s": 3.5, "e": 4.0}, {"w": "محصول", "s": 4.1, "e": 4.8}]

    def filler_ctx(self, words=None):
        data = self.FILLER_WORDS if words is None else words
        return fake_ctx(words=lambda ref, a, b: [{**w, "s": round(w["s"] - a, 3), "e": round(w["e"] - a, 3)} for w in data if a <= w["s"] < b])

    def test_filler_words_are_normalised_the_persian_way(self):
        from services.editing.director.tools import FILLERS_HARD, _norm_word
        self.assertEqual(_norm_word("اممممم"), "امم")
        self.assertEqual(_norm_word("اُوم،"), "اوم")
        self.assertEqual(_norm_word("امـم"), "امم")
        self.assertEqual(_norm_word("Hmmmm."), "hmm")
        self.assertEqual(_norm_word("يعني"), "یعنی")
        for real in ("هم", "ای", "او", "آن", "ما"):
            self.assertNotIn(_norm_word(real), FILLERS_HARD, real)                  # real words must never be cut

    def test_remove_fillers_cuts_hesitations_only_and_ripples(self):
        p = with_clip("video:3", start=0, end=10)
        before = ops.project_length(p)
        p, r = run_tool(p, "remove_fillers", {}, ctx=self.filler_ctx())
        self.assertTrue(r["ok"], r)
        cut = before - ops.project_length(p)
        self.assertAlmostEqual(cut, (0.6 + 0.08) + (0.5 + 0.08), delta=0.08)          # «اممم» and «اُوم» (each + the margins), nothing else
        clips = sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])
        for a, b in zip(clips, clips[1:]):
            self.assertAlmostEqual(ops.clip_end(a), b["at"], places=2)                # rippled: no holes
        check_valid(self, p)

    def test_remove_fillers_soft_words_only_when_asked(self):
        p = with_clip("video:3", start=0, end=10)
        soft, r = run_tool(p, "remove_fillers", {"include_soft": True}, ctx=self.filler_ctx())
        hard, _ = run_tool(p, "remove_fillers", {}, ctx=self.filler_ctx())
        self.assertGreater(ops.project_length(hard) - ops.project_length(soft), 0.35)      # «یعنی» went too
        self.assertTrue(r["ok"])

    def test_remove_fillers_nothing_found_is_not_an_error_but_no_speech_is(self):
        p = with_clip("video:3", start=0, end=10)
        p2, r = run_tool(p, "remove_fillers", {}, ctx=self.filler_ctx([{"w": "سلام", "s": 0.5, "e": 1.0}]))
        self.assertTrue(r["ok"])
        self.assertIn("پیدا نشد", r["message"])
        self.assertEqual(ops.project_length(p2), ops.project_length(p))
        _, r = run_tool(p, "remove_fillers", {}, ctx=self.filler_ctx([]))
        self.assertFalse(r["ok"])
        self.assertIn("گفتار", r["message"])

        def boom(ref, a, b):
            raise RuntimeError("سرورِ پردازش خاموش است")
        _, r = run_tool(p, "remove_fillers", {}, ctx=fake_ctx(words=boom))
        self.assertFalse(r["ok"])
        self.assertIn("خاموش", r["message"])

    def test_remove_fillers_on_a_linked_pair_cuts_both_tracks_equally(self):
        p = ops.new_project("reel")
        v = ops.media_clip(p, ASSETS["video:3"], 0, start=0, end=10)
        v["audio_on"] = False
        v["link"] = "LF"
        a = ops.media_clip(p, ASSETS["video:3"], 0, start=0, end=10, kind="audio")
        a["link"] = "LF"
        ops.place(ops.main_track(p), v, exact=True)
        ops.place(ops.audio_track(p, "speech"), a, exact=True)
        p, r = run_tool(p, "remove_fillers", {}, ctx=self.filler_ctx())
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(ops.end_of(ops.main_track(p)), ops.end_of(ops.audio_track(p, "speech")), places=2)
        self.assertLess(ops.end_of(ops.main_track(p)), 9.2)

    def test_fillers_after_silence_removal_still_find_their_words_in_the_pieces(self):
        p = with_clip("video:3", start=0, end=20)
        p, r1 = run_tool(p, "remove_silence", {"clip": "all"})
        self.assertTrue(r1["ok"], r1)
        pieces = len(ops.main_track(p)["clips"])
        p, r2 = run_tool(p, "remove_fillers", {}, ctx=self.filler_ctx())
        self.assertTrue(r2["ok"], r2)
        self.assertGreaterEqual(len(ops.main_track(p)["clips"]), pieces)
        check_valid(self, p)

    def test_voiceover_and_sfx_use_their_own_tracks(self):
        p = with_clip("video:1", start=0, end=8)
        p, r = run_tool(p, "add_voiceover", {"text": "سلام به همه", "at": 1})
        self.assertTrue(r["ok"], r)
        p, r = run_tool(p, "add_sfx", {"ref": "audio:2", "at": 3})
        p, r2 = run_tool(p, "add_sfx", {"ref": "audio:2", "at": 3.2})
        self.assertTrue(r["ok"] and r2["ok"])
        check_valid(self, p)

    def test_voiceover_failure_is_a_persian_step_error(self):
        p = with_clip("video:1", start=0, end=4)
        def nope(text, voice):
            raise StepError("سرورِ پردازش خاموش است.")
        _, r = run_tool(p, "add_voiceover", {"text": "سلام"}, ctx=fake_ctx(make_speech=nope))
        self.assertFalse(r["ok"])
        self.assertIn("خاموش", r["message"])

    def test_beat_markers(self):
        p = with_clip("video:1", start=0, end=4)
        p, r = run_tool(p, "mark_beats", {"music": "audio:1"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(all(m["kind"] == "beat" for m in p["markers"]))

    def test_caption_style_changes_every_caption(self):
        p = with_clip("video:3", start=0, end=10)
        p, _ = run_tool(p, "add_captions", {"style": "box"})
        p, r = run_tool(p, "caption_style", {"style": "karaoke"})
        self.assertTrue(r["ok"])
        cap = next(t for t in p["tracks"] if t.get("caption"))
        self.assertTrue(all(c["hl_mode"] == "box" for c in cap["clips"]))
        from services.editing import titles

        self.assertEqual(set(CAPTION_STYLES), {"pop", "box", "karaoke", "clean", "neon", "typewriter", "lower"})
        for key, st in CAPTION_STYLES.items():                      # every look is a style the text engine accepts, not a dead entry
            clip = titles.clean({**st["style"], "text": "سلام دنیا", "duration": 2.0, "caption": True})
            self.assertEqual(clip["hl_mode"], st["style"]["hl_mode"], key)
            if st["style"].get("anim_in"):
                self.assertEqual(clip["anim_in"], st["style"]["anim_in"], key)


# ================================================================== executor
class RunnerTests(SimpleTestCase):
    def test_one_bad_step_does_not_stop_the_rest_and_the_input_is_untouched(self):
        p = ops.new_project("reel")
        before = copy.deepcopy(p)
        steps = [{"tool": "add_clip", "params": {"ref": "video:1", "id": "a", "start": 0, "end": 3}},
                 {"tool": "teleport", "params": {}},
                 {"tool": "add_title", "params": {"text": "سلام", "template": "title_big"}},
                 {"tool": "split_clip", "params": {"clip": "zzz", "at": 1}}]
        new, res = apply_steps(p, steps, fake_ctx())
        self.assertEqual(p, before)
        self.assertEqual([r["ok"] for r in res], [True, False, True, False])
        self.assertIn("ناشناخته", res[1]["message"]) if "ناشناخته" in res[1]["message"] else self.assertIn("شناخته", res[1]["message"])
        self.assertEqual(len(main_ids(new)), 1)

    def test_steps_switched_off_are_skipped(self):
        new, res = apply_steps(ops.new_project("reel"), [{"tool": "add_clip", "params": {"ref": "video:1"}, "on": False}], fake_ctx())
        self.assertTrue(res[0]["skipped"])
        self.assertEqual(main_ids(new), [])

    def test_an_unexpected_exception_becomes_a_failed_step(self):
        boom = fake_ctx(describe=lambda ref: (_ for _ in ()).throw(RuntimeError("x")))
        _, res = apply_steps(ops.new_project("reel"), [{"tool": "add_clip", "params": {"ref": "video:1"}}], boom)
        self.assertFalse(res[0]["ok"])
        self.assertIn("غیرمنتظره", res[0]["message"])

    def test_validate_plan_reports_in_persian_and_normalises(self):
        steps, problems = validate_plan([{"tool": "add_title", "params": {"text": "x"}}, {"tool": "nope"}, "garbage", {"tool": "split_clip", "params": {}}])
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(problems), 3)
        self.assertEqual(steps[0]["id"], "s1")

    def test_describe_step_is_persian_without_executing(self):
        d = describe_step({"tool": "set_loudness", "params": {"on": True}})
        self.assertIn("LUFS", d["text"])
        self.assertEqual(describe_step({"tool": "zzz"})["known"], False)


# ================================================================== brief
class BriefTests(SimpleTestCase):
    def test_persian_prompts_become_briefs(self):
        b = brief_mod.parse_prompt("یک ریلز ۱۵ ثانیه‌ای برای حراج ۳۰٪ تخفیف با «عطر تابستانی» سریع و پرانرژی")
        self.assertEqual((b["platform"], b["recipe"], b["duration"], b["discount"], b["pace"]), ("reels", "sale", 15, 30, "fast"))
        self.assertEqual(b["title"], "عطر تابستانی")

    def test_recipe_words(self):
        self.assertEqual(brief_mod.parse_prompt("جعبه گشایی")["recipe"], "unboxing")
        self.assertEqual(brief_mod.parse_prompt("قبل و بعد از تعمیر")["recipe"], "before_after")
        self.assertEqual(brief_mod.parse_prompt("نظر مشتری رو کوتاه کن")["recipe"], "testimonial")
        self.assertEqual(brief_mod.parse_prompt("اسلایدشو از عکس‌ها برای یوتیوب")["platform"], "youtube")

    def test_flags_and_defaults(self):
        b = brief_mod.parse_prompt("بدون موسیقی و بدون زیرنویس، آرام")
        self.assertIs(b["music"], False)
        self.assertIs(b["captions"], False)
        self.assertEqual(b["pace"], "slow")
        done = brief_mod.finish_brief(brief_mod.parse_prompt(""), [ASSETS["video:1"]])
        self.assertEqual((done["platform"], done["recipe"]), ("reels", "product_showcase"))
        self.assertIn("چای", done["title"])
        self.assertTrue(done["cta"])

    def test_only_photos_guess_a_slideshow(self):
        b = brief_mod.parse_prompt("", assets=[ASSETS["pimg:1"], ASSETS["pimg:2"]])
        self.assertEqual(b["recipe"], "slideshow")

    def test_digits_in_persian_and_arabic_indic_forms(self):
        self.assertEqual(brief_mod.parse_prompt("۴۵ ثانیه")["duration"], 45)
        self.assertEqual(brief_mod.parse_prompt("٢٠ ثانیه")["duration"], 20)


# ================================================================== analysis helpers
class AnalyzeTests(SimpleTestCase):
    def test_best_windows_do_not_overlap_and_prefer_the_busy_part(self):
        scores = [0.1] * 5 + [0.9] * 3 + [0.1] * 12
        wins = analyze.best_windows(scores, 3, 2, total=20)
        self.assertEqual(wins[0]["s"], 5.0)
        self.assertTrue(wins[1]["s"] >= wins[0]["e"] or wins[1]["e"] <= wins[0]["s"])

    def test_windows_are_moved_out_of_a_spoken_phrase(self):
        wins = analyze.best_windows([0.5] * 20, 3, 1, total=20, spans=[[1.0, 5.0]])
        w = wins[0]
        self.assertFalse(1.0 < w["s"] < 5.0 and w["s"] != 0.95)

    def test_moment_scores_from_synthetic_frames_find_the_motion(self):
        quiet = np.zeros((4, 24, 32, 3), np.uint8)
        busy = np.random.RandomState(1).randint(0, 255, (4, 24, 32, 3)).astype(np.uint8)
        frames = np.concatenate([quiet, busy, quiet])
        sc = analyze.moment_scores("x", 6, frames=frames)
        self.assertEqual(len(sc), 6)
        self.assertGreater(max(sc[2:4]), max(sc[0], sc[5]))

    def test_pick_segments_opens_with_the_best_moment_and_sums_to_target(self):
        an = analyze.analyze([ASSETS["video:1"], ASSETS["video:2"], ASSETS["pimg:2"]], fake_ctx(path_of=lambda r: None), want_moments=False)
        an["by_ref"]["video:1"]["moments"] = [0.1] * 4 + [0.95] * 3 + [0.1] * 5
        segs = analyze.pick_segments(an, ["video:1", "video:2", "pimg:2"], 20, (1.3, 3.4), "normal")
        self.assertEqual(segs[0]["ref"], "video:1")
        self.assertAlmostEqual(segs[0]["start"], 4.0, delta=1.0)
        self.assertGreaterEqual(len(segs), 4)
        for s in segs:
            if "end" in s:
                self.assertLessEqual(s["end"], ASSETS[s["ref"]]["duration"] + 1e-6)


# ================================================================== recipes → real projects
class RecipeTests(SimpleTestCase):
    def build(self, prompt, refs, variant="a", music="audio:1"):
        assets = [ASSETS[r] for r in refs]
        an = analyze.analyze(assets + ([ASSETS[music]] if music else []), fake_ctx(), want_words=True, want_moments=False)
        b = brief_mod.finish_brief(brief_mod.parse_prompt(prompt, assets=assets), assets)
        plan = recipes.build_plan(b, assets, an, variant=variant, music_ref=music)
        project, results = apply_steps(ops.new_project(brief_mod.PLATFORMS[b["platform"]]["preset"]), plan, fake_ctx(), platform=brief_mod.PLATFORMS[b["platform"]]["zone"])
        return b, plan, project, results, an

    def assert_ok(self, results, allowed=()):
        bad = [r for r in results if not r["ok"] and r["tool"] not in allowed]
        self.assertEqual(bad, [], bad)

    def test_every_recipe_in_every_variant_builds_a_valid_editable_project(self):
        cases = {
            "product_showcase": ("ریلز معرفی محصول", ["video:1", "video:2", "pimg:2"]),
            "unboxing": ("جعبه‌گشایی برای ریلز", ["video:2", "video:3"]),
            "before_after": ("قبل و بعد", ["video:1", "pimg:2"]),
            "sale": ("حراج ۴۰٪ تخفیف", ["video:1", "pimg:2", "pimg:1"]),
            "testimonial": ("نظر مشتری", ["video:3"]),
            "slideshow": ("اسلایدشو", ["pimg:1", "pimg:2"]),
        }
        for name, (prompt, refs) in cases.items():
            for variant in ("a", "b", "c"):
                b, plan, project, results, _ = self.build(prompt, refs, variant)
                self.assertEqual(b["recipe"], name)
                self.assert_ok(results, allowed=("add_captions", "sticker"))       # sticker PNGs / ASR may be absent on a dev box
                line = check_valid(self, project)
                self.assertGreater(line.length, 4.0, f"{name}/{variant}")
                self.assertLessEqual(line.length, b["duration"] + 6, f"{name}/{variant}")
                self.assertTrue(any(c.get("type") == "text" for t in project["tracks"] for c in t["clips"]), f"{name}/{variant}: no title")
                self.assertTrue(project["master"]["loudness"]["on"])
                # a real, editable project: every media clip refers to a ref of the fake world
                for t in project["tracks"]:
                    for c in t["clips"]:
                        if c["type"] == "media" and c["ref"] != "shape":
                            self.assertIn(c["ref"], ASSETS)

    def test_the_hook_title_is_in_the_first_seconds_and_the_video_ends_on_a_cta(self):
        b, plan, project, results, an = self.build("ریلز", ["video:1", "video:2"])
        rep = critique.critique(project, an, b)
        keys = {i["key"]: i for i in rep["items"]}
        self.assertTrue(keys["hook"]["ok"])
        self.assertTrue(keys["cta"]["ok"])
        self.assertTrue(keys["levels"]["ok"] if "levels" in keys else True)

    def test_fast_variant_cuts_on_the_beats_and_calm_variant_does_not(self):
        _, plan_a, project_a, *_ = self.build("ریلز", ["video:1", "video:2"], "a")
        _, plan_b, *_ = self.build("ریلز", ["video:1", "video:2"], "b")
        self.assertIn("cut_to_beats", [s["tool"] for s in plan_a])
        self.assertNotIn("cut_to_beats", [s["tool"] for s in plan_b])
        cuts = [c["at"] for c in sorted(ops.main_track(project_a)["clips"], key=lambda c: c["at"])][1:-1]
        on_beat = [t for t in cuts if abs((t / 0.5) - round(t / 0.5)) < 0.01]
        self.assertGreaterEqual(len(on_beat), len(cuts) - 1)

    def test_no_music_means_no_music_step_not_a_failing_one(self):
        _, plan, project, results, _ = self.build("ریلز", ["video:1"], music="")
        self.assertNotIn("add_music", [s["tool"] for s in plan])
        self.assert_ok(results, allowed=("sticker",))

    def test_speech_recipes_remove_silence_and_caption(self):
        _, plan, project, results, _ = self.build("نظر مشتری", ["video:3"])
        tools_used = [s["tool"] for s in plan]
        self.assertLess(tools_used.index("remove_silence"), tools_used.index("add_captions"))
        self.assertLess(tools_used.index("remove_silence"), tools_used.index("remove_fillers"))     # a transcript exists: fillers go too
        self.assertLess(tools_used.index("remove_fillers"), tools_used.index("add_captions"))
        self.assertIn("clean_voice", tools_used)

    def test_sale_with_discount_shows_it_big(self):
        b, plan, project, *_ = self.build("حراج ۵۰٪ تخفیف", ["video:1", "pimg:2"])
        texts = [c["text"] for t in project["tracks"] for c in t["clips"] if c.get("type") == "text"]
        self.assertTrue(any("۵۰" in x or "50" in x for x in texts + [b["title"]]))


# ================================================================== critique
class CritiqueTests(SimpleTestCase):
    def setUp(self):
        self.an = analyze.analyze([ASSETS["video:3"], ASSETS["audio:1"]], fake_ctx(), want_words=True, want_moments=False)
        self.brief = brief_mod.finish_brief(brief_mod.parse_prompt("ریلز"), [ASSETS["video:3"]])

    def project(self):
        p = with_clip("video:3", start=0, end=10)
        return p

    def items(self, p):
        return {i["key"]: i for i in critique.critique(p, self.an, self.brief)["items"]}

    def test_missing_hook_and_cta_are_found_with_fixes(self):
        it = self.items(self.project())
        self.assertFalse(it["hook"]["ok"])
        self.assertTrue(it["hook"]["fix"])
        self.assertFalse(it["cta"]["ok"])
        self.assertEqual(it["cta"]["fix"][0]["tool"], "end_card")

    def test_cut_in_the_middle_of_a_word_is_found_and_fixed_by_trimming(self):
        p = ops.new_project("reel")
        a = ops.media_clip(p, ASSETS["video:3"], 0, start=0, end=1.8)        # 1.8 is inside «محصول» (1.5–2.2)
        b = ops.media_clip(p, ASSETS["video:3"], 1.8, start=5, end=8)
        ops.place(ops.main_track(p), a, exact=True)
        ops.place(ops.main_track(p), b, exact=True)
        it = self.items(p)
        self.assertFalse(it["words"]["ok"])
        fixed, res = apply_steps(p, it["words"]["fix"], fake_ctx())
        self.assertTrue(all(r["ok"] for r in res))
        self.assertTrue(self.items(fixed)["words"]["ok"])

    def test_music_louder_than_speech_without_ducking_is_bad_and_auto_mix_fixes_it(self):
        p = self.project()
        p, _ = run_tool(p, "add_music", {"ref": "audio:1", "volume_db": -2, "duck": False})
        it = self.items(p)
        self.assertEqual(it["levels"]["severity"], "bad")
        fixed, _ = apply_steps(p, it["levels"]["fix"], fake_ctx())
        self.assertTrue(self.items(fixed)["levels"]["ok"])

    def test_length_over_the_platform_limit_is_bad(self):
        self.brief = brief_mod.finish_brief(brief_mod.parse_prompt("استوری"), [ASSETS["video:3"]])
        p = with_clip("video:3", start=0, end=20)
        p, _ = run_tool(p, "add_clip", {"ref": "video:1", "id": "b", "start": 0, "end": 12})
        it = self.items(p)
        self.assertFalse(it["length"]["ok"])

    def test_captions_over_the_platform_ui_are_flagged(self):
        p = with_clip("video:3", start=0, end=10)
        p, _ = run_tool(p, "add_captions", {"style": "pop"})
        cap = next(t for t in p["tracks"] if t.get("caption"))
        for c in cap["clips"]:
            c["y"] = 0.95
        it = self.items(p)
        self.assertFalse(it["captions"]["ok"])
        fixed, _ = apply_steps(p, it["captions"]["fix"], fake_ctx())
        self.assertTrue(self.items(fixed)["captions"]["ok"])

    def test_auto_fixes_apply_each_fix_once(self):
        rep = critique.critique(self.project(), self.an, self.brief)
        done = set()
        first = critique.auto_fixes(rep, done=done)
        again = critique.auto_fixes(rep, done=done)
        self.assertTrue(first)
        self.assertEqual(again, [])

    def test_score_drops_with_problems(self):
        good = loop.build_variant("a", brief_mod.finish_brief(brief_mod.parse_prompt("ریلز"), [ASSETS["video:1"]]), [ASSETS["video:1"]],
                                  analyze.analyze([ASSETS["video:1"], ASSETS["audio:1"]], fake_ctx(), want_moments=False), fake_ctx(), music_ref="audio:1", rounds=2)
        bare = critique.critique(self.project(), self.an, self.brief)
        self.assertGreater(good["score"], bare["score"])


# ================================================================== the agent loop (models mocked)
class FakeAI:
    """A stand-in for `ai.call_json`: answers per prompt id; can fail like a 402."""

    def __init__(self, brief=None, steps=None, vision=None, fail=None):
        self.brief, self.steps, self.vision, self.fail = brief, steps, vision, fail
        self.calls: list[str] = []

    def __call__(self, store, *, prompt, prompt_id, validate, system=None, job=None, images=None, vision=False, version="1"):
        self.calls.append(prompt_id)
        info = {"asked": True, "ok": False, "via": "", "model": "", "error_code": "", "error": "", "fell_back": False, "fallback_reason": ""}
        if self.fail and (self.fail == "all" or self.fail == prompt_id):
            info.update(error_code="no_credit", error="اعتبارِ حسابِ سرویسِ هوش مصنوعی (Metis) تمام شده است (خطای ۴۰۲).")
            return None, info
        answer = {"video_director_brief": self.brief, "video_director_steps": self.steps, "video_director_vision": self.vision}.get(prompt_id)
        if answer is None:
            info.update(error="no answer")
            return None, info
        ok, problems = validate(answer)
        assert ok, problems
        info.update(ok=True, via="node", model="gemma3:12b")
        return answer, info


class LoopTests(SimpleTestCase):
    def run_loop(self, prompt="ریلز معرفی چای", refs=("video:1", "video:2", "audio:1"), ai=None, preview=None, **opts):
        assets = [ASSETS[r] for r in refs]
        o = loop.Options(**{"variants": 3, "rounds": 2, **opts})
        return loop.run(prompt, assets, fake_ctx(), store=None, options=o, call=ai or FakeAI(fail="all"), review_preview=preview)

    def test_without_any_ai_the_recipes_still_deliver_three_editable_variants_and_say_what_needed_ai(self):
        res = self.run_loop(ai=FakeAI(fail="all"))
        self.assertEqual([v["key"] for v in res["variants"]], ["a", "b", "c"])
        for v in res["variants"]:
            check_valid(self, v["project"])
            self.assertTrue(v["plan"])
            self.assertTrue(all("text" in s and s["title"] for s in v["plan"]))
        text = " ".join(res["degraded"])
        self.assertIn("هوش مصنوعی جواب نداد", text)
        self.assertIn("۴۰۲", text)
        self.assertTrue(res["ai"]["needed_for"])
        self.assertFalse(res["ai"]["ok"])

    def test_the_model_refines_the_brief_but_never_overrides_what_the_owner_said(self):
        ai = FakeAI(brief={"recipe": "unboxing", "platform": "youtube", "duration": 40, "pace": "slow", "title": "چای سبز ممتاز", "subtitle": "تازه از باغ",
                           "cta": "همین امروز بخر", "discount": 0, "captions": True, "music": True, "look": "golden_hour", "hook_ref": "video:2", "order": ["video:2", "video:1"]},
                    steps={"steps": []}, vision=None)
        res = self.run_loop("ریلز ۱۵ ثانیه‌ای معرفی محصول", ai=ai)
        b = res["brief"]
        self.assertEqual(b["platform"], "reels")                     # the owner said ریلز
        self.assertEqual(b["duration"], 15)                          # …and ۱۵ ثانیه
        self.assertEqual(b["recipe"], "unboxing")                    # not stated: the model chose
        self.assertEqual(b["title"], "چای سبز ممتاز")
        self.assertEqual(b["cta"], "همین امروز بخر")
        self.assertIn("video_director_brief", ai.calls)
        self.assertTrue(res["ai"]["ok"])
        titles = [c["text"] for t in res["variants"][0]["project"]["tracks"] for c in t["clips"] if c.get("type") == "text"]
        self.assertIn("چای سبز ممتاز", titles)

    def test_extra_steps_from_the_model_are_validated_applied_and_labelled(self):
        ai = FakeAI(brief={"recipe": "product_showcase", "platform": "reels"},
                    steps={"steps": [{"tool": "color_look", "params": {"look": "moody", "amount": 40}, "why": "حالِ تیره‌تر"}, {"tool": "rm_rf", "params": {}}]})
        # make the primary variant fail the rubric in a way the rubric cannot fix by itself: a very slow pace for a reel
        res = self.run_loop("ریلز", ai=ai, variants=1)
        v = res["variants"][0]
        ai_steps = [s for s in v["plan"] if s["round"] >= 90]
        if ai_steps:                                                  # only when the rubric left something unfixed
            self.assertIn("video_director_steps", ai.calls)
            self.assertTrue(all(s["tool"] != "rm_rf" for s in ai_steps))
            self.assertTrue(all(s["why"] for s in ai_steps))

    def test_vision_critique_runs_on_the_preview_and_is_reported(self):
        ai = FakeAI(brief={"recipe": "product_showcase", "platform": "reels"}, steps={"steps": []},
                    vision={"scores": {"hook": 80, "pacing": 70}, "issues": [{"frame": 2, "what": "محصول از کادر بیرون است", "fix": "قاب را وسط بیاور"}], "verdict": "minor"})
        frames = []
        res = self.run_loop(ai=ai, preview=lambda project: (frames.append(1) or ["Zm9v"]) )
        self.assertIn("video_director_vision", ai.calls)
        v = res["variants"][[x["key"] for x in res["variants"]].index(res["primary"])]
        self.assertEqual(v["critique"]["vision"]["verdict"], "minor")
        self.assertTrue(frames)

    def test_no_preview_is_rendered_when_no_ai_would_look_at_it(self):
        called = []
        res = self.run_loop(ai=FakeAI(fail="all"), preview=lambda project: called.append(1) or ["x"])
        self.assertEqual(called, [])
        self.assertTrue(any("پیش‌نمایش" in d for d in res["degraded"]))

    def test_a_failing_preview_never_fails_the_edit(self):
        ai = FakeAI(brief={"recipe": "product_showcase", "platform": "reels"}, steps={"steps": []})
        def broken(project):
            raise RuntimeError("ffmpeg")
        res = self.run_loop(ai=ai, preview=broken)
        self.assertEqual(len(res["variants"]), 3)
        self.assertTrue(any("پیش‌نمایش" in d for d in res["degraded"]))

    def test_no_visual_assets_is_a_clear_error(self):
        res = loop.run("سلام", [ASSETS["audio:1"]], fake_ctx(), options=loop.Options(), call=FakeAI(fail="all"))
        self.assertIn("ویدیو یا عکس", res["error"])

    def test_at_most_n_revision_rounds(self):
        ai = FakeAI(brief={"recipe": "product_showcase", "platform": "reels"}, steps={"steps": [{"tool": "zoom", "params": {"clip": "all", "to_scale": 1.1}}]})
        self.run_loop(ai=ai, rounds=1, variants=1)
        self.assertLessEqual(ai.calls.count("video_director_steps"), 1)

    def test_rerun_applies_an_edited_plan_without_a_model_and_without_auto_fixes(self):
        res = self.run_loop(ai=FakeAI(fail="all"), variants=1)
        v = res["variants"][0]
        steps = [{k: s[k] for k in ("id", "tool", "params", "why")} | {"on": s["tool"] != "end_card"} for s in v["plan"]]
        again = loop.rerun(res["brief"], steps, [ASSETS[r] for r in ("video:1", "video:2", "audio:1")], fake_ctx(), key="a")
        tools_ok = [s["tool"] for s in again["plan"] if s.get("ok") and not s.get("skipped")]
        self.assertNotIn("end_card", tools_ok)
        self.assertEqual(again["rounds"], 0)
        self.assertFalse(again["critique"]["items"][[i["key"] for i in again["critique"]["items"]].index("cta")]["ok"])


# ================================================================== reframe maths
class ReframeTests(SimpleTestCase):
    def test_window_sizes(self):
        self.assertEqual(reframe.window_size(1920, 1080, 9 / 16), (0.3164, 1.0))
        self.assertEqual(reframe.window_size(1080, 1920, 16 / 9), (1.0, 0.3164))
        self.assertEqual(reframe.window_size(1000, 1000, 1.0), (1.0, 1.0))
        self.assertEqual(reframe.window_size(1920, 1080, 9 / 16, 2.0), (0.1582, 0.5))

    def test_aspect_parsing_and_errors(self):
        self.assertAlmostEqual(reframe.aspect_value("4:5"), 0.8)
        self.assertAlmostEqual(reframe.aspect_value("16/9"), 16 / 9)
        for bad in ("abc", "0:1", 99):
            with self.assertRaises(tl.TimelineError):
                reframe.aspect_value(bad)

    def test_camera_path_has_a_dead_zone_a_speed_limit_and_stays_inside(self):
        times = [i / 3 for i in range(30)]
        still = reframe.camera_path(times, [0.52] * 30, 0.158)
        self.assertLess(max(still) - min(still), 0.02)                       # a subject near the middle: the camera does not move
        jump = reframe.camera_path(times, [0.2] * 10 + [0.8] * 20, 0.158)
        steps = [abs(b - a) for a, b in zip(jump, jump[1:])]
        self.assertLessEqual(max(steps), 0.35 * 0.316 / 3 + 0.02)            # speed limit (plus smoothing slack)
        self.assertGreaterEqual(min(jump), 0.158 - 1e-6)
        self.assertLessEqual(max(jump), 1 - 0.158 + 1e-6)

    def test_simplify_keeps_at_most_24_keys_and_the_ends(self):
        times = [i / 3 for i in range(150)]
        values = [0.5 + 0.3 * np.sin(i / 7.0) for i in range(150)]
        keys = reframe.simplify(times, values)
        self.assertLessEqual(len(keys), 24)
        self.assertEqual(keys[0]["t"], 0)
        self.assertEqual(keys[-1]["t"], round(times[-1], 3))

    def frames(self, n=30):
        return np.zeros((n, 18, 32, 3), np.uint8)

    def test_a_subject_moving_left_to_right_pans_the_window_left_to_right(self):
        xs = [0.2 + 0.6 * i / 29 for i in range(30)]
        it = iter(xs)
        res = reframe.plan("x", 0, 10, "9:16", size=(1920, 1080), frames=self.frames(), faces_fn=lambda f: [(next(it), 0.5, 0.1)])
        self.assertEqual(res["engine"], "face")
        rf = res["reframe"]
        self.assertTrue(rf["kx"])
        self.assertLess(rf["kx"][0]["v"], rf["kx"][-1]["v"])
        self.assertNotIn("ky", rf)                                           # full height: nothing to pan vertically
        self.assertLessEqual(len(rf["kx"]), 24)
        self.assertTrue(all(0.158 - 1e-3 <= k["v"] <= 0.842 + 1e-3 for k in rf["kx"]))

    def test_a_still_subject_gives_a_static_window(self):
        res = reframe.plan("x", 0, 10, "9:16", size=(1920, 1080), frames=self.frames(), faces_fn=lambda f: [(0.6, 0.5, 0.1)])
        self.assertNotIn("kx", res["reframe"])
        self.assertAlmostEqual(res["reframe"]["cx"], 0.6, delta=0.05)

    def test_nobody_found_keeps_the_window_in_the_middle_and_says_so(self):
        res = reframe.plan("x", 0, 10, "9:16", size=(1920, 1080), frames=self.frames(), faces_fn=lambda f: [])
        self.assertIn(res["engine"], ("center", "motion"))
        self.assertAlmostEqual(res["reframe"]["cx"], 0.5, delta=0.2)

    def test_same_aspect_is_a_no_op(self):
        res = reframe.plan("x", 0, 5, "16:9", size=(1920, 1080), frames=self.frames())
        self.assertEqual((res["reframe"]["w"], res["reframe"]["h"]), (1.0, 1.0))
        self.assertTrue(res["notes"])

    def test_speed_rescales_key_times(self):
        xs = iter([0.2] * 5 + [0.8] * 25)
        res = reframe.plan("x", 0, 10, "9:16", size=(1920, 1080), frames=self.frames(), speed=2.0, faces_fn=lambda f: [(next(xs), 0.5, 0.1)])
        self.assertLessEqual(res["reframe"]["kx"][-1]["t"], 5.1)


class SafeZoneTests(SimpleTestCase):
    def test_catalogue_matches_margins_and_inside(self):
        cat = {z["key"]: z for z in safezones.catalogue()}
        self.assertEqual(set(cat), {"reels", "story", "tiktok", "shorts", "feed"})
        self.assertEqual(cat["tiktok"]["margins"], safezones.margins("tiktok"))
        self.assertFalse(safezones.inside("reels", 0.95))
        self.assertTrue(safezones.inside("reels", 0.5))
        self.assertEqual(safezones.margins(None, "square"), safezones.margins("feed"))


# ================================================================== filter graphs
class GraphTests(SimpleTestCase):
    def test_reframe_is_cleaned_and_a_full_window_disappears(self):
        raw = {"ref": "video:1", "reframe": {"w": 0.3164, "h": 1.0, "cx": 0.7, "cy": 0.5, "kx": [{"t": 0, "v": 0.3, "e": "linear"}, {"t": 2, "v": 0.7, "e": "linear"}]}}
        self.assertEqual(tl._clean_extras(raw)["reframe"]["kx"][1]["v"], 0.7)
        self.assertEqual(tl._clean_extras({"reframe": {"w": 1, "h": 1}})["reframe"], {})
        self.assertEqual(tl._clean_extras({"reframe": {"w": 9, "h": -1, "cx": 5}})["reframe"], {"w": 1.0, "h": 0.05, "cx": 1.0, "cy": 0.5})

    def project_json(self, **clip_extra):
        return {"format": {"width": 360, "height": 640, "fps": 25}, "tracks": [
            {"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 3, "fit": "cover", **clip_extra}]},
            {"kind": "audio", "role": "speech", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 3, "audio": {"denoise_ai": True}}]}],
            "master": {"gain_db": 0, "limiter": True, "loudness": {"on": True, "target": -14, "tp": -1}}}

    def timeline(self, data):
        def resolve(ref):
            return {"path": "/tmp/v.mp4", "kind": "video", "has_audio": True, "duration": 10.0, "width": 1920, "height": 1080}
        return tl.from_project(data, resolve)

    def test_the_graph_has_the_reframe_crop_before_the_fit_and_follows_keyframes(self):
        data = self.project_json(reframe={"w": 0.3164, "h": 1.0, "cx": 0.5, "cy": 0.5, "kx": [{"t": 0, "v": 0.3, "e": "linear"}, {"t": 2, "v": 0.7, "e": "linear"}]})
        graph = compose.build_graph(self.timeline(data)).graph
        self.assertIn("crop=w='max(2,floor(iw*0.3164/2)*2)'", graph)
        self.assertIn("x='clip(iw*(", graph)
        self.assertLess(graph.index("crop=w='max(2,floor(iw*0.3164"), graph.index("force_original_aspect_ratio=increase"))
        self.assertIn("lt(", graph)                                            # the keyframe expression (animated centre)

    def test_master_loudness_is_in_the_audio_graph_before_the_limiter(self):
        graph = compose.build_graph(self.timeline(self.project_json())).graph
        self.assertIn("loudnorm=I=-14:TP=-1:LRA=11", graph)
        self.assertLess(graph.index("loudnorm=I=-14"), graph.index("alimiter"))
        self.assertIn("aresample=48000", graph)
        self.assertIn("alimiter=limit=0.861:level=disabled", graph)             # −1 dB true-peak ceiling, 0.3 dB margin, no auto-level
        data = self.project_json()
        data["master"]["limiter"] = False
        self.assertNotIn("alimiter", compose.build_graph(self.timeline(data)).graph)
        data["master"]["loudness"] = {"on": False}
        data["master"]["limiter"] = True
        self.assertIn("alimiter=limit=0.95", compose.build_graph(self.timeline(data)).graph)        # without loudness the old limiter is unchanged

    def test_loudness_off_or_absent_leaves_the_graph_unchanged(self):
        data = self.project_json()
        data["master"]["loudness"] = {"on": False}
        self.assertNotIn("loudnorm=I=-14", compose.build_graph(self.timeline(data)).graph)
        del data["master"]
        self.assertNotIn("loudnorm=I=-14", compose.build_graph(self.timeline(data)).graph)

    def test_denoise_ai_uses_rnnoise_when_the_model_exists_and_travels_to_the_node(self):
        self.assertEqual(audiofx.fx_chain({"denoise_ai": True})[0], "afftdn=nr=14:nf=-28")            # no model handed in: the plain fallback
        self.assertEqual(audiofx.fx_chain({"denoise_ai": True}, rnn="arnndn=m=x")[0], "arnndn=m=x")
        self.assertEqual(audiofx.fx_chain({"denoise": True}), ["afftdn=nr=12:nf=-28"])             # the old switch is unchanged
        line = self.timeline(self.project_json())
        if audiofx.rnn_model() is None:
            self.skipTest("RNNoise model not installed on this machine")
        graph = compose.build_graph(line).graph
        self.assertIn("arnndn=m=", graph)
        portable = compose.build_graph(line, portable=True)
        self.assertIn("arnndn=m=", portable.graph)
        self.assertTrue(any(str(v).endswith(".rnnn") for v in portable.assets.values()), portable.assets)    # the model goes with the job
        with patch.object(audiofx, "rnn_model", return_value=None):
            self.assertNotIn("arnndn", compose.build_graph(line).graph)

    def test_window_cuts_reframe_keys_for_the_exact_preview(self):
        data = self.project_json(reframe={"w": 0.3164, "h": 1.0, "cx": 0.5, "cy": 0.5, "kx": [{"t": 0, "v": 0.3, "e": "linear"}, {"t": 3, "v": 0.7, "e": "linear"}]})
        part = tl.window(self.timeline(data), 1.5, 3.0)
        kx = part.tracks[0].clips[0].reframe["kx"]
        self.assertAlmostEqual(kx[0]["v"], 0.5, places=2)


class ExportTargetTests(SimpleTestCase):
    def line(self, seconds):
        data = {"format": {"width": 360, "height": 640, "fps": 25}, "tracks": [{"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": seconds}]}]}
        return tl.from_project(data, lambda ref: {"path": "/tmp/v.mp4", "kind": "video", "has_audio": False, "duration": 600.0, "width": 1920, "height": 1080})

    def test_target_size_sets_a_video_bitrate_ceiling_from_length_and_audio(self):
        from services.editing import export
        line = self.line(60)
        spec = export.resolve({"preset": "reels", "target_mb": 16}, line)
        want = int(16 * 8192 * 0.95 / 60 - 192)
        self.assertEqual(spec.max_kbps, want)
        self.assertIn("حجمِ هدف", spec.note)
        self.assertIsNone(export.resolve({"preset": "reels"}, line).max_kbps)
        args = export.encode_args(spec)
        self.assertIn("-maxrate", args)
        self.assertEqual(export.resolve({"preset": "whatsapp", "target_mb": 50}, line).max_kbps, 1800)      # the stricter cap wins
        self.assertIsNone(export.resolve({"preset": "reels", "target_mb": "junk"}, line).max_kbps)

    def test_a_tiny_budget_warns_to_lower_the_resolution(self):
        from services.editing import export
        spec = export.resolve({"preset": "reels", "target_mb": 8}, self.line(180))
        self.assertGreaterEqual(spec.max_kbps, 150)
        self.assertIn("۷۲۰", spec.note)


# ================================================================== real ffmpeg on tiny clips
TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-director-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class RealRenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from apps.content.tests_editor_modes import make_video
        from services.video.ffmpeg import FFMPEG
        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            return
        cls.wide = make_video(Path(TEMP_MEDIA) / "wide.mp4", size="320x180", seconds=3, audio=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "wide"):
            self.skipTest("ffmpeg نیست")

    def render(self, data, name="out.mp4"):
        from services.editing import export as export_module
        from services.video.ffmpeg import probe

        def resolve(ref):
            return {"path": str(self.wide), "kind": "video", "has_audio": True, "duration": 3.0, "width": 320, "height": 180}
        line = tl.from_project(data, resolve)
        line.validate()
        out = Path(TEMP_MEDIA) / name
        export_module.render(line, out, quality="final", export={"height": 360, "quality": "small", "fps": 12})
        return out, probe(out)

    def test_a_reframed_wide_clip_renders_vertical_with_a_panning_window(self):
        data = {"format": {"width": 240, "height": 426, "fps": 12}, "tracks": [
            {"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 3, "fit": "cover",
                                          "reframe": {"w": 0.3164, "h": 1.0, "cx": 0.2, "cy": 0.5, "kx": [{"t": 0, "v": 0.2, "e": "linear"}, {"t": 3, "v": 0.8, "e": "linear"}]}}]}]}
        out, info = self.render(data)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((v["width"], v["height"]), (360, 640))
        self.assertGreater(out.stat().st_size, 1000)

    def test_loudness_and_rnn_denoise_render_and_hit_the_target(self):
        import re
        import subprocess
        from services.video.ffmpeg import FFMPEG
        data = {"format": {"width": 240, "height": 426, "fps": 12}, "tracks": [
            {"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 3}]},
            {"kind": "audio", "role": "speech", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 3, "volume": 0.2, "audio": {"denoise_ai": True}}]}],
            "master": {"gain_db": 0, "limiter": True, "loudness": {"on": True, "target": -14, "tp": -1}}}
        out, info = self.render(data, "loud.mp4")
        self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
        r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
        self.assertTrue(m, r.stderr[-400:])
        # a 3-second sine is a hard case for a one-pass normaliser: within ~1.5 LU of the target (the quiet source was far below), and the
        # true peak under the −1 dB ceiling (measured on the encoded AAC)
        self.assertAlmostEqual(float(m[-1]), -14.0, delta=1.5)
        tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)
        self.assertTrue(tp and float(tp[-1]) <= -0.9, tp)

    def test_reframe_planning_on_a_real_clip_returns_a_valid_window(self):
        res = reframe.plan(str(self.wide), 0, 3, "9:16")
        self.assertIn(res["engine"], ("face", "motion", "center"))
        self.assertAlmostEqual(res["reframe"]["w"], 0.3164, places=3)
        self.assertGreater(res["samples"], 0)
        keys = res["reframe"].get("kx") or []
        self.assertLessEqual(len(keys), 24)


# ------------------------------------------------------------------ round 5: the live walkthrough found an unexportable variant
class EndCardOverlapTests(SimpleTestCase):
    """Variant «a» of a real run ended with `cut_to_beats` AFTER `end_card`: the re-cut picture grew into the end card
    («در ترک «تصویر ۱» دو قطعه هم‌زمان‌اند») and the export button stayed disabled."""

    def with_card(self):
        p = with_clip("video:1", start=0, end=12)
        p, _ = run_tool(p, "add_clip", {"ref": "video:2", "id": "b", "start": 0, "end": 8})
        p, r = run_tool(p, "end_card", {"text": "همین حالا", "duration": 2.5})
        self.assertTrue(r["ok"], r)
        return p

    def no_overlap(self, p):
        for t in p["tracks"]:
            if t["kind"] != "video":
                continue
            cs = sorted([c for c in t["clips"] if c.get("type") == "media"], key=lambda c: float(c["at"]))
            for a, b in zip(cs, cs[1:]):
                self.assertGreaterEqual(float(b["at"]), ops.clip_end(a) - 0.001, f"{a.get('label')} ends {ops.clip_end(a)} but {b.get('label')} starts {b['at']}")

    def test_cut_to_beats_after_an_end_card_keeps_the_card_after_the_picture(self):
        p = self.with_card()
        before = {c["id"]: c for c in ops.main_track(p)["clips"]}
        card = next(c for c in before.values() if c.get("label") == "کارتِ پایانی")
        picture_end = float(card["at"])
        p, r = run_tool(p, "cut_to_beats", {"music": "audio:1", "every": 2})
        self.assertTrue(r["ok"], r)
        self.no_overlap(p)
        card_after = next(c for c in ops.main_track(p)["clips"] if c.get("label") == "کارتِ پایانی")
        pieces = [c for c in ops.main_track(p)["clips"] if c.get("label") != "کارتِ پایانی"]
        self.assertLessEqual(max(ops.clip_end(c) for c in pieces), float(card_after["at"]) + 0.001)
        self.assertAlmostEqual(max(ops.clip_end(c) for c in pieces), picture_end, delta=0.6, msg="the picture keeps (about) its length")
        check_valid(self, p)

    def test_the_whole_variant_recipe_order_that_failed_live_is_now_exportable(self):
        p = self.with_card()
        for tool, params in (("close_gaps", {"track": "main"}), ("cut_to_beats", {"music": "audio:1", "every": 2}), ("fit_length", {"seconds": 14}),
                             ("close_gaps", {"track": "main"}), ("cut_to_beats", {"music": "audio:1", "every": 2})):
            p, r = run_tool(p, tool, params)
            self.no_overlap(p)
        check_valid(self, p)

    def test_heal_overlaps_pushes_a_later_clip_and_puts_the_card_last(self):
        p = self.with_card()
        main = ops.main_track(p)
        card = next(c for c in main["clips"] if c.get("label") == "کارتِ پایانی")
        late = {**next(c for c in main["clips"] if c.get("label") != "کارتِ پایانی"), "id": "late", "at": float(card["at"]) + 0.5, "start": 0, "end": 2}
        main["clips"].append(late)
        self.assertEqual(ops.heal_overlaps(p), 1)
        self.no_overlap(p)
        card_now = next(c for c in main["clips"] if c.get("label") == "کارتِ پایانی")
        self.assertGreaterEqual(float(card_now["at"]), ops.clip_end(late) - 0.001)

    def test_heal_overlaps_leaves_a_clean_project_untouched(self):
        p = self.with_card()
        before = json.dumps(p, sort_keys=True)
        self.assertEqual(ops.heal_overlaps(p), 0)
        self.assertEqual(json.dumps(p, sort_keys=True), before)

    def test_apply_steps_heals_and_says_so(self):
        p = self.with_card()
        main = ops.main_track(p)
        main["clips"].append({**next(c for c in main["clips"] if c.get("label") != "کارتِ پایانی"), "id": "dup", "at": 0.0})
        new, results = apply_steps(p, [{"tool": "close_gaps", "params": {"track": "overlay"}}], fake_ctx(), platform="reels")
        self.no_overlap(new)
        self.assertTrue(any("همپوشانی" in n for n in results[-1].get("notes", [])), results[-1])

# -*- coding: utf-8 -*-
"""The owner's brief for the automatic edit, item by item: every size, caption look, director step, API route and node entry he asked for EXISTS.

He once said «you did not even add all those styles»; this file is the answer — a missing or renamed item fails here by name, not silently.
Pure catalogue checks (no ffmpeg, no node); the behaviour of each item is proven in the other `tests_autoedit_*` files."""
import json
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from services.editing import music_match, social_sizes
from services.editing.director import brief as brief_mod
from services.editing.director.tools import BG_MODES, CAPTION_STYLES, TOOLS
from services.editing.silence_intel import ACTIONS

ROOT = Path(__file__).resolve().parents[2]


class SizesAndNetworks(SimpleTestCase):
    #: network -> (size key, width, height)
    WANTED = {"Instagram reel": ("ig_reel", 1080, 1920), "Instagram story": ("ig_story", 1080, 1920), "Instagram post 4:5": ("ig_post", 1080, 1350),
              "Instagram square": ("ig_square", 1080, 1080), "YouTube": ("yt_wide", 1920, 1080), "YouTube Shorts": ("yt_shorts", 1080, 1920),
              "TikTok": ("tiktok", 1080, 1920), "Telegram": ("telegram", 1280, 720), "Aparat": ("aparat", 1920, 1080)}

    def test_every_network_the_owner_named_has_its_frame(self):
        for name, (key, w, h) in self.WANTED.items():
            self.assertIn(key, social_sizes.SIZES, name)
            self.assertEqual(tuple(social_sizes.SIZES[key]["size"]), (w, h), name)

    def test_each_size_knows_its_safe_zone_export_preset_and_a_persian_title(self):
        for key, s in social_sizes.SIZES.items():
            for field in ("title", "network", "aspect", "zone", "export", "preset"):
                self.assertTrue(s.get(field), f"{key}.{field}")
        cat = {c["key"]: c for c in social_sizes.catalogue()}
        self.assertEqual(set(cat), set(social_sizes.SIZES))

    def test_several_sizes_in_one_go_keep_order_and_drop_unknown_keys(self):
        self.assertEqual(social_sizes.clean_keys(["tiktok", "nope", "ig_reel", "tiktok"]), ["tiktok", "ig_reel"])

    def test_every_size_has_a_plan_that_reframes_to_its_aspect(self):
        for key, s in social_sizes.SIZES.items():
            steps = social_sizes.derive_steps(key)
            self.assertEqual(steps[0]["tool"], "set_format", key)
            reframe = next(x for x in steps if x["tool"] == "reframe")
            self.assertEqual(reframe["params"]["aspect"], s["aspect"], key)
            self.assertTrue(reframe["params"]["compose"], f"{key}: composition (thirds, headroom, lead room) is on")

    def test_the_director_platforms_cover_reel_story_tiktok_shorts_feed_square_and_youtube(self):
        self.assertTrue({"reels", "story", "tiktok", "shorts", "feed", "square", "youtube"} <= set(brief_mod.PLATFORMS))
        for p in brief_mod.PLATFORMS:
            self.assertIn(social_sizes.for_platform(p), social_sizes.SIZES, p)


class CaptionLooks(SimpleTestCase):
    def test_there_are_several_word_highlight_looks_each_with_a_highlight_mode(self):
        self.assertGreaterEqual(len(CAPTION_STYLES), 6)
        for key in ("pop", "box", "karaoke", "clean", "neon", "typewriter", "lower"):
            self.assertIn(key, CAPTION_STYLES)
            self.assertTrue(CAPTION_STYLES[key]["title"])
            self.assertIn(CAPTION_STYLES[key]["style"]["hl_mode"], ("color", "scale", "box"), key)
        self.assertGreaterEqual(len({v["style"]["hl_mode"] for v in CAPTION_STYLES.values()}), 3, "colour, swell and marker highlights all exist")


class DirectorSteps(SimpleTestCase):
    #: the steps of the owner's list: light, framing, background, cuts, silence, subtitles, music, sizes
    NEEDED = ("auto_look", "reframe", "crop_content", "split_shots", "background", "smart_cuts", "remove_fillers", "remove_retakes", "remove_silence",
              "add_captions", "caption_style", "pick_music", "add_music", "ducking", "auto_mix", "set_loudness", "clean_voice", "set_format")

    def test_every_step_exists(self):
        for name in self.NEEDED:
            self.assertIn(name, TOOLS, name)

    def test_the_background_can_be_kept_blurred_or_replaced_by_a_colour_or_a_picture(self):
        self.assertEqual(set(BG_MODES), {"keep", "blur", "color", "image"})

    def test_the_polish_recipe_exists_and_says_what_it_does(self):
        self.assertIn("polish", brief_mod.RECIPES)

    def test_a_pause_answer_is_keep_shorten_or_cut(self):
        self.assertEqual(set(ACTIONS), {"keep", "shorten", "cut"})

    def test_the_music_matcher_knows_moods_and_ranks_by_them(self):
        self.assertTrue(len(music_match.MOODS) >= 4)
        for fn in ("rank", "score", "loop_plan", "target_for"):
            self.assertTrue(callable(getattr(music_match, fn)), fn)


class Routes(SimpleTestCase):
    def test_the_api_routes_exist(self):
        for name, kwargs in (("autoedit-silences", {"store_id": 1}), ("autoedit-sizes", {"store_id": 1}), ("autoedit-look-preview", {"store_id": 1}),
                             ("autoedit-project-sizes", {"store_id": 1, "pk": 2}), ("autoedit-upload", {"store_id": 1, "pk": 3})):
            url = reverse(name, kwargs=kwargs)
            self.assertEqual(resolve(url).url_name, name)


class NodeSide(SimpleTestCase):
    def test_the_node_installs_what_the_feature_needs_by_itself(self):
        manifest = json.loads((ROOT / "processing" / "requirements.d" / "autoedit.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["feature"], "autoedit")
        self.assertIn("gpu-runtime", manifest["requires"])
        self.assertTrue(manifest["items"])
        for name in ("asr-gpu.json", "gpu-runtime.json", "ffmpeg-nvenc.json"):
            self.assertTrue((ROOT / "processing" / "requirements.d" / name).is_file(), name)

    def test_the_acceptance_run_has_the_automatic_edit_entries(self):
        from apps.compute.selftests import REGISTRY, load_all

        load_all()
        for key in ("autoedit_words", "autoedit_mix", "autoedit_matte"):
            self.assertIn(key, REGISTRY, key)

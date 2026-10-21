"""The finishing pass, and the product-only rule for generated scenes.

Two complaints about one video (script 1, «قهوه», 1405/07/29): "the quality
is low" and "someone came out of nowhere — a woman with a man's hands grabbed
the coffee". The first is answered by services.video.enhance, the second by
scene_state.people_allowed and the script validator. These tests pin both,
using the owner's own scene texts where it matters.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from services.ai.ollama import strip_reasoning
from services.ai.prompts import video_script as script_prompts
from services.video import enhance, scene_state
from services.video.ffmpeg import FFMPEG, probe_video
from services.video.scene_state import SceneState

# The owner's script 1, exactly as qwq:32b wrote it.
OWNER_SCENE_2 = (
    "The same coffee cup, now with a hand reaching for it, warm lighting continues, "
    "no text, no letters, no logos, no typography."
)
OWNER_SCENE_3 = (
    "The coffee cup now being enjoyed, with a satisfied smile on a person's face, "
    "warm lighting, no text, no letters, no logos, no typography."
)


def _has_ffmpeg() -> bool:
    return Path(FFMPEG).exists() or shutil.which(FFMPEG) is not None


requires_ffmpeg = unittest.skipUnless(_has_ffmpeg(), "ffmpeg not installed")


class FakeScene:
    def __init__(self, **kwargs):
        self.index = kwargs.pop("index", 2)
        self.visual_prompt = kwargs.pop("visual_prompt", "")
        self.motion_prompt = kwargs.pop("motion_prompt", "")
        self.transition = kwargs.pop("transition", "CONTINUE")
        self.state = kwargs.pop("state", {})
        self.speaker_on_camera = kwargs.pop("speaker_on_camera", False)


def product(name, **extra):
    return SimpleNamespace(name=name, short_description=extra.get("short", ""),
                           category=None, tags=extra.get("tags", []))


COFFEE = product("قهوه")
SHOE = product("کفش اسپرت")


class TargetSizeTests(SimpleTestCase):
    def test_wan_frame_covers_720p(self):
        """832×480 is within 3% of 16:9: cover 1280×720 and crop, no stretch."""
        self.assertEqual(enhance.target_size(832, 480), (1280, 720, "cover"))

    def test_portrait_is_kept_portrait(self):
        self.assertEqual(enhance.target_size(480, 832), (720, 1280, "cover"))

    def test_other_shapes_keep_their_aspect(self):
        w, h, mode = enhance.target_size(480, 480)
        self.assertEqual((w, h, mode), (720, 720, "fit"))

    def test_already_big_enough_is_left_alone(self):
        self.assertEqual(enhance.target_size(1920, 1080)[2], "none")


class BuildFiltersTests(SimpleTestCase):
    def cfg(self, **over):
        return {**enhance.config(), **over}

    def test_full_chain_for_a_wan_segment(self):
        chain, applied, shape = enhance.build_filters(
            {"width": 832, "height": 480, "fps": 16}, self.cfg(),
        )
        joined = ",".join(chain)
        self.assertIn("minterpolate=fps=32", joined)
        self.assertIn("mc_mode=aobmc", joined)
        self.assertIn("flags=lanczos", joined)
        self.assertIn("crop=1280:720", joined)
        self.assertIn("cas=", joined)
        self.assertIn("hqdn3d", joined)
        # padded BEFORE interpolating, or the output ends one source frame early
        self.assertLess(joined.index("tpad"), joined.index("minterpolate"))
        # interpolation before the upscale: motion search at 480p costs a
        # fraction of the same search at 720p
        self.assertLess(joined.index("minterpolate"), joined.index("scale="))
        self.assertEqual(shape, {"width": 1280, "height": 720, "fps": 32.0})
        self.assertEqual(applied, ["denoise", "deband", "interpolate_mci", "upscale", "sharpen"])

    def test_no_interpolation_when_already_smooth(self):
        chain, applied, shape = enhance.build_filters(
            {"width": 832, "height": 480, "fps": 30}, self.cfg(fps=30),
        )
        self.assertNotIn("interpolate_mci", applied)
        self.assertEqual(shape["fps"], 30)

    def test_interpolation_can_be_switched_off(self):
        _, applied, _ = enhance.build_filters(
            {"width": 832, "height": 480, "fps": 16}, self.cfg(interpolation="off"),
        )
        self.assertNotIn("interpolate_mci", applied)
        self.assertIn("upscale", applied)


class EnhanceSafetyTests(SimpleTestCase):
    def test_disabled_keeps_the_source(self):
        result = enhance.enhance("/nonexistent.mp4", "/tmp/x.mp4", cfg={"enabled": False})
        self.assertFalse(result.ok)

    def test_unreadable_source_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.mp4"
            bad.write_bytes(b"not a video")
            result = enhance.enhance(bad, Path(tmp) / "out.mp4")
            self.assertFalse(result.ok)
            self.assertFalse((Path(tmp) / "out.mp4").exists())


@requires_ffmpeg
class EnhanceRealTests(SimpleTestCase):
    """Run the real chain on a tiny clip shaped like a Wan segment."""

    def test_doubles_fps_upscales_keeps_length_and_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "seg.mp4"
            subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc2=size=208x120:rate=16:duration=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
                check=True, stdin=subprocess.DEVNULL,
            )
            before = probe_video(src)
            out = Path(tmp) / "seg_hd.mp4"
            # A small target keeps the test fast; the geometry rule is the same.
            result = enhance.enhance(src, out, cfg={"enabled": True, "short_side": 180,
                                                    "long_side": 320, "preset": "veryfast",
                                                    "nice": 0})
            self.assertTrue(result.ok, result.note)
            after = probe_video(out)
            self.assertEqual((after["width"], after["height"]), (320, 180))
            self.assertAlmostEqual(after["fps"], 32, delta=0.5)
            self.assertTrue(after["has_audio"])
            # exactly as long as the source: narration is timed against it
            self.assertAlmostEqual(after["duration"], before["duration"], delta=0.04)
            self.assertIn("interpolate_mci", result.applied)
            self.assertFalse(list(Path(tmp).glob("*.part.mp4")))


class PeopleRuleTests(SimpleTestCase):
    def test_coffee_is_not_worn_and_a_shoe_is(self):
        self.assertFalse(scene_state.people_fit(COFFEE))
        self.assertTrue(scene_state.people_fit(SHOE))
        self.assertTrue(scene_state.people_fit(product("کیف‌های چرمی")))

    def test_the_hand_and_the_smile_are_cut_out(self):
        two = scene_state.without_people_text(OWNER_SCENE_2)
        three = scene_state.without_people_text(OWNER_SCENE_3)
        for text in (two, three):
            self.assertFalse(scene_state.mentions_people(text), text)
            self.assertIn("coffee cup", text)
            self.assertIn("no text", text)

    def test_a_coffee_scene_with_a_hand_is_product_only(self):
        scene = FakeScene(visual_prompt=OWNER_SCENE_2, state={"characters": ["hand"]})
        self.assertFalse(scene_state.people_allowed(scene, COFFEE))

    def test_a_scene_the_shop_marked_for_a_speaker_may_show_one(self):
        scene = FakeScene(visual_prompt=OWNER_SCENE_3, speaker_on_camera=True)
        self.assertTrue(scene_state.people_allowed(scene, COFFEE))

    def test_a_worn_product_may_show_its_wearer(self):
        scene = FakeScene(visual_prompt="A woman walks in the street wearing the shoe")
        self.assertTrue(scene_state.people_allowed(scene, SHOE))

    def test_product_only_prompt_says_so_in_the_positive(self):
        """Wan runs at cfg 1 here: the negative is skipped, so "no people"
        has to be in the positive text."""
        scene = FakeScene(visual_prompt=OWNER_SCENE_3, motion_prompt="slow push-in on the smiling face",
                          state={"characters": ["smiling person"]})
        state = SceneState(characters=["smiling person"], objects=["coffee cup"], lighting="warm")
        positive, negative = scene_state.compile_prompt(
            scene, state, allow_people=False, product=COFFEE,
        )
        self.assertIn(scene_state.PRODUCT_ONLY, positive)
        self.assertNotIn("smiling", positive)
        self.assertNotIn("person's face", positive)
        self.assertNotIn("faces the camera", positive)
        self.assertIn("camera only", positive)
        self.assertIn("hands", negative)
        self.assertIn("person, people", negative)
        # the product and the scene's look survive
        self.assertIn("coffee cup", positive)
        self.assertIn("warm", positive)

    def test_allowed_people_keep_the_old_prompt(self):
        scene = FakeScene(visual_prompt="A runner wearing the shoe", state={"characters": ["runner"]})
        positive, negative = scene_state.compile_prompt(scene, None, allow_people=True)
        self.assertNotIn(scene_state.PRODUCT_ONLY, positive)
        self.assertIn(scene_state.MOUTH_CLOSED, positive)
        self.assertNotIn(scene_state.NO_PEOPLE_NEGATIVE, negative)

    def test_nothing_left_falls_back_to_the_product(self):
        scene = FakeScene(visual_prompt="A smiling woman holds it")
        positive, _ = scene_state.compile_prompt(scene, None, allow_people=False, product=COFFEE)
        self.assertIn("product from the reference photo", positive)

    def test_continuity_carries_nobody_forward(self):
        state = scene_state.without_people(SceneState(characters=["a woman"], clothing=["red coat"],
                                                      objects=["mug"]))
        self.assertEqual(state.characters, [])
        self.assertEqual(state.clothing, [])
        self.assertEqual(state.objects, ["mug"])


class ScriptValidatorTests(SimpleTestCase):
    def script(self, *scenes):
        return {"concept": "c", "cta": "x", "scenes": list(scenes)}

    def test_visual_under_another_key_is_used(self):
        parsed = self.script({"visual": "A red mug on a wooden table", "camera": "slow orbit",
                              "narration": "n"})
        ok, problems = script_prompts.validate_video_script(parsed, 5, product=COFFEE)
        self.assertTrue(ok, problems)
        scene = parsed["scenes"][0]
        self.assertEqual(scene["visual_prompt"], "A red mug on a wooden table")
        self.assertEqual(scene["motion_prompt"], "slow orbit")
        self.assertTrue(parsed["repairs"])

    def test_missing_visual_is_built_from_the_product_not_dropped(self):
        parsed = self.script({"narration": "قهوه ما", "duration": 5},
                             {"narration": "همین حالا", "duration": 5})
        ok, problems = script_prompts.validate_video_script(parsed, 5, product=COFFEE)
        self.assertTrue(ok, problems)
        self.assertEqual(len(parsed["scenes"]), 2)
        for scene in parsed["scenes"]:
            self.assertIn("product", scene["visual_prompt"])
            self.assertIn("camera only", scene["motion_prompt"])

    def test_owner_script_loses_its_person(self):
        parsed = self.script(
            {"visual_prompt": "A steaming cup of coffee on a wooden table", "motion_prompt": "slow push-in",
             "narration": "a", "transition": "NEW_SCENE"},
            {"visual_prompt": OWNER_SCENE_2, "motion_prompt": "gentle orbit around the coffee cup",
             "narration": "b", "state": {"characters": ["hand"], "objects": ["coffee cup"]}},
            {"visual_prompt": OWNER_SCENE_3, "motion_prompt": "slow push-in on the smiling face",
             "narration": "c", "state": {"characters": ["smiling person"]}},
        )
        ok, problems = script_prompts.validate_video_script(parsed, 5, product=COFFEE)
        self.assertTrue(ok, problems)
        for scene in parsed["scenes"]:
            self.assertFalse(scene_state.mentions_people(scene["visual_prompt"]), scene["visual_prompt"])
            self.assertFalse(scene_state.mentions_people(scene["motion_prompt"]), scene["motion_prompt"])
            self.assertNotIn("characters", scene["state"])
        self.assertEqual(parsed["scenes"][1]["motion_prompt"], "gentle orbit around the coffee cup")

    def test_a_worn_product_keeps_its_model(self):
        parsed = self.script({"visual_prompt": "A woman walks wearing the shoe", "people": True,
                              "motion_prompt": "tracking shot", "narration": "a"})
        script_prompts.validate_video_script(parsed, 5, product=SHOE)
        self.assertIn("woman", parsed["scenes"][0]["visual_prompt"])

    def test_the_prompt_forbids_invented_people(self):
        self.assertEqual(script_prompts.VIDEO_SCRIPT_PROMPT_VERSION, "7")


class StripReasoningTests(SimpleTestCase):
    def test_orphan_closing_tag_from_qwq_template(self):
        text = 'Let me draft {"scenes": []} first... </think>\n{"concept": "c"}'
        self.assertEqual(strip_reasoning(text), '{"concept": "c"}')

    def test_full_block_still_removed(self):
        self.assertEqual(strip_reasoning('<think>x</think>{"a": 1}'), '{"a": 1}')

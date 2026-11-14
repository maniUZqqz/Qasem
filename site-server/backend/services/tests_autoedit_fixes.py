"""The fixes after the owner's own video went through the automatic edit (1405/08/23): shot detection that finds the selfie -> screen-recording cut,
the picture background choice, the Whisper model choice, and the quiet log line of a run that waits for the processing server.

Pure-Python / ffmpeg tests (no database); the database ones live in apps/content/tests_autoedit_fixes.py.
"""
import atexit
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from services.editing import captions, scenes
from services.editing.director import brief as brief_mod
from services.editing.director import loop, recipes
from services.video.ffmpeg import FFMPEG

HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
TEMP = Path(tempfile.mkdtemp(prefix="nm-autoedit-fixes-"))
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)


class ShotDetectionTests(SimpleTestCase):
    """The owner's video: a selfie camera, then a recorded phone screen at 12.5 s.  ffmpeg's scdet scored that hard cut 10.2 (its bar was 12), so the
    edit never split it and treated the face part as a screen recording.  The numbers below are measured on that file (64x36 thumbnails, 30 fps)."""

    FPS = scenes.SCAN_FPS

    def owner_like(self, seconds=100):
        """mad / hist_dist per frame with the three real cuts of the owner's video (8.67, 12.47, 92.73) and its UI changes (the app turning a page)."""
        n = int(seconds * self.FPS)
        mad = np.full(n, 1.2, dtype=np.float32)
        dist = np.full(n, 0.004, dtype=np.float32)
        for t, m, d in ((8.667, 27.49, 0.255), (12.467, 28.25, 0.277), (92.733, 38.59, 0.181)):          # the real cuts
            mad[int(round(t * self.FPS))], dist[int(round(t * self.FPS))] = m, d
        for t, m, d in ((11.667, 9.38, 0.207), (46.4, 5.48, 0.180), (58.6, 8.79, 0.181), (63.27, 8.81, 0.176), (84.6, 8.81, 0.176)):   # a page turning
            mad[int(round(t * self.FPS))], dist[int(round(t * self.FPS))] = m, d
        return mad, dist

    def test_the_selfie_to_screen_cut_is_found_at_the_normal_sensitivity(self):
        mad, dist = self.owner_like()
        cuts = [round(t, 1) for t, _m, _d in scenes.pick_cuts(mad, dist, "normal")]
        self.assertEqual(cuts, [8.7, 12.5, 92.7], "the face section must be split off from the app recording")

    def test_an_app_changing_page_is_not_a_cut_unless_asked_for(self):
        mad, dist = self.owner_like()
        for level in ("low", "normal", "high"):
            cuts = [round(t, 1) for t, _m, _d in scenes.pick_cuts(mad, dist, level)]
            for page in (11.7, 46.4, 58.6, 63.3, 84.6):
                self.assertNotIn(page, cuts, f"{level}: {page} is the app turning a page, not a shot change")

    def test_the_sensitivity_levels_are_ordered(self):
        self.assertGreater(scenes.RULES["low"][0], scenes.RULES["normal"][0])
        self.assertGreater(scenes.RULES["normal"][0], scenes.RULES["high"][0])
        self.assertGreater(scenes.SENSITIVITY["low"], scenes.SENSITIVITY["normal"])
        self.assertGreater(scenes.SENSITIVITY["normal"], scenes.SENSITIVITY["high"])
        mad = np.zeros(300, dtype=np.float32)
        dist = np.zeros(300, dtype=np.float32)
        mad[100], dist[100] = 20.0, 0.3        # a clear cut: normal and high see it
        mad[200], dist[200] = 12.0, 0.2        # a soft one: only high
        self.assertEqual(len(scenes.pick_cuts(mad, dist, "low")), 0)
        self.assertEqual(len(scenes.pick_cuts(mad, dist, "normal")), 1)
        self.assertEqual(len(scenes.pick_cuts(mad, dist, "high")), 2)

    def test_a_flash_or_a_burst_of_frames_is_one_cut(self):
        mad = np.zeros(300, dtype=np.float32)
        dist = np.zeros(300, dtype=np.float32)
        for i in (100, 101, 103):                       # one event, three frames in a row
            mad[i], dist[i] = 30.0 + i % 3, 0.4
        mad[102] = 45.0                                  # the sharpest frame of the event is the cut
        dist[102] = 0.5
        got = scenes.pick_cuts(mad, dist, "normal")
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0][0], 102 / self.FPS, places=2)

    def test_a_picture_change_with_the_same_colours_is_not_a_cut(self):
        """A brightness flicker or a pan across the same scene moves pixels but not the colour distribution: the histogram bar rejects it."""
        mad = np.zeros(200, dtype=np.float32)
        dist = np.zeros(200, dtype=np.float32)
        mad[80], dist[80] = 40.0, 0.03
        self.assertEqual(scenes.pick_cuts(mad, dist, "normal"), [])

    def _two_shots(self, name, first, second, seconds=3):
        out = TEMP / name
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", first, "-f", "lavfi", "-i", second, "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
                        "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)
        return out

    def test_real_video_a_bright_camera_shot_then_a_bright_app_page(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        camera = "color=c=0xC9A98F:s=320x180:r=25:d=3,noise=alls=22:allf=t,drawbox=x=100:y=30:w=120:h=130:c=0xB07860:t=fill"
        app = "color=c=0xF4F4F6:s=320x180:r=25:d=3,drawbox=x=10:y=20:w=300:h=14:c=0xD8D8DE:t=fill,drawbox=x=10:y=60:w=200:h=40:c=0xCCD6F0:t=fill"
        path = self._two_shots("camera_then_app.mp4", camera, app)
        got = scenes.detect_cuts(path, 0.0, 6.0)
        self.assertEqual(got["engine"], "frames")
        self.assertEqual(len(got["cuts"]), 1, got)
        self.assertAlmostEqual(got["cuts"][0], 3.0, delta=0.1)

    def test_real_video_one_app_page_to_another_is_no_cut(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        one = "color=c=0xF4F4F6:s=320x180:r=25:d=3,drawbox=x=10:y=20:w=300:h=14:c=0xD8D8DE:t=fill,drawbox=x=10:y=80:w=220:h=40:c=0xCCD6F0:t=fill"
        two = "color=c=0xF4F4F6:s=320x180:r=25:d=3,drawbox=x=10:y=60:w=300:h=14:c=0xD8D8DE:t=fill,drawbox=x=40:y=120:w=220:h=40:c=0xCCD6F0:t=fill"
        path = self._two_shots("page_to_page.mp4", one, two)
        self.assertEqual(scenes.detect_cuts(path, 0.0, 6.0, "normal")["cuts"], [])

    def test_the_window_is_in_source_seconds_and_the_ends_are_not_cuts(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        path = self._two_shots("window.mp4", "color=c=red:s=160x90:r=10:d=2", "color=c=blue:s=160x90:r=10:d=3")
        self.assertAlmostEqual(scenes.detect_cuts(path, 0.0, 5.0)["cuts"][0], 2.0, delta=0.1)
        self.assertAlmostEqual(scenes.detect_cuts(path, 1.0, 4.0)["cuts"][0], 2.0, delta=0.1)
        self.assertEqual(scenes.detect_cuts(path, 2.5, 5.0)["cuts"], [])

    def test_a_failing_frame_path_falls_back_to_scdet(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        path = self._two_shots("fallback.mp4", "color=c=red:s=160x90:r=10:d=2", "color=c=blue:s=160x90:r=10:d=3")
        with patch.object(scenes, "measure", side_effect=RuntimeError("no numpy today")):
            got = scenes.detect_cuts(path, 0.0, 5.0)
        self.assertEqual(got["engine"], "scdet")
        self.assertEqual(len(got["cuts"]), 1)


class BackgroundPictureTests(SimpleTestCase):
    """«پس‌زمینه: جایگزین با عکس» - the backend always supported it; the panel could not choose it."""

    def test_the_words_replace_the_background_with_a_picture(self):
        for text in ("پس‌زمینه را با عکس عوض کن", "پس زمینه با تصویر فروشگاه باشد", "replace the background with a photo"):
            self.assertEqual(brief_mod.parse_prompt(text)["background"], "image", text)
        self.assertEqual(brief_mod.parse_prompt("پس‌زمینه را محو کن")["background"], "blur")
        self.assertEqual(brief_mod.parse_prompt("پس‌زمینه ساده باشد")["background"], "color")

    def test_the_chip_carries_the_picture_and_refuses_a_bad_reference(self):
        b = {"matched": [], "notes": []}
        loop._apply_override(b, {"background": "image", "background_ref": "image:12"})
        self.assertEqual((b["background"], b["background_ref"]), ("image", "image:12"))
        b = {"matched": [], "notes": []}
        loop._apply_override(b, {"background": "image", "background_ref": "../../etc/passwd"})
        self.assertEqual(b["background"], "image")
        self.assertNotIn("background_ref", b, "only a library picture reference is accepted")
        b = {"matched": [], "notes": []}
        loop._apply_override(b, {"background": "pencil"})
        self.assertNotIn("background", b)

    def _plan(self, brief, assets):
        an = {"by_ref": {a["ref"]: {"kind": a["kind"], "duration": a.get("duration", 10), "box": {}} for a in assets}, "has_speech": True, "has_words": False}
        ctx = {"an": an, "brief": brief, "assets": assets, "plat": brief_mod.PLATFORMS["reels"], "v": recipes.VARIANTS["a"], "pace": "normal", "music": ""}
        return recipes._polish(ctx)

    VIDEO = {"ref": "video:1", "kind": "video", "duration": 30}
    PHOTO = {"ref": "image:7", "kind": "image"}

    def test_the_polish_recipe_adds_the_background_step_with_the_chosen_picture(self):
        steps = self._plan({"background": "image", "background_ref": "image:9", "music": False, "captions": False}, [self.VIDEO, self.PHOTO])
        bg = next(s for s in steps if s["tool"] == "background")
        self.assertEqual((bg["params"]["mode"], bg["params"]["ref"]), ("image", "image:9"))

    def test_without_a_chosen_picture_an_image_among_the_picked_media_is_used(self):
        steps = self._plan({"background": "image", "music": False, "captions": False}, [self.VIDEO, self.PHOTO])
        bg = next(s for s in steps if s["tool"] == "background")
        self.assertEqual(bg["params"]["ref"], "image:7")

    def test_without_any_picture_there_is_a_note_and_no_broken_step(self):
        brief = {"background": "image", "music": False, "captions": False, "notes": []}
        steps = self._plan(brief, [self.VIDEO])
        self.assertFalse([s for s in steps if s["tool"] == "background"])
        self.assertTrue(any("عکسی انتخاب نشد" in n for n in brief["notes"]), brief["notes"])

    def test_blur_and_colour_are_as_before(self):
        for mode in ("blur", "color"):
            steps = self._plan({"background": mode, "music": False, "captions": False}, [self.VIDEO])
            self.assertEqual(next(s for s in steps if s["tool"] == "background")["params"], {"mode": mode, "clip": "main"})


class WhisperModelChoiceTests(SimpleTestCase):
    """The ASR manifest installed Whisper 'small'; Persian cuts and subtitles are better with a larger model.  The site asks for "auto" from nodes that
    list their models (agent 2.18+) and keeps the old "small" for an older agent, which would refuse "auto"."""

    def node(self, **caps):
        return SimpleNamespace(capabilities=caps)

    def test_a_node_that_lists_its_models_is_asked_for_the_best_one(self):
        self.assertEqual(captions.whisper_payload([self.node(asr_models=["large-v3-turbo", "small"])])["model"], "auto")
        self.assertEqual(captions.whisper_payload([self.node(asr_models=["small"])])["model"], "auto")

    def test_an_older_agent_keeps_getting_the_model_it_knows(self):
        self.assertEqual(captions.whisper_payload([self.node(kinds=["asr.transcribe"])])["model"], "small")
        self.assertEqual(captions.whisper_payload([])["model"], "small")
        self.assertEqual(captions.whisper_payload([self.node(asr_models=["small"]), self.node(kinds=[])])["model"], "small", "one old node is enough to stay safe")

    def test_the_rest_of_the_payload_is_unchanged_and_the_constant_is_not_mutated(self):
        p = captions.whisper_payload([self.node(asr_models=["small"])])
        self.assertEqual({k: v for k, v in p.items() if k != "model"}, {k: v for k, v in captions.WHISPER_PAYLOAD.items() if k != "model"})
        self.assertEqual(captions.WHISPER_PAYLOAD["model"], "small")


class ParkedRunLogTests(SimpleTestCase):
    """A run that waits for the processing server is parked by design: one INFO line, not an ERROR with a traceback."""

    def test_a_waiting_error_is_logged_quietly_and_a_real_failure_loudly(self):
        from apps.content import tasks_director

        log = logging.getLogger("nm.test.parked")
        waiting = captions.waiting_error()
        with self.assertLogs(log, level="INFO") as caught:
            tasks_director._log_failure(log, "Director job", 173, waiting)
        self.assertEqual([r.levelno for r in caught.records], [logging.INFO])
        self.assertIsNone(caught.records[0].exc_info)
        self.assertIn("waits for the processing server", caught.output[0])
        with self.assertLogs(log, level="INFO") as caught:
            try:
                raise ValueError("boom")
            except ValueError as exc:
                tasks_director._log_failure(log, "Director job", 174, exc)
        self.assertEqual([r.levelno for r in caught.records], [logging.ERROR])
        self.assertIsNotNone(caught.records[0].exc_info)


class NoMusicRunTests(SimpleTestCase):
    """The shop's music library is also where the site seeds its own starter tracks: a run that says «بدونِ موسیقی» must not go and look there."""

    def run_it(self, prompt="", override=None):
        from services.tests_autoedit_quality import PolishRecipeTests
        from services.tests_director import FakeAI

        t = PolishRecipeTests()
        looked = []

        def find_music(query):
            looked.append(query)
            return "audio:1"

        res = loop.run(prompt, [t.TALK], t.ctx(find_music=find_music), store=None,
                       options=loop.Options(variants=1, rounds=0, use_ai=False, preview=False, override=override or {}), call=FakeAI(fail="all"))
        return looked, res

    def test_a_normal_run_looks_in_the_library_for_music(self):
        looked, res = self.run_it()
        self.assertEqual(looked, [""])
        self.assertIn("pick_music", [s["tool"] for s in res["variants"][0]["plan"]])

    def test_the_chip_without_music_does_not(self):
        looked, res = self.run_it(override={"music": False})
        self.assertEqual(looked, [])
        self.assertNotIn("pick_music", [s["tool"] for s in res["variants"][0]["plan"]])

    def test_the_words_without_music_do_not_either(self):
        looked, _res = self.run_it("بدون موسیقی")
        self.assertEqual(looked, [])

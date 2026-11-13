"""The node acceptance run's pass/fail logic, proven on the site with no node: a correct mix passes, the old doubled mix fails, words and mattes are judged."""
import atexit
import shutil
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from services.editing import export, media_cache, selftest_autoedit as st
from services.video.ffmpeg import FFMPEG

HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
TEMP = Path(tempfile.mkdtemp(prefix="nm-autoedit-selftest-"))
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)          # the module makes its folder at import: never leave it behind


class SelftestLogicTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.media = st.make_media(TEMP / "media")

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")

    def render(self, data, name):
        out = TEMP / name
        export.render(st.build_timeline(data, self.media), out, quality="draft")
        return out

    def test_the_sample_is_heard_as_speech_where_the_person_speaks(self):
        spans = media_cache.speech_spans(self.media["speech"])
        self.assertTrue(any(s <= st.SPEECH_WINDOW[0] + 0.5 and e >= st.SPEECH_WINDOW[1] - 0.5 for s, e in spans), spans)
        self.assertFalse(any(s < 1.5 for s, e in spans), "the first seconds are open")

    def test_a_correct_render_passes_every_check(self):
        res = st.check_mix(self.render(st.mix_project(), "good.mp4"))
        self.assertTrue(res["ok"], res)
        self.assertEqual({r["key"] for r in res["checks"]}, {"file", "no_overlap", "ducking", "loudness"})

    def test_ducking_off_is_caught(self):
        data = st.mix_project()
        data["ducking"] = {"on": False}
        res = st.check_mix(self.render(data, "unducked.mp4"))
        self.assertFalse(res["ok"])
        self.assertFalse(next(r for r in res["checks"] if r["key"] == "ducking")["ok"])

    def test_the_old_doubled_mix_is_caught(self):
        out = TEMP / "doubled.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(self.media["speech"]), "-i", str(self.media["speech"]), "-filter_complex",
                        "[1:a]adelay=120|120[b];[0:a][b]amix=inputs=2:normalize=0[o]", "-map", "0:v", "-map", "[o]", "-c:v", "copy", "-c:a", "aac", str(out)],
                       check=True, capture_output=True)
        res = st.check_mix(out)
        self.assertFalse(res["ok"])
        self.assertFalse(next(r for r in res["checks"] if r["key"] == "no_overlap")["ok"])

    def test_a_missing_file_fails_with_a_reason(self):
        res = st.check_mix(TEMP / "nothing.mp4")
        self.assertFalse(res["ok"])

    def test_the_words_are_judged_on_order_time_and_content(self):
        good = [{"w": "سلام", "s": 0.1, "e": 0.5}, {"w": "به", "s": 0.6, "e": 0.7}, {"w": "همه", "s": 0.8, "e": 1.1}, {"w": "دوستان", "s": 1.2, "e": 1.8}]
        self.assertTrue(st.check_words(good, 6.0)["ok"])
        self.assertFalse(st.check_words([], 6.0)["ok"])
        self.assertFalse(st.check_words(list(reversed(good)), 6.0)["ok"], "times must rise")
        gibberish = [{"w": "الف", "s": 0.1, "e": 0.5}, {"w": "ب", "s": 0.6, "e": 0.7}, {"w": "پ", "s": 0.8, "e": 1.1}]
        self.assertFalse(st.check_words(gibberish, 6.0)["ok"], "words that are not the sentence")

    def test_the_matte_is_judged_on_size_and_length(self):
        clip = TEMP / "m.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=12:d=2", "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
        self.assertTrue(st.check_matte(clip, (320, 240), 2.0)["ok"])
        self.assertFalse(st.check_matte(clip, (640, 480), 2.0)["ok"])
        self.assertFalse(st.check_matte(TEMP / "none.mp4", (320, 240), 2.0)["ok"])

    def test_without_a_node_the_run_waits_and_the_command_says_so(self):
        with patch.object(st, "_node_online", return_value=""):
            res = st.run()
            self.assertEqual((res["state"], res["ok"]), ("waiting", None))
            out = StringIO()
            with self.assertRaises(SystemExit) as caught:
                call_command("autoedit_selftest", stdout=out)
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("waiting", out.getvalue())

    def test_a_check_that_crashes_is_a_failed_check_with_the_reason(self):
        with patch.object(st, "_node_online", return_value="n1"), patch.object(st, "run_render_mix", side_effect=RuntimeError("boom")):
            res = st.run(["render_mix"])
        self.assertEqual(res["state"], "failed")
        self.assertIn("boom", res["checks"]["render_mix"]["checks"][0]["detail"])

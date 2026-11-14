"""SRT writer (audit 2026-11-14): an always-valid timestamp and invisible right-to-left marks around Persian lines."""
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from services.video import subtitles as sub
from services.video.ffmpeg import FFMPEG

STAMP = re.compile(r"^\d{2,}:[0-5]\d:[0-5]\d,\d{3}$")
HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


class StampTests(SimpleTestCase):
    def test_rounded_milliseconds_carry_into_the_seconds(self):
        self.assertEqual(sub._stamp(2.9996), "00:00:03,000")            # was «00:00:02,1000»
        self.assertEqual(sub._stamp(3599.9999), "01:00:00,000")         # was «00:59:59,1000»
        self.assertEqual(sub._stamp(59.9995), "00:01:00,000")
        self.assertEqual(sub._stamp(0.0004), "00:00:00,000")
        self.assertEqual(sub._stamp(0.0005), "00:00:00,001")
        self.assertEqual(sub._stamp(1.5), "00:00:01,500")
        self.assertEqual(sub._stamp(3661.0), "01:01:01,000")

    def test_never_an_invalid_stamp(self):
        rnd = random.Random(7)
        values = [rnd.uniform(0, 7300) for _ in range(5000)] + [k + 0.9995 + e for k in range(0, 4000, 61) for e in (0, 1e-6, -1e-6)]
        for v in values:
            self.assertRegex(sub._stamp(v), STAMP, v)
        for odd in (-5, -0.0001, float("nan"), float("inf"), None, "x"):
            self.assertEqual(sub._stamp(odd), "00:00:00,000", odd)

    def test_stamps_never_go_backwards(self):
        a = [sub._stamp(i / 997.0) for i in range(0, 20000)]
        self.assertEqual(a, sorted(a))


class RtlTests(SimpleTestCase):
    def test_persian_lines_are_wrapped_and_latin_lines_are_not(self):
        srt = sub.to_srt([sub.Cue(1, 0.0, 2.0, "سال ۲۰۲۶ خوب بود."), sub.Cue(2, 2.0, 4.0, "Hello world"), sub.Cue(3, 4.0, 6.0, "خط اول\nNM خط دوم 2026")])
        blocks = srt.strip().split("\n\n")
        self.assertIn(sub.RLE + "سال ۲۰۲۶ خوب بود." + sub.PDF, blocks[0])
        self.assertTrue(blocks[1].endswith("\nHello world"))
        self.assertNotIn(sub.RLE, blocks[1])
        lines = blocks[2].split("\n")
        self.assertEqual(lines[2], sub.RLE + "خط اول" + sub.PDF)
        self.assertEqual(lines[3], sub.RLE + "NM خط دوم 2026" + sub.PDF)          # a Latin start must not flip the Persian line
        self.assertEqual(sub.rtl_line(sub.RLE + "x" + sub.PDF + "سلام"), sub.RLE + "x" + sub.PDF + "سلام")   # never wrapped twice
        self.assertEqual(sub.rtl_line(""), "")

    def test_the_marks_are_stripped_again_on_import(self):
        from apps.content.editor_project import parse_srt

        text = sub.to_srt([sub.Cue(1, 0.0, 2.9996, "سال ۲۰۲۶ خوب بود."), sub.Cue(2, 3.0, 5.0, "Hello")])
        lines = parse_srt(text)
        self.assertEqual([x["text"] for x in lines], ["سال ۲۰۲۶ خوب بود.", "Hello"])
        self.assertEqual(lines[0]["end"], 3.0)
        self.assertEqual(sub.strip_bidi(sub.RLE + "ab" + sub.PDF + chr(0x200f)), "ab")

    def test_the_file_keeps_its_bom_and_is_valid_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            path = sub.write_srt([sub.Cue(1, 0.0, 1.0, "سلام ۱")], Path(d) / "s.srt")
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(sub.RLE, raw.decode("utf-8-sig"))


class BurnedInTests(SimpleTestCase):
    """The marks must stay invisible when libass burns the file in: no extra glyph, but a line that starts with Latin text reads right to left."""

    def frame(self, directory, name, text):
        import numpy as np

        srt = Path(directory) / f"{name}.srt"
        srt.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n", encoding="utf-8-sig")
        out = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=540x960:r=25:d=1",
             "-vf", sub.style_filter(srt, size_pct=7) + ",format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"],
            capture_output=True, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace")[:300])
        return np.frombuffer(out.stdout, dtype=np.uint8).reshape(960, 540, 3).astype(int)

    def test_no_extra_glyph_and_the_direction_is_forced(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")
        import numpy as np

        with tempfile.TemporaryDirectory() as d:
            for text in ("سلام دنیا", "NM یک ابزار است 2026"):
                plain = self.frame(d, "plain", text)
                marked = self.frame(d, "marked", sub.rtl_line(text))
                ink_a, ink_b = int((abs(plain - 32).max(axis=2) > 60).sum()), int((abs(marked - 32).max(axis=2) > 60).sum())
                self.assertGreater(ink_a, 500, text)
                self.assertAlmostEqual(ink_b / ink_a, 1.0, delta=0.04, msg=f"{text}: the marks must not draw anything ({ink_a} vs {ink_b})")
                if text.startswith("NM"):
                    self.assertGreater(int(abs(plain - marked).max(axis=2).astype(bool).sum()), 300, "the Persian line is laid out right to left")
                else:
                    self.assertEqual(int(np.abs(plain - marked).max()), 0, "a pure Persian line looks exactly the same")

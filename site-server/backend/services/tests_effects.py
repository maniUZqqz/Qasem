"""The §23.4 effects: rotate, watermark, blur, sharpen, vignette, transition.

These are tested against **real ffmpeg**, not against the strings they build.
Every bug they had was one a string comparison would have passed:

* `boxblur=18` reads as obviously correct and fails on any region narrower
  than about 72 pixels, because the radius has to fit the chroma plane and
  that plane is half size. A face is always narrower than that.
* Two blurs in one plan both named their intermediate pad `[blurred]`, and
  ffmpeg treats the second as a redefinition.
* A region blur needs named pads at all, which `-vf` cannot express — so the
  renderer had to learn `-filter_complex`, and the filters that do *not* need
  it had to keep working.

So each case here renders a two-second clip and checks a file came out.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from services.editing import edl as edl_mod
from services.editing import tools
from services.editing.tools import ToolError
from services.video.ffmpeg import FFMPEG, VideoProcessingError, probe_duration


def _ffmpeg_missing() -> bool:
    try:
        subprocess.run([FFMPEG, "-version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return True
    return False


class EffectBuildTests(unittest.TestCase):
    """The parts that need no ffmpeg: registration, clamping, refusals."""

    def test_every_new_effect_is_registered(self):
        for key in ("rotate", "watermark", "blur_region", "sharpen",
                    "vignette", "transition"):
            self.assertIn(key, tools.TOOLS)
            self.assertIn(key, [t["key"] for t in tools.catalogue()])

    def test_an_empty_watermark_is_refused_not_rendered_blank(self):
        with self.assertRaises(ToolError):
            tools.TOOLS["watermark"].build({
                "text": "   ", "position": "br", "size": 28, "opacity": 0.5,
            })

    def test_watermark_text_is_escaped(self):
        """A colon or a quote in a shop's name ends drawtext's option list and
        takes the whole filtergraph down with it — so the text never goes inline:
        it is written to a textfile and only the placeholder sits in the graph."""
        out = tools.TOOLS["watermark"].build({
            "text": "a:b,c[d]", "position": "br", "size": 28, "opacity": 0.5,
        })
        self.assertIn("textfile=" + tools.WATERMARK_TEXTFILE, out)
        self.assertNotIn("a:b,c[d]", out)

    def test_two_regions_get_different_pad_names(self):
        build = tools.TOOLS["blur_region"].build
        base = {"width": 20, "height": 20, "strength": 6}
        first = build({**base, "x": 5, "y": 5})
        second = build({**base, "x": 60, "y": 60})
        self.assertNotEqual(first, second)
        # The same region twice is the same filter, which is the right answer
        # to asking for an identical blur twice.
        self.assertEqual(first, build({**base, "x": 5, "y": 5}))

    def test_a_region_outside_the_frame_is_refused(self):
        with self.assertRaises(ToolError):
            tools.TOOLS["blur_region"].build({
                "x": 100, "y": 0, "width": 20, "height": 20, "strength": 6,
            })

    def test_a_region_is_clamped_to_the_frame_rather_than_refused(self):
        """A model that says 90% wide at 40% from the left has the right idea
        and the wrong number."""
        out = tools.TOOLS["blur_region"].build({
            "x": 40, "y": 0, "width": 90, "height": 20, "strength": 6,
        })
        self.assertIn("crop=iw*0.6", out)

    def test_rotate_only_offers_quarter_turns(self):
        with self.assertRaises(ToolError):
            tools.validate_one({"tool": "rotate", "params": {"degrees": "45"}})

    def test_an_out_of_range_strength_is_clamped_and_noted(self):
        operation = tools.validate_one({
            "tool": "blur_region",
            "params": {"x": 0, "y": 0, "width": 20, "height": 20, "strength": 99},
        })
        self.assertEqual(operation.params["strength"], 10)
        self.assertTrue(operation.notes)


@unittest.skipIf(_ffmpeg_missing(), "ffmpeg is not installed on this machine")
class EffectRenderTests(unittest.TestCase):
    """Each effect, through a real render."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.source = cls.tmp / "source.mp4"
        subprocess.run(
            [FFMPEG, "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", str(cls.source)],
            capture_output=True, check=True,
        )

    def render(self, raw, name):
        operations, refused = tools.validate(raw, duration=3.0, has_audio=True)
        self.assertEqual(refused, [])
        plan = edl_mod.build(self.source, operations, duration=3.0, has_audio=True)
        out = self.tmp / f"{name}.mp4"
        edl_mod.render(plan, out)
        self.assertTrue(out.exists() and out.stat().st_size > 0)
        return out

    def test_rotate(self):
        self.render([{"tool": "rotate", "params": {"degrees": "90"}}], "rotate")

    def test_watermark(self):
        self.render(
            [{"tool": "watermark", "params": {"text": "آپ‌مارکت: تست"}}], "watermark",
        )

    def test_sharpen_and_vignette(self):
        self.render(
            [{"tool": "sharpen", "params": {"amount": 1.0}},
             {"tool": "vignette", "params": {"strength": 0.5}}],
            "sharpen_vignette",
        )

    def test_transition(self):
        self.render(
            [{"tool": "transition", "params": {"at": 1.5, "duration": 0.4}}],
            "transition",
        )

    def test_blur_region(self):
        self.render(
            [{"tool": "blur_region",
              "params": {"x": 10, "y": 10, "width": 30, "height": 30}}],
            "blur",
        )

    def test_a_region_too_small_for_a_fixed_radius_still_renders(self):
        """The original bug: a face-sized box is narrower than the chroma
        plane needs for an absolute radius, so every real use failed."""
        self.render(
            [{"tool": "blur_region",
              "params": {"x": 5, "y": 5, "width": 3, "height": 3}}],
            "tiny_blur",
        )

    def test_two_blurs_in_one_plan(self):
        self.render(
            [{"tool": "blur_region",
              "params": {"x": 5, "y": 5, "width": 20, "height": 20}},
             {"tool": "blur_region",
              "params": {"x": 60, "y": 60, "width": 20, "height": 20}}],
            "two_blurs",
        )

    def test_a_blur_survives_a_cut(self):
        """The cut moves the graph onto `-filter_complex`; the audio has to
        come with it or the output has a video track and nothing else."""
        out = self.render(
            [{"tool": "cut", "params": {"start": 1, "end": 2}},
             {"tool": "blur_region",
              "params": {"x": 10, "y": 10, "width": 30, "height": 30}}],
            "blur_cut",
        )
        self.assertLess(probe_duration(out), 3.0)

    def test_the_plain_filters_did_not_move_to_filter_complex(self):
        """Everything without named pads must stay on the simple path."""
        operations, _ = tools.validate(
            [{"tool": "brightness", "params": {"amount": 0.1}}],
            duration=3.0, has_audio=True,
        )
        plan = edl_mod.build(self.source, operations, duration=3.0, has_audio=True)
        self.assertFalse(any("[" in f for f in plan.video_filters))

    def test_all_of_them_together(self):
        self.render(
            [{"tool": "rotate", "params": {"degrees": "180"}},
             {"tool": "vignette", "params": {"strength": 0.3}},
             {"tool": "sharpen", "params": {"amount": 0.6}},
             {"tool": "blur_region",
              "params": {"x": 10, "y": 10, "width": 25, "height": 25}},
             {"tool": "watermark", "params": {"text": "NM"}}],
            "everything",
        )

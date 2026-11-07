"""Round 5 clip tools in the export: «لایهٔ تنظیم» (adjustment layer), «کلیدِ روشنایی» (luma key) and «اصلاحِ لنز» (lens correction)."""
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings

from services.editing import compose, export
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG

from .tests_editor_modes import make_video

TEMP = tempfile.mkdtemp(prefix="nm-clipfx-")
HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


def media(i=0, at=0.0, end=2.0, **extra):
    return {"id": f"c{i}", "type": "media", "ref": "x", "label": "x", "kind": "video", "at": at, "start": 0, "end": end, "src": 3, "opacity": 1, "x": 0, "y": 0,
            "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": False, "has_audio": False, "effects": [],
            "transition": None, **extra}


def layer(at=0.0, end=2.0, **extra):
    """`end` is the layer's DURATION (a layer is like a still: it has no source range, `start` is always 0)."""
    return {"id": "adj", "type": "adjust", "ref": "", "label": "لایهٔ تنظیم", "kind": "video", "adjust": True, "at": at, "start": 0, "end": end, "opacity": 1, "x": 0, "y": 0,
            "width": 1, "height": 1, **extra}


def project(*tracks, w=320, h=180):
    return {"format": {"width": w, "height": h, "fps": 12, "preset": "reel"}, "tracks": [{"id": f"t{i}", "kind": "video", "name": "v", "clips": c} for i, c in enumerate(tracks)],
            "global_ops": []}


def build(data, src="/x.mp4"):
    info = {"path": src, "kind": "video", "has_audio": False, "duration": 3.0, "width": 320, "height": 180}

    def resolve(ref):
        if not ref:
            raise tl.TimelineError("ref خالی")
        return dict(info)
    return tl.from_project(data, resolve)


class CleanTests(SimpleTestCase):
    def test_adjustment_layer_needs_no_source_and_keeps_its_colour_and_effects(self):
        t = build(project([media()], [layer(color={"exposure": 0.4})]))
        adj = t.tracks[1].clips[0]
        self.assertTrue(adj.adjust)
        self.assertEqual(adj.kind, "image")
        self.assertEqual(adj.source, "")
        self.assertAlmostEqual(adj.length, 2.0, places=2)
        self.assertTrue(adj.color)

    def test_adjust_flag_only_counts_when_it_is_exactly_true_and_never_has_a_transition(self):
        t = build(project([media()], [layer(adjust="yes", ref="x")]))
        self.assertFalse(t.tracks[1].clips[0].adjust)
        t = build(project([media()], [layer(transition={"kind": "fade", "duration": 1})]))
        self.assertIsNone(t.tracks[1].clips[0].transition)

    def test_luma_key_is_clamped_and_off_means_absent(self):
        t = build(project([media(luma={"on": True, "mode": "bright", "tolerance": 9, "softness": -3})]))
        self.assertEqual(t.tracks[0].clips[0].luma, {"on": True, "mode": "bright", "tolerance": 1.0, "softness": 0.0})
        t = build(project([media(luma={"on": False, "tolerance": 0.3})]))
        self.assertFalse(t.tracks[0].clips[0].luma)
        t = build(project([media(luma={"on": True, "mode": "weird"})]))
        self.assertEqual(t.tracks[0].clips[0].luma["mode"], "dark")

    def test_lens_is_clamped_and_a_flat_lens_is_dropped(self):
        t = build(project([media(lens={"k1": 5, "k2": -5})]))
        self.assertEqual(t.tracks[0].clips[0].lens, {"k1": 1.0, "k2": -1.0})
        t = build(project([media(lens={"k1": 0.001, "k2": 0})]))
        self.assertFalse(t.tracks[0].clips[0].lens)
        t = build(project([media(lens="bad")]))
        self.assertFalse(t.tracks[0].clips[0].lens)


class AnchorCleanTests(SimpleTestCase):
    def test_anchor_is_clamped_and_the_centre_is_dropped(self):
        t = build(project([media(anchor={"x": 3, "y": -3})]))
        self.assertEqual(t.tracks[0].clips[0].anchor, {"x": 1.0, "y": -1.0})
        t = build(project([media(anchor={"x": 0.001, "y": 0})]))
        self.assertFalse(t.tracks[0].clips[0].anchor)

    def test_the_graph_moves_the_centre_by_the_anchor_term_only_when_turning(self):
        g = compose.build_graph(build(project([media(anchor={"x": -0.5, "y": -0.5}, scale=2.0)])), need_base=True).graph
        self.assertIn("cos(", g)
        self.assertIn("sin(", g)
        g = compose.build_graph(build(project([media(anchor={"x": -0.5, "y": -0.5})])), need_base=True).graph
        self.assertNotIn("cos(", g)


class TrackMatteCleanTests(SimpleTestCase):
    def test_track_matte_is_cleaned_and_off_means_absent(self):
        t = build(project([media(track_matte={"mode": "alpha", "invert": True})]))
        self.assertEqual(t.tracks[0].clips[0].track_matte, {"mode": "alpha", "invert": True})
        t = build(project([media(track_matte={"mode": "weird"})]))
        self.assertEqual(t.tracks[0].clips[0].track_matte, {"mode": "luma", "invert": False})
        t = build(project([media(track_matte={"on": False})]))
        self.assertFalse(t.tracks[0].clips[0].track_matte)
        t = build(project([media(track_matte="x")]))
        self.assertFalse(t.tracks[0].clips[0].track_matte)

    def test_the_graph_uses_the_upper_clip_as_the_matte_and_does_not_draw_it(self):
        data = project([media(0, track_matte={"mode": "luma", "invert": False})], [media(1)])
        t = build(data)
        b = compose.Builder(t)
        b.build_video()
        g = ";".join(b.parts)
        self.assertIn("alphaextract", g)
        self.assertIn("blend=all_mode=multiply", g)
        self.assertIn("format=gray", g)
        self.assertEqual(len(b.matte_used), 1)
        self.assertEqual(g.count("overlay="), 3, g)     # a on its canvas, m on its canvas, the merge — and nothing for m on its own

    def test_alpha_mode_and_invert(self):
        data = project([media(0, track_matte={"mode": "alpha", "invert": True})], [media(1)])
        b = compose.Builder(build(data))
        b.build_video()
        g = ";".join(b.parts)
        self.assertNotIn("format=gray", g)
        self.assertIn("alphaextract,negate", g)

    def test_without_an_overlapping_clip_above_the_matte_is_ignored_with_a_note(self):
        data = project([media(0, end=2.0, track_matte={"mode": "luma", "invert": False})], [media(1, at=5.0, end=1.0)])
        b = compose.Builder(build(data))
        b.build_video()
        self.assertEqual(len(b.matte_used), 0)
        self.assertTrue(any("ماتِ ترک" in n for n in b.notes), b.notes)
        self.assertNotIn("alphaextract", ";".join(b.parts))

    def test_two_clips_never_share_one_matte(self):
        data = project([media(0, at=0, end=1, track_matte={"mode": "luma", "invert": False}), media(2, at=1, end=1, track_matte={"mode": "luma", "invert": False})], [media(1, at=0, end=2)])
        b = compose.Builder(build(data))
        b.build_video()
        self.assertEqual(len(b.matte_used), 1)


class GraphTests(SimpleTestCase):
    def graph(self, data):
        return compose.build_graph(build(data), need_base=True).graph

    def test_a_layer_splits_what_is_below_and_corrects_one_copy_only_for_its_duration(self):
        g = self.graph(project([media()], [layer(at=0.5, end=1.0, color={"exposure": 0.4})]))
        self.assertIn("split=2", g)
        self.assertIn("overlay=x=0:y=0:enable='between(t,0.500,1.500)'", g)
        self.assertEqual(g.count("-i"), 0)

    def test_a_layer_at_partial_opacity_blends(self):
        g = self.graph(project([media()], [layer(opacity=0.5, color={"exposure": 0.4})]))
        self.assertIn("blend=all_mode=normal:all_opacity=0.500", g)

    def test_an_empty_layer_changes_nothing(self):
        plain = self.graph(project([media()]))
        with_empty = self.graph(project([media()], [layer()]))
        self.assertEqual(with_empty.count("split"), plain.count("split"))

    def test_luma_key_and_lens_filters_appear(self):
        g = self.graph(project([media(luma={"on": True, "mode": "dark", "tolerance": 0.2, "softness": 0.1}, lens={"k1": -0.3, "k2": 0.1})]))
        self.assertIn("lumakey=threshold=0:tolerance=0.2:softness=0.1", g)
        self.assertIn("lenscorrection=cx=0.5:cy=0.5:k1=-0.3:k2=0.1", g)
        g = self.graph(project([media(luma={"on": True, "mode": "bright", "tolerance": 0.2, "softness": 0.1})]))
        self.assertIn("lumakey=threshold=1:", g)


def frame(path, t=0.5):
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(36, 64, 3).astype(float)


@override_settings(MEDIA_ROOT=TEMP)
class RenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "m.mp4", size="320x180", seconds=3, audio=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")

    def render(self, data, name):
        t = build(data, str(self.src))
        return export.render(t, Path(TEMP) / name, quality="draft")

    def test_the_layer_darkens_only_its_own_stretch_of_the_whole_picture_below(self):
        data = project([media(end=2.0)], [layer(at=1.0, end=1.0, color={"exposure": -0.8})])
        out = self.render(data, "adj.mp4")
        before, after = frame(out, 0.4), frame(out, 1.5)
        plain = self.render(project([media(end=2.0)]), "plain.mp4")
        self.assertLess(float(np.mean(np.abs(before - frame(plain, 0.4)))), 6.0, "before the layer the picture is untouched")
        self.assertLess(float(after.mean()), float(frame(plain, 1.5).mean()) - 20, "inside the layer it is darker")

    def test_a_layer_reaches_down_through_every_lower_track(self):
        data = project([media(end=2.0)], [media(1, at=0.0, end=2.0, x=0.0, y=0.0, width=0.5, height=0.5)], [layer(color={"exposure": -0.8})])
        out = self.render(data, "adj2.mp4")
        plain = self.render(project([media(end=2.0)], [media(1, at=0.0, end=2.0, x=0.0, y=0.0, width=0.5, height=0.5)]), "plain2.mp4")
        self.assertLess(float(frame(out, 1.0).mean()), float(frame(plain, 1.0).mean()) - 20)

    def test_lens_correction_changes_the_picture_and_keeps_the_size(self):
        out = self.render(project([media(lens={"k1": -0.4, "k2": 0.0})]), "lens.mp4")
        plain = self.render(project([media()]), "nolens.mp4")
        self.assertGreater(float(np.mean(np.abs(frame(out, 0.5) - frame(plain, 0.5)))), 4.0)

    def test_luma_key_makes_the_dark_parts_see_through(self):
        base = media(0, end=2.0, flip_h=True)
        top = media(1, end=2.0, luma={"on": True, "mode": "dark", "tolerance": 0.5, "softness": 0.0})
        data = project([base], [top])
        out = self.render(data, "luma.mp4")
        plain = self.render(project([base], [media(1, end=2.0)]), "noluma.mp4")
        self.assertGreater(float(np.mean(np.abs(frame(out, 0.5) - frame(plain, 0.5)))), 0.5)

    def red(self):
        path = Path(TEMP) / "red.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=3:r=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
        return path

    def test_scaling_about_a_corner_anchor_keeps_that_corner_in_place(self):
        src = self.red()
        box = dict(x=0.25, y=0.25, width=0.5, height=0.5, scale=2.0)
        centre = export.render(build(project([media(**box)]), str(src)), Path(TEMP) / "a0.mp4", quality="draft")
        corner = export.render(build(project([media(**box, anchor={"x": -0.5, "y": -0.5})]), str(src)), Path(TEMP) / "a1.mp4", quality="draft")
        top_left = (4, 4)      # (column, row) of the 64×36 frame, i.e. about 6 % from the corner
        self.assertGreater(frame(centre, 0.5)[top_left[1], top_left[0], 0], 150, "scaling about the centre reaches the top-left")
        self.assertLess(frame(corner, 0.5)[top_left[1], top_left[0], 0], 60, "scaling about the top-left corner never goes above it")
        self.assertGreater(frame(corner, 0.5)[30, 58, 0], 150, "...but it does cover the bottom-right")


@override_settings(MEDIA_ROOT=TEMP)
class TrackMatteRenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "mt.mp4", size="320x180", seconds=3, audio=False)
            cls.half = Path(TEMP) / "half.mp4"      # left half white, right half black
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=3:r=12,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.half)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")

    def render(self, matte, name):
        data = project([media(0, end=2.0, track_matte=matte)], [media(1, end=2.0)])
        info = {"0": str(self.src), "1": str(self.half)}

        def resolve(ref):
            return {"path": info[ref], "kind": "video", "has_audio": False, "duration": 3.0, "width": 320, "height": 180}
        for t, ref in zip(data["tracks"], ("0", "1")):
            for c in t["clips"]:
                c["ref"] = ref
        return export.render(tl.from_project(data, resolve), Path(TEMP) / name, quality="draft")

    def test_the_lower_clip_shows_only_where_the_matte_is_bright(self):
        out = self.render({"mode": "luma", "invert": False}, "tm1.mp4")
        f = frame(out, 0.5)
        self.assertGreater(float(f[18, 8].mean()), 40, "left half (matte white) shows the picture")
        self.assertLess(float(f[18, 56].mean()), 12, "right half (matte black) is the black base")

    def test_invert_swaps_the_halves(self):
        out = self.render({"mode": "luma", "invert": True}, "tm2.mp4")
        f = frame(out, 0.5)
        self.assertLess(float(f[18, 8].mean()), 12)
        self.assertGreater(float(f[18, 56].mean()), 40)

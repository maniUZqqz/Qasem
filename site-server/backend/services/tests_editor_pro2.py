"""Editor pro 2: shapes and stickers, .cube LUTs, free-form masks (with feather and motion), long keyframe paths, titles that
follow a motion track, nested sequences, background-removal mattes, motion tracking (OpenCV) and multicam sync.

String-level tests are fast; the render tests run the real ffmpeg on tiny synthetic clips and look at the pixels."""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from services.editing import compose, export, keyframes, luts, masks, multicam, shapes, stickers, titles, tracking
from services.editing import timeline as T
from services.editing.errors import TimelineError
from services.tests_editor_pro import ffexpr, near, pixel
from services.tests_timeline_project import HAVE_FFMPEG, make_clip, project, resolver, sh, stats
from services.video.ffmpeg import FFMPEG

try:
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    HAVE_CV = True
except Exception:  # noqa: BLE001
    HAVE_CV = False

MEDIA = tempfile.mkdtemp(prefix="nm-pro2-media-")


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


def cube_text(size=3, fn=lambda r, g, b: (r, g, b), title="t"):
    rows = []
    for b in range(size):
        for g in range(size):
            for r in range(size):
                rows.append(" ".join(f"{v:.6f}" for v in fn(r / (size - 1), g / (size - 1), b / (size - 1))))
    return f'TITLE "{title}"\nLUT_3D_SIZE {size}\n' + "\n".join(rows) + "\n"


# ------------------------------------------------------------------ shapes & stickers

@override_settings(MEDIA_ROOT=MEDIA)
class ShapeTests(SimpleTestCase):
    def test_clean_clamps_and_defaults(self):
        c = shapes.clean({"shape": "evil", "fill": "red", "stroke_w": 99, "points": 1, "inner": 5})
        self.assertEqual((c["shape"], c["fill"], c["stroke_w"], c["points"], c["inner"]), ("rect", "#ff3d71", 20.0, 3, 0.9))
        self.assertEqual(shapes.clean({"shape": "star"})["inner"], 0.45)
        self.assertEqual(shapes.clean({"shape": "burst"})["inner"], 0.78)
        self.assertEqual(sorted(shapes.SHAPE_TITLES), sorted(shapes.SHAPES))

    def test_the_outline_is_a_closed_polygon_inside_the_unit_box(self):
        for key in shapes.SHAPES:
            for item in shapes.unit_shapes(shapes.clean({"shape": key})):
                if item[0] != "poly":
                    continue
                pts = item[1]
                self.assertGreaterEqual(len(pts), 3, key)
                self.assertTrue(all(-1e-9 <= x <= 1 + 1e-9 and -1e-9 <= y <= 1 + 1e-9 for x, y in pts), key)
        heart = shapes.unit_shapes(shapes.clean({"shape": "heart"}))[0][1]
        xs, ys = [p[0] for p in heart], [p[1] for p in heart]
        self.assertAlmostEqual(min(xs), 0, places=6)
        self.assertAlmostEqual(max(ys), 1, places=6)
        self.assertEqual(len(shapes.unit_shapes(shapes.clean({"shape": "star", "points": 6}))[0][1]), 12)

    def test_png_has_alpha_fill_stroke_and_a_transparent_corner(self):
        from PIL import Image

        out = shapes.render_png(shapes.clean({"shape": "ellipse", "fill": "#ff0000", "stroke": "#0000ff", "stroke_w": 8}), 200, 100,
                                Path(MEDIA) / "e.png")
        im = Image.open(out).convert("RGBA")
        self.assertEqual(im.size, (200, 100))
        self.assertEqual(im.getpixel((2, 2))[3], 0, "a corner outside the ellipse is transparent")
        r, g, b, a = im.getpixel((100, 50))
        self.assertTrue(r > 240 and g < 20 and b < 20 and a == 255, (r, g, b, a))
        edge = im.getpixel((100, 4))
        self.assertTrue(edge[2] > 150 and edge[0] < 100, f"the stroke is blue at the top edge: {edge}")

    def test_gradient_fill_and_opacity(self):
        from PIL import Image

        out = shapes.render_png(shapes.clean({"shape": "rect", "fill": "#000000", "fill2": "#ffffff", "angle": 0}), 100, 20, Path(MEDIA) / "g.png")
        im = Image.open(out).convert("RGBA")
        self.assertLess(im.getpixel((3, 10))[0], 40)
        self.assertGreater(im.getpixel((96, 10))[0], 215)
        half = Image.open(shapes.render_png(shapes.clean({"shape": "rect", "fill_opacity": 0.5}), 40, 40, Path(MEDIA) / "h.png")).convert("RGBA")
        self.assertTrue(120 <= half.getpixel((20, 20))[3] <= 135)

    def test_render_cached_is_made_once_and_the_cache_is_bounded(self):
        spec = shapes.clean({"shape": "star"})
        a = shapes.render_cached(spec, 120, 120)
        stamp = a.stat().st_mtime_ns
        b = shapes.render_cached(spec, 120, 120)
        self.assertEqual(a, b)
        self.assertEqual(b.stat().st_size, a.stat().st_size)
        self.assertGreaterEqual(b.stat().st_mtime_ns, stamp)

    def test_catalogue_names(self):
        self.assertEqual([s["key"] for s in shapes.catalogue()["shapes"]], list(shapes.SHAPES))


@override_settings(MEDIA_ROOT=MEDIA)
class StickerTests(SimpleTestCase):
    def test_badges_and_emoji_are_drawn_as_512_png_with_alpha(self):
        from PIL import Image

        have = {s["key"] for s in stickers.available()}
        self.assertIn("arrow_right", have)
        for key in ("arrow_right", "triangle_warn") + (("sale",) if "sale" in have else ()) + (("fire",) if "fire" in have else ()):
            im = Image.open(stickers.path_of(key)).convert("RGBA")
            self.assertEqual(im.size, (512, 512), key)
            self.assertEqual(im.getpixel((2, 2))[3], 0, f"{key}: a corner is transparent")
            self.assertGreater(sum(1 for a in im.getchannel("A").getdata() if a > 200), 4000, f"{key}: something is drawn")

    def test_unknown_or_hostile_keys_are_refused(self):
        for bad in ("nope", "../x", "a b", ""):
            with self.assertRaises(TimelineError):
                stickers.path_of(bad)

    def test_a_persian_badge_has_text_pixels_in_a_different_colour_than_its_body(self):
        from PIL import Image

        if "sale" not in {s["key"] for s in stickers.available()}:
            self.skipTest("libraqm نیست")
        im = Image.open(stickers.path_of("sale")).convert("RGBA")
        white = sum(1 for p in im.getdata() if p[3] > 200 and p[0] > 235 and p[1] > 235 and p[2] > 235)
        red = sum(1 for p in im.getdata() if p[3] > 200 and p[0] > 200 and p[1] < 60)
        self.assertGreater(white, 1500, "white text/stroke")
        self.assertGreater(red, 30000, "the red burst")


# ------------------------------------------------------------------ LUTs

@override_settings(MEDIA_ROOT=MEDIA)
class LutTests(SimpleTestCase):
    def test_parse_accepts_a_cube_and_refuses_the_broken_ones_in_persian(self):
        meta = luts.parse(cube_text(5, title="film"))
        self.assertEqual((meta["size"], meta["title"], meta["table"].shape), (5, "film", (125, 3)))
        for bad, word in ((cube_text(3).replace("LUT_3D_SIZE 3", "LUT_1D_SIZE 3"), "یک‌بعدی"), (cube_text(3).replace("LUT_3D_SIZE 3", "LUT_3D_SIZE 70"), "اندازهٔ"),
                          ("TITLE x\nLUT_3D_SIZE 2\n0 0 0\n1 1 1\n", "ردیف"), (cube_text(2) + "0.1 0.2\n", "نادرست"),
                          (cube_text(2).replace("LUT_3D_SIZE 2", "LUT_3D_SIZE 2\nDOMAIN_MIN 1 1 1\nDOMAIN_MAX 0 0 0"), "DOMAIN")):
            with self.assertRaises(TimelineError, msg=word) as ctx:
                luts.parse(bad)
            self.assertIn(word, str(ctx.exception))

    def test_store_lists_removes_and_dedupes(self):
        data = cube_text(3, title="warm").encode()
        a = luts.store(7, data)
        b = luts.store(7, data)
        self.assertEqual(a["key"], b["key"])
        self.assertEqual([r["key"] for r in luts.listing(7)], [a["key"]])
        self.assertTrue(luts.path_of(7, a["key"]).is_file())
        self.assertIsNone(luts.path_of(7, "../etc/passwd"))
        self.assertIsNone(luts.path_of(8, a["key"]), "another shop cannot read it")
        with self.assertRaises(TimelineError):
            luts.store(7, b"x" * 20_000_000)
        self.assertTrue(luts.remove(7, a["key"]))
        self.assertEqual(luts.listing(7), [])

    def test_blended_cube_is_halfway_between_identity_and_the_lut(self):
        invert = Path(MEDIA) / "invert.cube"
        invert.write_text(cube_text(3, fn=lambda r, g, b: (1 - r, 1 - g, 1 - b)))
        half = luts.blended(invert, 0.5)
        meta = luts.parse(half.read_text())
        # the red-fastest order: row 1 is (r=0.5, g=0, b=0): identity (0.5,0,0) blended with (0.5,1,1) = (0.5, 0.5, 0.5)
        self.assertAlmostEqual(float(meta["table"][1][1]), 0.5, places=4)
        self.assertEqual(luts.blended(invert, 1.0), invert)
        self.assertEqual(luts.blended(invert, 0.5), half, "made once")


@override_settings(MEDIA_ROOT=MEDIA)
class RealLutRenderTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        cls.dir = Path(tempfile.mkdtemp(prefix="nm-lut-"))
        cls.red = make_clip(cls.dir / "red.mp4", seconds=2, audio=False, color="0xc82020")
        cls.invert = cls.dir / "invert.cube"
        cls.invert.write_text(cube_text(17, fn=lambda r, g, b: (1 - r, 1 - g, 1 - b)))

    @classmethod
    def tearDownClass(cls):
        if HAVE_FFMPEG:
            shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def render(self, amount):
        table = {"v": {"path": str(self.red), "kind": "video", "has_audio": False, "duration": 2.0},
                 "lut:k": {"path": str(self.invert), "kind": "lut"}}
        data = project({"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 1.5, "lut": {"key": "k", "amount": amount}}]})
        line = T.from_project(data, resolver(table))
        out = self.dir / f"o{amount}.mp4"
        export.render(line, out, quality="draft")
        return out

    def test_a_lut_changes_the_picture_and_amount_blends_it(self):
        full = pixel(self.render(1.0), 0.5, 100, 100)
        self.assertTrue(near(full, (0x37, 0xdf, 0xdf), 30), f"inverted red (200,32,32) -> (55,223,223): {full}")
        half = pixel(self.render(0.5), 0.5, 100, 100)
        self.assertTrue(abs(half[0] - 128) < 40 and abs(half[1] - 128) < 40, f"halfway is grey-ish: {half}")
        plain = pixel(self.render(0.0), 0.5, 100, 100)
        self.assertTrue(near(plain, (200, 32, 32), 30), f"amount 0 leaves the colour: {plain}")

    def test_a_missing_lut_is_a_clear_error(self):
        data = project({"kind": "video", "clips": [{"ref": "v", "at": 0, "end": 1, "lut": {"key": "gone"}}]})
        with self.assertRaises(TimelineError):
            T.from_project(data, resolver({"v": {"path": str(self.red), "kind": "video", "has_audio": False, "duration": 2.0}}))


# ------------------------------------------------------------------ keyframe tree + title path

class LongKeyframePathTests(SimpleTestCase):
    def test_a_long_path_nests_shallowly_and_equals_value_at(self):
        keys = [{"t": round(i * 0.1, 3), "v": round(0.5 + 0.4 * math.sin(i / 3), 4), "e": "linear"} for i in range(90)]
        clean = keyframes.clean_keys(keys, -2, 2)
        self.assertEqual(len(clean), 90, "90 keys survive (the limit is no longer 24)")
        expr = keyframes.expr(clean, 0.0, "t")
        depth = max(sum(1 for ch in expr[:i] if ch == "(") - sum(1 for ch in expr[:i] if ch == ")") for i in range(0, len(expr), 7))
        self.assertLess(depth, 40, "a chain of 90 if() would nest 180 deep")
        for t in (-1, 0, 0.05, 0.1, 1.234, 4.4, 8.85, 8.9, 20):
            self.assertAlmostEqual(ffexpr(expr, t=t), keyframes.value_at(clean, t, 0.0), places=3, msg=t)

    def test_short_paths_keep_the_old_chain_shape(self):
        keys = [{"t": 0, "v": 0, "e": "linear"}, {"t": 1, "v": 1, "e": "ease_in"}, {"t": 2, "v": 0.5, "e": "linear"}]
        for t in (0, 0.5, 1, 1.5, 2, 3):
            self.assertAlmostEqual(ffexpr(keyframes.expr(keys, 0, "t"), t=t), keyframes.value_at(keys, t, 0), places=4)


class TitlePathTests(SimpleTestCase):
    PATH = [{"t": 0, "dx": 0.0, "dy": 0.0}, {"t": 1, "dx": 0.2, "dy": 0.1}, {"t": 2, "dx": 0.2, "dy": 0.3}]

    def test_clean_keeps_a_sorted_clamped_path_and_drops_a_lone_point(self):
        c = titles.clean({"text": "سلام", "duration": 2, "path": [{"t": 2, "dx": 9, "dy": 0}, {"t": 0, "dx": 0, "dy": 0}, "x"]})
        self.assertEqual([p["t"] for p in c["path"]], [0.0, 2.0])
        self.assertEqual(c["path"][1]["dx"], 2.0)
        self.assertEqual(titles.clean({"text": "x", "path": [{"t": 0, "dx": 0, "dy": 0}]})["path"], [])
        self.assertEqual(titles.path_at(self.PATH, 0.5), (0.1, 0.05))
        self.assertEqual(titles.path_at(self.PATH, 5), (0.2, 0.3))

    def test_the_ass_follows_the_path_with_move_segments(self):
        item = {"text": "برچسب", "at": 0, "duration": 2, "x": 0.5, "y": 0.5, "path": self.PATH, "box": False}
        ass = titles.build_ass([item], 400, 300)
        moves = [ln for ln in ass.splitlines() if ln.startswith("Dialogue") and "\\move(" in ln]
        self.assertGreaterEqual(len(moves), 2, "one \\move per stretch between the path's points")
        # the first stretch starts at the anchor (200, 150) and ends 0.2 W right / 0.1 H down (280, 180)
        first = moves[0]
        self.assertIn("\\move(200,150,280,180", first.replace(" ", ""))
        still = titles.build_ass([{**item, "path": []}], 400, 300)
        self.assertNotIn("\\move(", still)

    def test_a_cut_title_keeps_the_right_part_of_its_path(self):
        line = T.Timeline(width=400, height=300, fps=25, tracks=[T.Track(kind="text", clips=[T.TextClip(
            text="x", at=0, duration=2, spec=titles.clean({"text": "x", "duration": 2, "path": self.PATH}))])])
        part = T.window(line, 1.0, 2.0)
        path = part.tracks[0].clips[0].spec["path"]
        self.assertEqual(path[0], {"t": 0.0, "dx": 0.2, "dy": 0.1})
        self.assertEqual(path[-1]["t"], 1.0)


# ------------------------------------------------------------------ real renders

@override_settings(MEDIA_ROOT=MEDIA)
class RealPro2RenderTests(SimpleTestCase):
    counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        cls.dir = Path(tempfile.mkdtemp(prefix="nm-pro2-"))
        cls.red = make_clip(cls.dir / "red.mp4", seconds=4, audio=False, color="red")
        cls.blue = make_clip(cls.dir / "blue.mp4", seconds=4, audio=False, color="blue")
        cls.gray = make_clip(cls.dir / "gray.mp4", seconds=4, audio=False, color="0x808080")
        cls.tone = make_clip(cls.dir / "tone.mp4", seconds=4, audio=True, color="0x303030", freq=440)
        cls.redblue = cls.dir / "redblue.mp4"        # 2 s red then 2 s blue
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=25:d=2", "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=25:d=2",
           "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.redblue))
        cls.halfmatte = cls.dir / "halfmatte.mp4"    # white on the left half, black on the right half (a 6 fps matte)
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=6:d=4", "-vf", "drawbox=x=0:y=0:w=80:h=120:color=white:t=fill,format=gray",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.halfmatte))

    @classmethod
    def tearDownClass(cls):
        if HAVE_FFMPEG:
            shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def table(self):
        d = lambda p, **kw: {"path": str(p), "kind": "video", "has_audio": False, "duration": 4.0, "width": 320, "height": 240, **kw}  # noqa: E731
        return {"red": d(self.red), "blue": d(self.blue), "gray": d(self.gray), "rb": d(self.redblue),
                "tone": d(self.tone, has_audio=True),
                "matte:m1": {"path": str(self.halfmatte), "kind": "matte", "s0": 0.0}}

    def render(self, *tracks, sequences=None, **fmt):
        data = project(*tracks, **fmt)
        if sequences:
            data["sequences"] = sequences
        line = T.from_project(data, resolver(self.table()))
        RealPro2RenderTests.counter += 1
        out = self.dir / f"o{RealPro2RenderTests.counter}.mp4"
        export.render(line, out, quality="draft")
        return out, line

    def clip(self, ref, at=0, start=0, end=3, **kw):
        return {"ref": ref, "at": at, "start": start, "end": end, **kw}

    # ----------------------------------------------------------- shapes
    def test_a_shape_clip_is_drawn_on_top_and_moves_like_a_picture(self):
        shape = {"shape": "ellipse", "fill": "#ff0000"}
        sc = self.clip("shape", end=2, x=0.35, y=0.35, width=0.3, height=0.3, shape=shape, kf={"px": [{"t": 0, "v": -0.25, "e": "linear"}, {"t": 2, "v": 0.25, "e": "linear"}]})
        out, line = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [sc]})
        self.assertEqual(line.tracks[1].clips[0].kind, "image")
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (255, 0, 0), 60), "the ellipse is at the centre at t=1")
        self.assertTrue(near(pixel(out, 1.0, 160 - 55, 120 - 55), (0, 0, 255), 40), "outside the ellipse (its corner) the base shows")
        self.assertTrue(near(pixel(out, 1.9, 160 + 70, 120), (255, 0, 0), 70), "it moved right")

    def test_a_sticker_is_a_plain_image_ref(self):
        png = stickers.path_of("arrow_right")
        table = self.table()
        table["sticker:arrow_right"] = {"path": str(png), "kind": "image", "has_audio": False, "duration": 0.0}
        data = project({"kind": "video", "clips": [self.clip("gray", end=2)]},
                       {"kind": "video", "clips": [{"ref": "sticker:arrow_right", "at": 0, "start": 0, "end": 2, "x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5, "fit": "stretch"}]})
        out = self.dir / "sticker.mp4"
        export.render(T.from_project(data, resolver(table)), out, quality="draft")
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (0xf9, 0x73, 0x16), 60), pixel(out, 1.0, 160, 120))
        self.assertTrue(near(pixel(out, 1.0, 20, 20), (128, 128, 128), 30))

    # ----------------------------------------------------------- masks
    def test_a_bezier_mask_cuts_the_layer_and_feather_softens_the_edge(self):
        left_half = [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}, {"x": 0.0, "y": 1.0}]
        hard = self.clip("red", end=2, fit="stretch", mask={"shape": "bezier", "points": left_half, "feather": 0})
        out, line = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [hard]})
        self.assertTrue(line.tracks[1].clips[0].mask_file.endswith(".png"))
        self.assertTrue(near(pixel(out, 1.0, 60, 120), (255, 0, 0), 50), "left of the cut: red")
        self.assertTrue(near(pixel(out, 1.0, 260, 120), (0, 0, 255), 50), "right of the cut: the blue below")
        soft = self.clip("red", end=2, fit="stretch", mask={"shape": "bezier", "points": left_half, "feather": 0.3})
        out2, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [soft]})
        mid = pixel(out2, 1.0, 160, 120)
        self.assertTrue(mid[0] > 60 and mid[2] > 60, f"feathered edge is a blend: {mid}")

    def test_a_curved_handle_makes_a_round_hole(self):
        c = 0.5523 * 0.4                                   # a circle of radius 0.4 from four Bézier points
        pts = [{"x": 0.5, "y": 0.1, "ix": -c, "iy": 0, "ox": c, "oy": 0}, {"x": 0.9, "y": 0.5, "ix": 0, "iy": -c, "ox": 0, "oy": c},
               {"x": 0.5, "y": 0.9, "ix": c, "iy": 0, "ox": -c, "oy": 0}, {"x": 0.1, "y": 0.5, "ix": 0, "iy": c, "ox": 0, "oy": -c}]
        poly = masks.flatten(masks.clean_points(pts))
        self.assertGreater(len(poly), 80)
        r = [math.hypot(x - 0.5, y - 0.5) for x, y in poly]
        self.assertTrue(0.39 < min(r) and max(r) < 0.41, (min(r), max(r)))
        m = self.clip("red", end=2, fit="stretch", mask={"shape": "bezier", "points": pts, "feather": 0})
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [m]})
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (255, 0, 0), 50))
        self.assertTrue(near(pixel(out, 1.0, 10, 10), (0, 0, 255), 50), "the corner is outside the circle")

    def test_a_motion_track_moves_a_rect_mask_and_a_bezier_mask(self):
        kx = [{"t": 0, "v": -0.25, "e": "linear"}, {"t": 2, "v": 0.25, "e": "linear"}]
        rect = self.clip("red", end=2, fit="stretch", mask={"shape": "rect", "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.4, "feather": 0, "kx": kx})
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [rect]})
        self.assertTrue(near(pixel(out, 0.1, 80, 120), (255, 0, 0), 60), pixel(out, 0.1, 80, 120))
        self.assertTrue(near(pixel(out, 0.1, 240, 120), (0, 0, 255), 60))
        self.assertTrue(near(pixel(out, 1.9, 240, 120), (255, 0, 0), 60), pixel(out, 1.9, 240, 120))
        box = [{"x": 0.4, "y": 0.3}, {"x": 0.6, "y": 0.3}, {"x": 0.6, "y": 0.7}, {"x": 0.4, "y": 0.7}]
        bez = self.clip("red", end=2, fit="stretch", mask={"shape": "bezier", "points": box, "feather": 0, "kx": kx})
        out2, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [bez]})
        self.assertTrue(near(pixel(out2, 0.1, 80, 120), (255, 0, 0), 70), pixel(out2, 0.1, 80, 120))
        self.assertTrue(near(pixel(out2, 0.1, 240, 120), (0, 0, 255), 70))
        self.assertTrue(near(pixel(out2, 1.9, 240, 120), (255, 0, 0), 70), pixel(out2, 1.9, 240, 120))
        inv = self.clip("red", end=2, fit="stretch", mask={"shape": "bezier", "points": box, "feather": 0, "invert": True, "kx": kx})
        out3, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [inv]})
        self.assertTrue(near(pixel(out3, 0.1, 80, 120), (0, 0, 255), 70), "inverted + moving: the hole is where the mask was")
        self.assertTrue(near(pixel(out3, 0.1, 240, 120), (255, 0, 0), 70))

    # ----------------------------------------------------------- matte
    def test_a_matte_makes_half_of_the_clip_transparent(self):
        c = self.clip("red", end=2, fit="stretch", matte={"key": "m1"})
        out, line = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [c]})
        self.assertTrue(line.tracks[1].clips[0].matte_file.endswith("halfmatte.mp4"))
        self.assertTrue(near(pixel(out, 1.0, 60, 120), (255, 0, 0), 60), "where the matte is white the subject stays")
        self.assertTrue(near(pixel(out, 1.0, 260, 120), (0, 0, 255), 60), "where it is black the clip is gone")

    def test_a_matte_follows_a_trimmed_clip_and_a_transform(self):
        c = self.clip("red", at=0.5, start=1.0, end=3.0, fit="stretch", matte={"key": "m1"}, scale=0.5)
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=3)]}, {"kind": "video", "clips": [c]})
        self.assertTrue(near(pixel(out, 1.5, 120, 120), (255, 0, 0), 70), pixel(out, 1.5, 120, 120))
        self.assertTrue(near(pixel(out, 1.5, 200, 120), (0, 0, 255), 70), pixel(out, 1.5, 200, 120))

    # ----------------------------------------------------------- nested sequences
    def test_a_nested_sequence_plays_as_one_clip_with_its_picture_and_sound(self):
        seq = {"tracks": [{"kind": "video", "clips": [self.clip("red", at=0, end=1), self.clip("blue", at=1, end=1)]},
                          {"kind": "audio", "clips": [self.clip("tone", at=0, end=2)]}]}
        nested = {"ref": "seq:a", "at": 1.0, "start": 0, "end": 2, "fit": "stretch"}
        out, line = self.render({"kind": "video", "clips": [self.clip("gray", at=0, end=1), nested]}, sequences={"a": seq})
        info = stats(out)
        self.assertAlmostEqual(info["dur"], 3.0, delta=0.15)
        self.assertTrue(info["audio"], "the nested sequence's tone comes along")
        self.assertTrue(near(pixel(out, 0.5, 160, 120), (128, 128, 128), 25))
        self.assertTrue(near(pixel(out, 1.5, 160, 120), (255, 0, 0), 50), "nested red at nested time 0.5")
        self.assertTrue(near(pixel(out, 2.5, 160, 120), (0, 0, 255), 50), "nested blue at nested time 1.5")
        self.assertEqual(line.clip_count, 5, "the nested clips count against the limit too")

    def test_the_nested_clip_can_be_trimmed_slowed_and_scaled_like_any_clip(self):
        seq = {"tracks": [{"kind": "video", "clips": [self.clip("red", at=0, end=1), self.clip("blue", at=1, end=1)]}]}
        nested = {"ref": "seq:a", "at": 0, "start": 1.0, "end": 2.0, "speed": 0.5, "fit": "stretch"}      # blue only, played at half speed: 2 s
        out, line = self.render({"kind": "video", "clips": [nested]}, sequences={"a": seq})
        self.assertAlmostEqual(stats(out)["dur"], 2.0, delta=0.15)
        self.assertTrue(near(pixel(out, 0.5, 160, 120), (0, 0, 255), 50))
        small = {"ref": "seq:a", "at": 0, "start": 0, "end": 1.0, "fit": "stretch", "scale": 0.5}
        out2, _ = self.render({"kind": "video", "clips": [self.clip("gray", end=1)]}, {"kind": "video", "clips": [small]}, sequences={"a": seq})
        self.assertTrue(near(pixel(out2, 0.5, 160, 120), (255, 0, 0), 60))
        self.assertTrue(near(pixel(out2, 0.5, 10, 10), (128, 128, 128), 30), "scaled to half: the base shows around it")

    def test_nested_sequences_inside_nested_sequences_and_their_limits(self):
        inner = {"tracks": [{"kind": "video", "clips": [self.clip("red", end=1)]}]}
        outer = {"tracks": [{"kind": "video", "clips": [{"ref": "seq:in", "at": 0, "start": 0, "end": 1, "fit": "stretch"}]}]}
        out, _ = self.render({"kind": "video", "clips": [{"ref": "seq:out", "at": 0, "start": 0, "end": 1, "fit": "stretch"}]},
                             sequences={"in": inner, "out": outer})
        self.assertTrue(near(pixel(out, 0.5, 160, 120), (255, 0, 0), 50))
        loop = {"a": {"tracks": [{"kind": "video", "clips": [{"ref": "seq:b", "at": 0, "start": 0, "end": 1}]}]},
                "b": {"tracks": [{"kind": "video", "clips": [{"ref": "seq:a", "at": 0, "start": 0, "end": 1}]}]}}
        with self.assertRaises(TimelineError) as ctx:
            T.from_project({**project({"kind": "video", "clips": [{"ref": "seq:a", "at": 0, "start": 0, "end": 1}]}), "sequences": loop}, resolver(self.table()))
        self.assertIn("حلقه", str(ctx.exception))
        with self.assertRaises(TimelineError):
            T.from_project({**project({"kind": "video", "clips": [{"ref": "seq:ghost", "at": 0, "end": 1}]}), "sequences": {}}, resolver(self.table()))

    def test_a_nested_sequence_survives_the_exact_range_window_and_a_transition(self):
        seq = {"tracks": [{"kind": "video", "clips": [self.clip("red", at=0, end=1), self.clip("blue", at=1, end=1)]}]}
        data = project({"kind": "video", "clips": [self.clip("gray", at=0, end=1), {"ref": "seq:a", "at": 1.0, "start": 0, "end": 2, "fit": "stretch", "transition": {"kind": "fade", "duration": 0.4}}]})
        data["sequences"] = {"a": seq}
        line = T.from_project(data, resolver(self.table()))
        out = self.dir / "trans.mp4"
        export.render(line, out, quality="draft")
        self.assertAlmostEqual(stats(out)["dur"], 3.0, delta=0.15)
        part = self.dir / "part.mp4"
        info = export.render_preview(line, part, 1.5, 2.5, height=120)
        self.assertTrue(info["path"].is_file())
        self.assertEqual(stats(part)["h"], 120)

    # ----------------------------------------------------------- portable graphs
    def test_a_portable_graph_uses_tokens_for_fonts_and_luts_and_lists_its_assets(self):
        lut = self.dir / "p.cube"
        lut.write_text(cube_text(3))
        table = self.table()
        table["lut:k"] = {"path": str(lut), "kind": "lut"}
        data = project({"kind": "video", "clips": [self.clip("gray", end=2, lut={"key": "k", "amount": 1})]},
                       {"kind": "text", "clips": [{"text": "سلام", "at": 0, "duration": 1}]})
        built = compose.build_graph(T.from_project(data, resolver(table)), portable=True)
        self.assertIn("__FONTSDIR__", built.graph)
        self.assertNotIn(str(titles.FONTS_DIR), built.graph)
        self.assertEqual(list(built.assets.values()), [str(lut)])
        self.assertIn("lut3d=file='__ASSET_0__'", built.graph)
        self.assertEqual(list(built.texts), ["__FILE_0__"])
        local = compose.build_graph(T.from_project(data, resolver(table)))
        self.assertNotIn("__ASSET_", local.graph)
        self.assertIn(str(titles.FONTS_DIR), local.graph)


# ------------------------------------------------------------------ tracking + multicam

class TrackingTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (HAVE_FFMPEG and HAVE_CV):
            return
        import numpy as np

        cls.dir = Path(tempfile.mkdtemp(prefix="nm-track-"))
        rng = np.random.default_rng(3)
        W, H, N, FPS = 320, 240, 60, 15
        bg = (rng.random((H, W)) * 60 + 40).astype(np.uint8)
        patch = (rng.random((40, 40)) * 200 + 30).astype(np.uint8)
        cls.truth = []
        cmd = [FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               str(cls.dir / "move.mp4")]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for i in range(N):
            x = 60 + i * 3                       # 3 px per frame to the right
            y = 90 + int(20 * math.sin(i / 8))   # a gentle wave
            frame = bg.copy()
            frame[y:y + 40, x:x + 40] = patch
            cls.truth.append(((x + 20) / W, (y + 20) / H))
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        proc.wait()
        cls.video = cls.dir / "move.mp4"

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "dir"):
            shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not (HAVE_FFMPEG and HAVE_CV):
            self.skipTest("ffmpeg یا OpenCV نیست")

    def test_a_moving_patch_is_followed_within_a_few_pixels(self):
        out = tracking.track(self.video, 0.0, 4.0, {"x": 60 / 320, "y": 90 / 240, "w": 40 / 320, "h": 40 / 240}, src_size=(320, 240), fps=15, ffmpeg=FFMPEG)
        self.assertGreaterEqual(len(out["samples"]), 50)
        self.assertIsNone(out["lost_at"])
        worst = 0.0
        for s in out["samples"]:
            i = round(s["s"] * 15)
            tx, ty = self.truth[min(i, len(self.truth) - 1)]
            worst = max(worst, math.hypot((s["x"] - tx) * 320, (s["y"] - ty) * 240))
        self.assertLess(worst, 5.0, f"worst error {worst:.1f}px")
        self.assertGreater(out["samples"][-1]["x"] - out["samples"][0]["x"], 0.5, "it moved right across the frame")
        self.assertAlmostEqual(out["samples"][-1]["scale"], 1.0, delta=0.15)

    def test_a_flat_region_and_a_tiny_range_are_refused_with_a_sentence(self):
        with self.assertRaises(tracking.TrackError):
            tracking.track(self.video, 1.0, 1.1, {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}, src_size=(320, 240), ffmpeg=FFMPEG)
        flat = self.dir / "flat.mp4"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=15:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(flat))
        with self.assertRaises(tracking.TrackError) as ctx:
            tracking.track(flat, 0.0, 2.0, {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}, src_size=(320, 240), ffmpeg=FFMPEG)
        self.assertIn("قابلِ ردیابی", str(ctx.exception))

    def test_cancel_stops_it(self):
        n = {"calls": 0}

        def cancel():
            n["calls"] += 1
            return n["calls"] > 5

        with self.assertRaises(tracking.TrackCancelled):
            tracking.track(self.video, 0.0, 4.0, {"x": 0.19, "y": 0.37, "w": 0.12, "h": 0.17}, src_size=(320, 240), ffmpeg=FFMPEG, cancel=cancel)


class MulticamTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        import numpy as np
        import wave

        cls.dir = Path(tempfile.mkdtemp(prefix="nm-mc-"))
        rng = np.random.default_rng(11)
        sr, total = 8000, 30
        sig = np.zeros(sr * total, dtype=np.float32)
        for start in rng.uniform(0.5, total - 1, 24):                # hand-claps: short noise bursts at random moments
            i = int(start * sr)
            n = int(rng.uniform(0.05, 0.25) * sr)
            sig[i:i + n] += (rng.standard_normal(n) * np.hanning(n) * rng.uniform(0.3, 0.9)).astype(np.float32)

        def write(name, offset, noise=0.0, gain=1.0):
            """A recording that started `offset` seconds after the reference (it misses the first `offset` seconds)."""
            part = sig[int(offset * sr):] * gain
            part = part + rng.standard_normal(len(part)).astype(np.float32) * noise
            with wave.open(str(cls.dir / name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes((np.clip(part, -1, 1) * 32767).astype("<i2").tobytes())
            return cls.dir / name

        cls.a = write("a.wav", 0.0)
        cls.b = write("b.wav", 2.37, noise=0.02, gain=0.5)
        cls.c = write("c.wav", 5.0)
        cls.noise = cls.dir / "noise.wav"
        with wave.open(str(cls.noise), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((rng.standard_normal(sr * 20) * 3000).astype("<i2").tobytes())

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "dir"):
            shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def test_offsets_are_found_to_a_few_milliseconds(self):
        out = multicam.sync([self.a, self.b, self.c])
        self.assertEqual(out[0]["offset"], 0.0)
        self.assertAlmostEqual(out[1]["offset"], 2.37, delta=0.01)
        self.assertAlmostEqual(out[2]["offset"], 5.0, delta=0.01)
        self.assertTrue(out[1]["ok"] and out[2]["ok"], out)
        self.assertGreater(out[1]["confidence"], 0.4)

    def test_a_recording_that_started_earlier_gets_a_negative_offset(self):
        out = multicam.sync([self.b, self.a])
        self.assertAlmostEqual(out[1]["offset"], -2.37, delta=0.01)

    def test_unrelated_sound_is_reported_as_not_found(self):
        out = multicam.sync([self.a, self.noise])
        self.assertFalse(out[1]["ok"], out)
        self.assertLess(out[1]["confidence"], multicam.MIN_CONFIDENCE)

    def test_one_file_or_a_silent_file_is_refused(self):
        with self.assertRaises(TimelineError):
            multicam.sync([self.a])
        silent = self.dir / "silent.mp4"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=10:d=2", "-c:v", "libx264", str(silent))
        with self.assertRaises(TimelineError):
            multicam.sync([self.a, silent])

"""موتورِ شخصیتِ برند: گرافِ برداری (SVG ⇄ Pillow)، سندِ ظاهر، هر سبک × هر ژست × هر اندازه، کلیدِ رنگ، لوگوی هرگز آینه‌نشده، لایه‌های دستی، SVG/PDF.
هیچ دیتابیسی لازم نیست (SimpleTestCase)."""
import io
import re
import xml.etree.ElementTree as ET

import numpy as np
from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from apps.mascot import selftest as MST
from apps.mascot.engine import compose, poses, qa, stage
from apps.mascot.engine import spec as MS

from . import selftest
from .engine import doc as D
from .engine import figure as F
from .engine import render as R
from .engine import sheet as SH
from .engine import vector as V

CHAGHER = ["#126F85", "#163F75"]


def asym_logo() -> Image.Image:
    """لوگوی نامتقارن: نیمهٔ چپ قرمزِ خالص، نیمهٔ راست آبیِ خالص (رنگ‌هایی که در پالتِ شخصیت نیست)."""
    im = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 59, 119], fill=(255, 0, 0, 255))
    d.rectangle([60, 0, 119, 119], fill=(0, 0, 255, 255))
    return im


def doc_for(style: str, **kw) -> dict:
    return D.normalize({**selftest.chagher_doc(style), **kw})


class VectorPrimitiveTests(SimpleTestCase):
    def test_shapes_become_paths_and_svg_is_well_formed(self):
        root = V.G(kids=[V.P(V.circle(50, 50, 20), fill="#ff0000"), V.P(V.rrect(10, 10, 40, 30, 8), fill="#00ff00", stroke="#000000", sw=3),
                         V.P(V.capsule(0, 0, 80, 40, 12, 8), fill="#0000ff"), V.P(V.curve([(0, 0), (20, 30), (50, 10)]), stroke="#222222", sw=4)])
        svg = V.to_svg(root, (0, 0, 100, 100))
        tree = ET.fromstring(svg)
        self.assertTrue(tree.tag.endswith("svg"))
        self.assertEqual(len(tree.findall(".//{http://www.w3.org/2000/svg}path")), 4)

    def test_same_scene_same_pixels_between_svg_geometry_and_raster(self):
        """رندرِ پیکسلیِ یک دایره همان جایی است که SVG می‌گوید (هندسهٔ مشترک)."""
        root = V.G(kids=[V.P(V.circle(60, 40, 20), fill="#ff0000")])
        img = V.rasterize(root, V.mscale(2.0), (200, 160), ss=3)
        a = np.asarray(img)
        ys, xs = np.nonzero(a[..., 3] > 128)
        self.assertAlmostEqual(xs.mean(), 120, delta=1.5)
        self.assertAlmostEqual(ys.mean(), 80, delta=1.5)
        self.assertAlmostEqual((xs.max() - xs.min()) / 2, 40, delta=1.5)

    def test_group_transform_and_opacity(self):
        root = V.G(kids=[V.G(kids=[V.P(V.rrect(0, 0, 40, 40, 0), fill="#000000")], m=V.mtrans(100, 50), op=0.5)])
        img = V.rasterize(root, V.IDENT, (200, 120), ss=2)
        px = img.getpixel((120, 70))
        self.assertAlmostEqual(px[3], 128, delta=3)
        self.assertEqual(img.getpixel((10, 10))[3], 0)

    def test_unit_path_uses_the_photo_editor_convention(self):
        path = {"closed": True, "pts": [{"x": 0, "y": 0, "hi": None, "ho": None}, {"x": 1, "y": 0, "hi": None, "ho": None}, {"x": 1, "y": 1, "hi": None, "ho": None}, {"x": 0, "y": 1, "hi": None, "ho": None}]}
        cmds = V.from_unit_path(path, {"cx": 50, "cy": 50, "w": 40, "h": 20, "rot": 0})
        pts = [(c[1], c[2]) for c in cmds if c[0] in "ML"]
        self.assertEqual(pts[0], (30.0, 40.0))
        self.assertIn((70.0, 60.0), pts)

    def test_stroke_has_no_gaps_at_joints(self):
        root = V.G(kids=[V.P(V.poly([(10, 10), (60, 60), (110, 10)], False), stroke="#000000", sw=14)])
        img = V.rasterize(root, V.IDENT, (140, 100), ss=3)
        self.assertGreater(img.getpixel((60, 60))[3], 250)
        self.assertGreater(img.getpixel((35, 35))[3], 250)


class DocTests(SimpleTestCase):
    def test_normalize_limits_choices_colours_and_layers(self):
        d = D.normalize({"style": "nope", "hair": "long", "skin": "zz", "top": "#ABC", "layers": [{"shape": "rect", "box": {"cx": 1e9, "w": -5}}, {"shape": "bad"}, "x"] + [{"shape": "ellipse"}] * 100,
                         "evil": "<script>"})
        self.assertEqual(d["style"], "flat")
        self.assertEqual(d["hair"], "long")
        self.assertEqual(d["skin"], D.DEFAULTS["skin"])
        self.assertEqual(d["top"], "#aabbcc")
        self.assertLessEqual(len(d["layers"]), D.MAX_LAYERS)
        self.assertNotIn("evil", d)
        self.assertLessEqual(d["layers"][0]["box"]["cx"], 1500)
        self.assertGreaterEqual(d["layers"][0]["box"]["w"], 1)
        ids = [l["id"] for l in d["layers"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_library_option_is_labelled_in_persian(self):
        for key, opts in D.CHOICES.items():
            for o in opts:
                self.assertIn(o, D.CHOICE_LABELS_FA[key], (key, o))

    def test_library_sizes_meet_the_brief(self):
        self.assertGreaterEqual(len(D.STYLES), 4)                         # تخت، چیبی، استیکر + آدمک‌چوبی
        self.assertGreaterEqual(len(D.HAIRS), 9)
        self.assertGreaterEqual(len(D.OUTFITS), 6)
        self.assertGreaterEqual(len(D.BODIES), 4)
        self.assertGreaterEqual(len(D.EYE_STYLES), 6)
        self.assertGreaterEqual(len(D.PROPS) - 1, 14)

    def test_to_mascot_spec_is_valid_for_the_stick_engine(self):
        for hair in D.HAIRS:
            spec = MS.normalize(D.to_mascot_spec(D.normalize({"hair": hair, "eye_style": "big", "head_style": "square"})))
            self.assertIn(spec["hair"], ("none", "tuft", "spikes", "bob", "ponytail"))
            self.assertIn(spec["eye_style"], ("dots", "round", "sleepy"))

    def test_hash_changes_with_look_and_not_with_name(self):
        a = doc_for("flat")
        self.assertEqual(D.doc_hash(a), D.doc_hash({**a, "name": "یک نامِ دیگر"}))
        self.assertNotEqual(D.doc_hash(a), D.doc_hash({**a, "hair": "long"}))
        self.assertNotEqual(D.doc_hash(a), D.doc_hash({**a, "layers": [{"shape": "rect", "box": {"cx": 1, "cy": 1, "w": 10, "h": 10}}]}))


class EveryStyleEveryPoseTests(SimpleTestCase):
    def test_every_style_x_every_pose_x_every_size_keeps_the_colour_key(self):
        """۴ سبک × ۲۹ ژست × ۴ اندازه (به مقیاسِ آزمون) — شخصیت دیده می‌شود و همهٔ رنگ‌های امضا هست."""
        logo = MST.synthetic_logo()
        for style in D.STYLES:
            res = R.grid(doc_for(style), logo=logo)
            self.assertEqual(res["total"], len(poses.POSES) * 4, style)
            self.assertTrue(res["ok"], (style, res["failed"][:3]))

    def test_every_style_x_pose_in_the_mirrored_direction(self):
        logo = MST.synthetic_logo()
        for style in D.STYLES:
            res = R.grid(doc_for(style), logo=logo, sizes=("ig_portrait",), flip=True)
            self.assertTrue(res["ok"], (style, res["failed"][:3]))

    def test_every_expression_and_every_prop_renders_in_every_vector_style(self):
        for style in ("flat", "chibi", "sticker"):
            for ex in D.EXPRESSIONS:
                shot = stage.render_actor({"spec": doc_for(style), "pose": "stand", "expression": ex, "x": 0.5, "y": 0.96, "height": 0.9}, 200, 300)
                self.assertGreater(shot.layer.getchannel("A").getbbox()[3], 100, (style, ex))
            for prop in D.PROPS:
                shot = stage.render_actor({"spec": doc_for(style), "pose": "hold", "expression": "happy", "prop": prop, "x": 0.5, "y": 0.96, "height": 0.9}, 200, 300)
                self.assertIsNotNone(shot.bbox, (style, prop))

    def test_every_library_option_draws_without_error_and_changes_the_picture(self):
        base = doc_for("flat", logo="none", hat="none", hair="none", extra="none", neck="none")

        def pic(doc):
            return np.asarray(stage.render_actor({"spec": doc, "pose": "stand", "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.92, "shadow": False}, 220, 320).layer)

        ref = pic(base)
        for key in ("body", "head_style", "eye_style", "brows", "nose", "hair", "hat", "neck", "extra", "outfit", "bottoms", "shoes_type"):
            seen = 0
            for opt in D.CHOICES[key]:
                other = pic({**base, key: opt})
                if not np.array_equal(other, ref):
                    seen += 1
            self.assertGreaterEqual(seen, len(D.CHOICES[key]) - 2, key)

    def test_three_vector_styles_look_different_and_stick_is_the_old_engine(self):
        def pic(style):
            return np.asarray(stage.render_actor({"spec": R.actor_spec(doc_for(style)), "pose": "wave", "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.9}, 240, 340).layer)

        imgs = {s: pic(s) for s in D.STYLES}
        keys = list(imgs)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                self.assertFalse(np.array_equal(imgs[keys[i]], imgs[keys[j]]), (keys[i], keys[j]))
        self.assertNotIn("stick", stage.STYLE_RENDERERS)
        self.assertEqual({"flat", "chibi", "sticker"}, set(stage.STYLE_RENDERERS))

    def test_sticker_style_has_a_white_die_cut_border(self):
        shot = stage.render_actor({"spec": doc_for("sticker"), "pose": "stand", "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.9, "shadow": False}, 300, 420)
        a = np.asarray(shot.layer)
        edge = a[(a[..., 3] > 240)]
        white = ((edge[:, :3] > 245).all(axis=1)).sum()
        self.assertGreater(white / len(edge), 0.03)

    def test_every_pose_stays_inside_the_canvas_after_inside(self):
        for pz in poses.names():
            shot = compose.figure_layer({"spec": doc_for("flat"), "pose": pz, "expression": "happy", **compose.actor_defaults("ig_portrait")}, 270, 340, inside=0.02)
            x0, y0, x1, y1 = shot.bbox
            self.assertGreaterEqual(x0, 0, pz)
            self.assertLessEqual(x1, 270, pz)
            self.assertLessEqual(y1, 340, pz)


class LogoNeverMirroredTests(SimpleTestCase):
    def _centroids(self, flip: bool, style: str):
        logo = asym_logo()
        doc = doc_for(style, outfit="tshirt", neck="none", extra="none", prop="none", hat="none")
        shot = stage.render_actor({"spec": doc, "pose": "hands_up", "expression": "happy", "flip": flip, "x": 0.5, "y": 0.96, "height": 0.95, "shadow": False}, 360, 520, logo=logo)
        a = np.asarray(shot.layer).astype(int)
        red = (a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 2] < 60) & (a[..., 3] > 200)
        blue = (a[..., 2] > 200) & (a[..., 0] < 60) & (a[..., 1] < 60) & (a[..., 3] > 200)
        self.assertGreater(red.sum(), 20, (flip, style))
        self.assertGreater(blue.sum(), 20, (flip, style))
        return np.nonzero(red)[1].mean(), np.nonzero(blue)[1].mean()

    def test_the_logo_reads_the_same_way_whichever_direction_the_character_faces(self):
        for style in ("flat", "chibi", "sticker"):
            rx, bx = self._centroids(False, style)
            self.assertLess(rx, bx, style)                         # قرمز (چپِ لوگو) چپِ آبی
            rx2, bx2 = self._centroids(True, style)
            self.assertLess(rx2, bx2, style + " flipped")          # آینه‌شدنِ شخصیت لوگو را وارونه نکرد

    def test_chest_logo_appears_only_when_asked_for(self):
        no = doc_for("flat", logo="none")
        shot = stage.render_actor({"spec": no, "pose": "stand", "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.95, "shadow": False}, 360, 520, logo=asym_logo())
        a = np.asarray(shot.layer).astype(int)
        self.assertEqual(((a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 3] > 200)).sum(), 0)


class ManualLayerTests(SimpleTestCase):
    LAYER = {"id": "dot", "shape": "ellipse", "anchor": "world", "box": {"cx": 300, "cy": 120, "w": 60, "h": 60, "rot": 0}, "fill": "#ff00ff", "above": True}

    def _count(self, doc, pose="stand"):
        shot = stage.render_actor({"spec": doc, "pose": pose, "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.95, "shadow": False}, 360, 520)
        a = np.asarray(shot.layer).astype(int)
        return ((a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 2] > 200) & (a[..., 3] > 200)).sum()

    def test_a_world_layer_is_drawn(self):
        self.assertEqual(self._count(doc_for("flat")), 0)
        self.assertGreater(self._count(doc_for("flat", layers=[self.LAYER])), 50)

    def test_a_head_layer_follows_the_pose(self):
        lay = {**self.LAYER, "anchor": "head", "box": {"cx": 0, "cy": -20, "w": 40, "h": 40, "rot": 0}}
        d = doc_for("flat", layers=[lay])
        for pz in ("stand", "run_a", "lying", "sit"):
            shot = stage.render_actor({"spec": d, "pose": pz, "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.95, "shadow": False}, 360, 520)
            a = np.asarray(shot.layer).astype(int)
            mask = (a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 2] > 200) & (a[..., 3] > 200)
            self.assertGreater(mask.sum(), 20, pz)
            cy, cx = np.nonzero(mask)[0].mean(), np.nonzero(mask)[1].mean()
            hx, hy, hr = shot.head
            self.assertLess(((cx - hx) ** 2 + (cy - hy) ** 2) ** 0.5, hr * 1.6, pz)      # لایه کنارِ سر می‌ماند

    def test_a_path_layer_with_bezier_handles_renders(self):
        path = {"closed": True, "pts": [{"x": 0.5, "y": 0, "hi": [-0.3, 0], "ho": [0.3, 0]}, {"x": 1, "y": 1, "hi": None, "ho": None}, {"x": 0, "y": 1, "hi": None, "ho": None}]}
        lay = {"id": "p1", "shape": "path", "anchor": "world", "box": {"cx": 300, "cy": 120, "w": 90, "h": 90, "rot": 20}, "fill": "#ff00ff", "path": path}
        self.assertGreater(self._count(doc_for("flat", layers=[lay])), 100)

    def test_hidden_layers_are_skipped_and_below_layers_sit_behind(self):
        hidden = {**self.LAYER, "hidden": True}
        self.assertEqual(self._count(doc_for("flat", layers=[hidden])), 0)
        covered = {**self.LAYER, "above": False, "box": {"cx": 300, "cy": 400, "w": 140, "h": 300, "rot": 0}}
        self.assertLess(self._count(doc_for("flat", layers=[covered])), 140 * 300 * 0.02)       # بیشترش زیرِ بدن است


class SvgAndSheetTests(SimpleTestCase):
    def test_svg_for_every_vector_style_and_pose_parses(self):
        for style in ("flat", "chibi", "sticker"):
            for pz in ("stand", "wave", "run_a", "lying", "thumbs_up"):
                text, info = R.svg(doc_for(style), pose=pz, expression="happy", logo=MST.synthetic_logo())
                tree = ET.fromstring(text)
                self.assertTrue(tree.tag.endswith("svg"), (style, pz))
                self.assertFalse(info["embedded"])
                self.assertIn("<path", text)
                self.assertIn("<image", text)                           # لوگوی روی سینه
                self.assertRegex(text, r'viewBox="[-\d. ]+"')

    def test_svg_of_the_stick_style_embeds_a_raster_and_says_so(self):
        text, info = R.svg(doc_for("stick"), pose="wave")
        self.assertTrue(info["embedded"])
        self.assertIn("data:image/png;base64", text)
        ET.fromstring(text)

    def test_svg_with_a_background_is_a_filled_rect_first(self):
        text, _ = R.svg(doc_for("flat"), background="#ffee00")
        self.assertRegex(text, r'<rect[^>]+fill="#ffee00"')

    def test_model_sheet_and_pdf(self):
        d = doc_for("chibi")
        img = SH.model_sheet(d, title="مربی چغر", store_name="چغر", version=2, logo=MST.synthetic_logo(), persona={"archetype": "sage", "catchphrases": ["با چغر چغر تر شو"]})
        self.assertEqual(img.size, (SH.W, SH.H))
        self.assertGreater(len(set(img.convert("L").resize((64, 48)).getdata())), 40)
        pdf = SH.pdf_bytes(d, title="مربی چغر", store_name="چغر", version=2, logo=MST.synthetic_logo())
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(re.findall(rb"/Type\s*/Page\b", pdf)), 2)

    def test_the_four_styles_page_and_the_poses_page_have_every_pose(self):
        pg = SH.poses_page(doc_for("flat"))
        self.assertGreaterEqual(pg.height, 160 + 5 * 300)
        self.assertEqual(SH.styles_page(doc_for("flat")).size, (SH.W, SH.H))


class SelftestHookTests(SimpleTestCase):
    def test_run_engine_passes_for_chagher(self):
        res = selftest.run_engine(sizes=("ig_portrait", "story"), pose_list=("stand", "wave", "lying"))
        self.assertTrue(res["ok"], res["failed"][:2])
        self.assertEqual(res["styles"], 4)

    def test_node_spec_and_image_check(self):
        s = selftest.node_spec()
        self.assertIn("reference.png", s["files"])
        self.assertEqual(s["payload"]["width"], 512)
        ok, why = selftest.check_node_image(b"")
        self.assertFalse(ok)
        flat = io.BytesIO()
        Image.new("RGB", (512, 512), (10, 10, 10)).save(flat, "PNG")
        self.assertFalse(selftest.check_node_image(flat.getvalue() + b"0" * 5000)[0])
        im = Image.new("RGB", (512, 512), (230, 232, 236))
        ImageDraw.Draw(im).ellipse((150, 100, 360, 480), fill=(18, 111, 133))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        ok, why = selftest.check_node_image(buf.getvalue() + b"0" * 4000)
        self.assertTrue(ok, why)

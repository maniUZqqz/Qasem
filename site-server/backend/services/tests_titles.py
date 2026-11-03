"""Titles: the cleaner, the ASS writer, and REAL libass renders of Persian / English / digits text.

The string-level tests are fast; the render tests run the server's ffmpeg on tiny flat frames and measure pixels —
an ASS file that merely parses proves nothing about shaping, ordering, boxes or animation."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from services.editing import titles
from services.editing.errors import TimelineError
from services.video.ffmpeg import FFMPEG

HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
BG = "0x202020"


def hexrgb(color):
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


class CleanTests(SimpleTestCase):
    def test_old_clips_keep_their_look(self):
        d = titles.clean({"text": "سلام", "at": 1, "duration": 2})
        self.assertEqual((d["color"], d["box"], d["box_opacity"], d["size"], d["font"], d["bold"]),
                         ("#ffffff", True, 0.45, 6.0, "vazir", True))
        self.assertEqual((d["x"], d["y"], d["position"], d["align"], d["template"]), (0.5, 0.86, "bottom", "center", "plain"))
        self.assertEqual((d["stroke"], d["shadow"], d["anim_in"], d["anim_out"], d["words"]), (0, 0, "none", "none", []))

    def test_legacy_positions_and_explicit_xy(self):
        self.assertEqual(titles.clean({"text": "a", "position": "top"})["y"], 0.12)
        self.assertEqual(titles.clean({"text": "a", "position": "middle"})["y"], 0.5)
        d = titles.clean({"text": "a", "position": "top", "x": 0.2, "y": 0.3})
        self.assertEqual((d["x"], d["y"]), (0.2, 0.3))
        self.assertEqual(titles.clean({"text": "a", "x": 9, "y": -3})["y"], 0.0)

    def test_templates_set_defaults_but_the_clip_wins(self):
        fa = titles.clean({"text": "رضا محمدی", "text2": "مدیر", "template": "lower_bar"})
        self.assertEqual((fa["align"], fa["anim_in"], fa["box"]), ("right", "slide_left", False))
        en = titles.clean({"text": "John Carter", "template": "lower_bar"})
        self.assertEqual((en["align"], en["anim_in"]), ("left", "slide_right"))
        own = titles.clean({"text": "x", "template": "lower_bar", "anim_in": "pop", "align": "center", "size": 9})
        self.assertEqual((own["anim_in"], own["align"], own["size"]), ("pop", "center", 9.0))
        self.assertEqual(titles.clean({"text": "x", "template": "title_big"})["anim_in"], "pop")
        self.assertEqual(titles.clean({"text": "x", "template": "nope"})["template"], "plain")
        # idempotent: cleaning a cleaned clip changes nothing
        again = titles.clean(fa)
        self.assertEqual(again, fa)

    def test_values_are_clamped_and_bad_values_fall_back(self):
        d = titles.clean({"text": "x", "size": 99, "duration": -5, "stroke": 500, "opacity": 0, "scale": 99, "rotation": 999,
                          "color": "red", "stroke_color": "#abc", "font": "comic", "anim_in": "explode", "align": "diagonal",
                          "hl_mode": "x", "box_opacity": 7})
        self.assertEqual((d["size"], d["duration"], d["stroke"], d["opacity"], d["scale"], d["rotation"]),
                         (30.0, 0.1, 100.0, 0.05, 4.0, 180.0))
        self.assertEqual((d["color"], d["stroke_color"], d["font"], d["anim_in"], d["align"], d["hl_mode"], d["box_opacity"]),
                         ("#ffffff", "#aabbcc", "vazir", "none", "center", "color", 1.0))

    def test_empty_text_is_refused_in_persian_but_a_second_line_alone_is_fine(self):
        with self.assertRaises(TimelineError) as ctx:
            titles.clean({"text": "   ", "label": "تیتر"})
        self.assertIn("متن خالی", str(ctx.exception))
        with self.assertRaises(TimelineError):
            titles.clean("not a dict")
        self.assertEqual(titles.clean({"text": "", "text2": "زیرعنوان"})["text2"], "زیرعنوان")

    def test_text_is_sanitised(self):
        d = titles.clean({"text": "a\x00b\r\nc\td" + "x" * 900, "text2": "y" * 900})
        self.assertNotIn("\x00", d["text"])
        self.assertIn("a" + "b\nc d", d["text"])
        self.assertEqual((len(d["text"]), len(d["text2"])), (400, 200))

    def test_words_are_cleaned_sorted_and_clamped_to_the_clip(self):
        d = titles.clean({"text": "a b c", "duration": 2, "words": [
            {"w": "b", "s": 1.0, "e": 1.4}, {"w": "a", "s": 0.0, "e": 0.9}, {"w": "", "s": 1, "e": 2},
            {"word": "c", "start": 1.5, "end": 9}, {"w": "bad"}, "junk"]})
        self.assertEqual([w["w"] for w in d["words"]], ["a", "b", "c"])
        self.assertEqual(d["words"][2], {"w": "c", "s": 1.5, "e": 2.0})

    def test_rtl_detection_follows_the_first_strong_letter(self):
        self.assertTrue(titles.is_rtl("سلام Hello"))
        self.assertFalse(titles.is_rtl("Hello سلام"))
        self.assertFalse(titles.is_rtl("۱۲۳ 456"))
        self.assertEqual(titles.plain_text({"text": "رضا\nمحمدی", "text2": "مدیر"}), "رضا محمدی — مدیر")

    def test_catalogue_and_preview_spec(self):
        cat = titles.catalogue()
        self.assertEqual({t["key"] for t in cat["templates"]}, set(titles.TEMPLATES))
        self.assertTrue(all(t["title"] for t in cat["templates"] + cat["fonts"] + cat["animations_in"]))
        self.assertIn("typewriter", {a["key"] for a in cat["animations_out"]})
        spec = titles.preview_spec({"text": "سلام", "size": 8, "stroke": 10, "words": [{"w": "سلام", "s": 0, "e": 1}]})
        self.assertEqual(spec["size"], 0.08)
        self.assertTrue(spec["rtl"])
        self.assertEqual(spec["stroke"]["w"], 0.1)
        self.assertIn("Vazirmatn", spec["css"])
        self.assertEqual(len(spec["words"]), 1)


class AssWriterTests(SimpleTestCase):
    def test_document_shape_and_timing(self):
        ass = titles.build_ass([{"text": "سلام", "at": 2.0, "duration": 3.0}, {"text": "بعدی", "at": 6.0, "duration": 1.0}], 540, 960)
        self.assertIn("PlayResX: 540", ass)
        self.assertIn("PlayResY: 960", ass)
        self.assertIn("ScaledBorderAndShadow: yes", ass)
        self.assertIn(",-1\n", ass.split("[Events]")[0], "Encoding -1 = bidi base direction from the first strong letter")
        dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
        self.assertTrue(dialogues[0].split(",")[1].startswith("0:00:02.00"))
        self.assertTrue(any(",0:00:05.00," in d for d in dialogues), "the first clip ends at 5 s")
        self.assertTrue(dialogues[-1].split(",")[1].startswith("0:00:06.00"))

    def test_user_text_cannot_inject_ass_tags(self):
        ass = titles.build_ass([{"text": "a{\\fs300}B\\Nc{x}", "text2": "{\\an9}z", "at": 0, "duration": 2}], 540, 960)
        body = "\n".join(line for line in ass.splitlines() if line.startswith("Dialogue:"))
        self.assertNotIn("{\\fs300}", body)
        self.assertNotIn("{\\an9}", body)
        self.assertIn("\\{", body)
        # the typed backslash-N is neutralised by a zero-width space; only our own line break is a real \N
        self.assertNotIn("B\\Nc", body)
        self.assertIn("\\​Nc", body)

    def test_font_size_scales_with_the_frame_so_previews_match_exports(self):
        def fontsize(h):
            ass = titles.build_ass([{"text": "x", "at": 0, "duration": 1, "size": 6}], h * 9 // 16, h)
            line = next(l for l in ass.splitlines() if l.startswith("Style: T0"))
            return float(line.split(",")[2])
        self.assertAlmostEqual(fontsize(1920) / fontsize(960), 2.0, delta=0.01)
        # ASS fontsize is the LINE height: 6 % em x Vazirmatn's measured 1.713 line ratio
        self.assertAlmostEqual(fontsize(1000), 0.06 * 1000 * titles.FONTS["vazir"]["line"], delta=0.05)

    def test_ass_filter_names_the_bundled_fonts_dir(self):
        f = titles.ass_filter("/tmp/x.ass")
        self.assertTrue(f.startswith("ass=filename="))
        self.assertIn("fontsdir=", f)
        self.assertIn("imaging/fonts", f)

    def test_every_template_and_animation_builds(self):
        items = []
        for tpl in titles.TEMPLATES:
            for anim in titles.ANIMATIONS_IN:
                items.append({"text": "تخفیف ویژه NMarketing ۵۰٪", "text2": "فقط امروز", "template": tpl, "anim_in": anim,
                              "anim_out": anim, "at": 0, "duration": 3})
        ass = titles.build_ass(items, 360, 640)
        self.assertGreater(ass.count("Dialogue:"), len(items))
        self.assertNotIn("nan", ass.lower().replace("sans", ""))


# ------------------------------------------------------------------ real renders

def render_frame(items, t, w=240, h=426, bg=BG):
    """One frame of the items over a flat dark background, as an RGB numpy array."""
    import numpy as np

    d = Path(tempfile.mkdtemp(prefix="nm-titles-"))
    try:
        path = d / "t.ass"
        path.write_text(titles.build_ass(items, w, h), encoding="utf-8")
        out = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c={bg}:s={w}x{h}:r=25:d={t + 1}",
             "-vf", titles.ass_filter(path) + ",format=rgb24", "-ss", str(t), "-frames:v", "1", "-f", "rawvideo", "-"],
            capture_output=True, stdin=subprocess.DEVNULL)
        if out.returncode:
            raise AssertionError(out.stderr.decode("utf-8", "replace")[:400])
        return np.frombuffer(out.stdout, dtype=np.uint8).reshape(h, w, 3).astype(int)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def near(img, color, tol=40):
    r, g, b = hexrgb(color) if isinstance(color, str) else color
    return (abs(img[..., 0] - r) < tol) & (abs(img[..., 1] - g) < tol) & (abs(img[..., 2] - b) < tol)


def bright(img):
    return img.min(axis=2) > 200


def ink_mask(img, tol=40):
    """Anything that differs from the flat background (so half-transparent text counts too)."""
    return abs(img - 32).max(axis=2) > tol


def centroid(mask):
    import numpy as np

    ys, xs = np.nonzero(mask)
    return (float(xs.mean()), float(ys.mean())) if len(xs) else (None, None)


FA = "تخفیف ویژه ۵۰٪ NMarketing 2026"


class RealRenderTests(SimpleTestCase):
    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def test_text_shows_only_inside_its_window_and_persian_orders_right_to_left(self):
        item = {"text": "اول دوم سوم", "at": 1.0, "duration": 2.0, "box": False, "size": 9, "y": 0.5,
                "words": [{"w": "اول", "s": 0.0, "e": 0.6}, {"w": "دوم", "s": 0.7, "e": 1.3}, {"w": "سوم", "s": 1.4, "e": 1.9}],
                "hl_color": "#ff0000", "color": "#ffffff"}
        self.assertEqual(int(bright(render_frame([item], 0.5)).sum()), 0, "before the clip")
        self.assertEqual(int(bright(render_frame([item], 3.5)).sum()), 0, "after the clip")
        xs = []
        for t in (1.3, 2.0, 2.6):            # first, second, third word active
            img = render_frame([item], t)
            self.assertGreater(int(bright(img).sum()), 100, f"white text at {t}")
            cx, _ = centroid(near(img, "#ff0000"))
            self.assertIsNotNone(cx, f"highlight colour missing at {t}")
            xs.append(cx)
        # Persian reads right to left: the first word is rightmost, the third leftmost — and the highlight walks left
        self.assertGreater(xs[0], xs[1] + 10)
        self.assertGreater(xs[1], xs[2] + 10)

    def test_latin_text_reads_left_to_right(self):
        item = {"text": "one two three", "at": 0.0, "duration": 2.0, "box": False, "size": 8, "y": 0.5,
                "words": [{"w": "one", "s": 0.0, "e": 0.6}, {"w": "two", "s": 0.7, "e": 1.3}, {"w": "three", "s": 1.4, "e": 1.9}],
                "hl_color": "#ff0000"}
        xs = [centroid(near(render_frame([item], t), "#ff0000"))[0] for t in (0.3, 1.0, 1.6)]
        self.assertLess(xs[0], xs[1] - 5)
        self.assertLess(xs[1], xs[2] - 5)

    def test_karaoke_modes_all_paint_the_highlight(self):
        words = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.45} for i, w in enumerate("قهوه تازه امروز".split())]
        for mode in ("color", "scale", "box"):
            item = {"text": "قهوه تازه امروز", "at": 0.0, "duration": 2.0, "words": words, "hl_color": "#00ff00",
                    "hl_mode": mode, "box": False, "size": 8, "y": 0.5}
            img = render_frame([item], 0.7)
            self.assertGreater(int(near(img, "#00ff00").sum()), 80, mode)
            self.assertGreater(int(near(render_frame([item], 1.5), "#00ff00").sum()), 40, mode + ": last word lit")

    def test_box_stroke_and_shadow_are_drawn_only_when_asked(self):
        base = {"text": FA, "at": 0.0, "duration": 2.0, "y": 0.5, "size": 6}
        plain = render_frame([{**base, "box": False}], 1.0)
        self.assertEqual(int(near(plain, "#c80000").sum()), 0)
        boxed = render_frame([{**base, "box": True, "box_color": "#c80000", "box_opacity": 1.0}], 1.0)
        self.assertGreater(int(near(boxed, "#c80000", 20).sum()), 800, "a solid red box behind the text")
        stroked = render_frame([{**base, "box": False, "stroke": 25, "stroke_color": "#c80000"}], 1.0)
        self.assertGreater(int(near(stroked, "#c80000", 30).sum()), 150, "red outline around white letters")
        self.assertGreater(int(bright(stroked).sum()), 100)
        shadowed = render_frame([{**base, "box": False, "shadow": 40, "shadow_color": "#00ff00"}], 1.0)
        green = (shadowed[..., 1] > 120) & (shadowed[..., 0] < 80) & (shadowed[..., 2] < 80)
        self.assertGreater(int(green.sum()), 40, "a coloured drop shadow")

    def test_size_and_position_follow_the_frame_not_the_pixels(self):
        item = {"text": "H", "at": 0.0, "duration": 2.0, "box": False, "size": 10, "x": 0.5, "y": 0.5, "font": "lato"}
        small = render_frame([item], 1.0, 200, 356)
        large = render_frame([item], 1.0, 400, 712)
        hs = int(bright(small).any(axis=1).sum())
        hl = int(bright(large).any(axis=1).sum())
        self.assertAlmostEqual(hl / hs, 2.0, delta=0.3)
        for img, (w, h) in ((small, (200, 356)), (large, (400, 712))):
            cx, cy = centroid(bright(img))
            self.assertAlmostEqual(cx / w, 0.5, delta=0.05)
            self.assertAlmostEqual(cy / h, 0.5, delta=0.05)
        # em semantics: a capital H is ~0.7 em tall -> 10 % em = 7 % of the frame height
        self.assertAlmostEqual(hs / 356, 0.07, delta=0.015)
        bigger = render_frame([{**item, "size": 20}], 1.0, 200, 356)
        self.assertAlmostEqual(int(bright(bigger).any(axis=1).sum()) / hs, 2.0, delta=0.3)

    def test_a_long_text_wraps_inside_the_frame_and_stays_in_it(self):
        item = {"text": "قهوهٔ تازه با تخفیفِ ویژهٔ امروز و ارسالِ رایگان برای همهٔ سفارش‌ها در تهران و کرج و شیراز", "at": 0.0,
                "duration": 2.0, "box": False, "size": 7, "y": 0.9}
        img = render_frame([item], 1.0)
        mask = bright(img)
        ys, xs = mask.nonzero()
        self.assertGreater(len(xs), 300)
        self.assertGreater(xs.min(), 2)
        self.assertLess(xs.max(), 238)
        self.assertLess(ys.max(), 424, "a bottom caption that wraps must not hang off the frame")
        self.assertGreater(len(set(ys.tolist())), 60, "several lines")

    def test_animations_change_the_picture_over_time(self):
        def clip(kind, **kw):
            return {"text": "تخفیف ۵۰٪ NMarketing", "at": 1.0, "duration": 3.0, "box": False, "size": 7, "x": 0.5, "y": 0.5,
                    "anim_in": kind, "anim_dur": 1.0, **kw}

        def ink(item, t):
            return int(bright(render_frame([item], t)).sum())

        # fade: transparent at the start, solid after
        fade = clip("fade")
        self.assertLess(ink(fade, 1.05), ink(fade, 2.5) * 0.35)
        # pop: starts small, ends at full size
        pop = clip("pop")
        self.assertLess(ink(pop, 1.05), ink(pop, 2.5) * 0.6)
        # zoom: starts big, settles
        zoom = clip("zoom", anim_in="zoom")
        end = ink(zoom, 2.5)
        self.assertGreater(end, 100)
        # typewriter: ink grows with time and the layout does not jump
        tw = clip("typewriter", anim_dur=1.0)
        counts = [ink(tw, t) for t in (1.15, 1.6, 2.3)]
        self.assertLess(counts[0], counts[1])
        self.assertLess(counts[1], counts[2])
        # slide_up enters from below (y decreasing), slide_left enters from the right (x decreasing)
        up = clip("slide_up")
        y_early = centroid(ink_mask(render_frame([up], 1.3)))[1]
        y_rest = centroid(ink_mask(render_frame([up], 2.5)))[1]
        self.assertGreater(y_early, y_rest + 3)
        left = clip("slide_left")
        x_early = centroid(ink_mask(render_frame([left], 1.3)))[0]
        x_rest = centroid(ink_mask(render_frame([left], 2.5)))[0]
        self.assertGreater(x_early, x_rest + 3)
        down = clip("slide_down")
        self.assertLess(centroid(ink_mask(render_frame([down], 1.3)))[1], centroid(ink_mask(render_frame([down], 2.5)))[1] - 3)
        right = clip("slide_right")
        self.assertLess(centroid(ink_mask(render_frame([right], 1.3)))[0], centroid(ink_mask(render_frame([right], 2.5)))[0] - 3)
        # blur: soft at first (fewer fully-bright pixels), sharp later
        blur = clip("blur")
        self.assertLess(ink(blur, 1.1), ink(blur, 2.5))
        # out animations: gone by the very end of the clip
        out = clip("none", anim_out="fade", anim_dur=1.0)
        self.assertGreater(ink(out, 2.5), 100)
        self.assertLess(ink(out, 3.95), ink(out, 2.5) * 0.3)
        out_tw = clip("none", anim_out="typewriter", anim_dur=1.0)
        self.assertLess(ink(out_tw, 3.9), ink(out_tw, 2.5) * 0.5)

    def test_lower_thirds_draw_their_accent_and_both_lines(self):
        fa = {"text": "رضا محمدی", "text2": "مدیرعامل NMarketing", "at": 0.0, "duration": 4.0, "accent": "#00c8ff", "anim_in": "none"}
        for tpl in ("lower_bar", "lower_box", "lower_line"):
            img = render_frame([{**fa, "template": tpl}], 2.0, 360, 640)
            self.assertGreater(int(near(img, "#00c8ff", 30).sum()), 60, f"{tpl}: accent colour")
            self.assertGreater(int(bright(img).sum()), 150, f"{tpl}: text")
            mask = bright(img)
            rows = [i for i in range(mask.shape[0]) if mask[i].any()]
            self.assertGreater(rows[-1] - rows[0], 25, f"{tpl}: two lines")
            self.assertGreater(rows[0], 640 * 0.5, f"{tpl}: in the lower half")
        # the bar of a Persian (right-aligned) lower third sits at the right, an English one at the left
        bar_fa = centroid(near(render_frame([{**fa, "template": "lower_bar"}], 2.0, 360, 640), "#00c8ff", 30))[0]
        en = {**fa, "text": "John Carter", "text2": "Head of Marketing"}
        bar_en = centroid(near(render_frame([{**en, "template": "lower_bar"}], 2.0, 360, 640), "#00c8ff", 30))[0]
        self.assertGreater(bar_fa, 180)
        self.assertLess(bar_en, 180)

    def test_other_templates_render(self):
        for tpl in ("title_center", "title_big", "quote", "sticker", "bubble"):
            img = render_frame([{"text": "فروش ویژه شب یلدا", "text2": "فقط تا پایان هفته", "template": tpl, "at": 0.0,
                                 "duration": 4.0, "anim_in": "none"}], 2.0, 360, 640)
            self.assertGreater(int((abs(img - 32).max(axis=2) > 24).sum()), 300, tpl)
        sticker = render_frame([{"text": "ویژه", "template": "sticker", "at": 0.0, "duration": 4.0, "anim_in": "none"}], 2.0, 360, 640)
        self.assertGreater(int(near(sticker, "#ffd400", 30).sum()), 500, "yellow sticker box")

    def test_hostile_text_renders_as_plain_characters(self):
        item = {"text": "x{\\fs300}B \\N {\\an9} 😀 ok", "at": 0.0, "duration": 2.0, "box": False, "size": 6, "y": 0.5}
        img = render_frame([item], 1.0)
        ys, xs = bright(img).nonzero()
        self.assertGreater(len(xs), 100)
        # an injected \fs300 would fill the frame; literal text stays a couple of lines tall
        self.assertLess(ys.max() - ys.min(), 426 * 0.3)

    def test_two_clips_do_not_interfere(self):
        a = {"text": "اول", "at": 0.0, "duration": 1.0, "box": False, "y": 0.2, "size": 8}
        b = {"text": "دوم", "at": 2.0, "duration": 1.0, "box": False, "y": 0.8, "size": 8}
        cy_a = centroid(bright(render_frame([a, b], 0.5)))[1]
        cy_b = centroid(bright(render_frame([a, b], 2.5)))[1]
        self.assertLess(cy_a, 426 * 0.35)
        self.assertGreater(cy_b, 426 * 0.65)
        self.assertEqual(int(bright(render_frame([a, b], 1.5)).sum()), 0)

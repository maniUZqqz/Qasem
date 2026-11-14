"""Every director caption look (CAPTION_STYLES) rendered for real (ASS + libass through ffmpeg, 480x854) at three moments.

Why: the «karaoke» look painted the spoken word #111111 on a #111111 marker box - a solid black blob nobody could read - and
no test ever looked at the pixels.  Here the word that is spoken is found by differencing the frame with a frame before the first
word, and its region must be readable: the contrast between its brightest and darkest pixels is at least 4.5:1 (WCAG AA)
and it is not uniformly dark."""
from django.test import SimpleTestCase

from services.editing import titles
from services.editing.director.tools import CAPTION_STYLES
from services.tests_titles import HAVE_FFMPEG, render_frame

W, H = 480, 854
TEXT = "قهوهٔ تازه امروز"
#: three spoken words; the title renderer keeps a word lit until the next one starts, so the «no word lit» frame is the one BEFORE the first word
WORDS = [{"w": "قهوهٔ", "s": 0.6, "e": 1.0}, {"w": "تازه", "s": 1.3, "e": 1.7}, {"w": "امروز", "s": 2.0, "e": 2.4}]
ACTIVE_AT = (0.8, 1.5, 2.2)
IDLE_AT = 0.45                      # after every entrance animation (<= 0.3 s) and before the first word (0.6 s)


def _lum(img):
    """WCAG relative luminance per pixel of an RGB array."""
    import numpy as np

    s = img / 255.0
    lin = np.where(s <= 0.03928, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def _item(key):
    style = dict(CAPTION_STYLES[key]["style"])
    style.pop("position", None)
    return {**style, "text": TEXT, "at": 0.0, "duration": 3.0, "words": WORDS, "x": 0.5, "y": 0.5, "align": "center"}


class InkOnTests(SimpleTestCase):
    def test_letters_follow_the_box_colour(self):
        self.assertEqual(titles.ink_on("#ffd400"), "#111111")       # the yellow marker
        self.assertEqual(titles.ink_on("#ffffff"), "#111111")
        self.assertEqual(titles.ink_on("#39ff88"), "#111111")
        self.assertEqual(titles.ink_on("#111111"), "#ffffff")       # what the old karaoke look had: a dark box
        self.assertEqual(titles.ink_on("#000000"), "#ffffff")
        self.assertEqual(titles.ink_on("#1d3fa6"), "#ffffff")

    def test_the_marker_word_is_never_painted_in_the_box_colour(self):
        for box in ("#111111", "#ffd400", "#ffffff", "#1d6fe0", "#e63946", "#39ff88", "#000000"):
            ass = titles.build_ass([{"text": "یک دو", "at": 0, "duration": 2, "hl_mode": "box", "hl_color": box,
                                     "words": [{"w": "یک", "s": 0.0, "e": 1.0}, {"w": "دو", "s": 1.0, "e": 2.0}]}], W, H)
            ink = titles._c(titles.ink_on(box))
            self.assertIn("\\1c" + ink, ass, box)
            self.assertNotEqual(titles.ink_on(box), box)

    def test_karaoke_is_the_yellow_marker_now(self):
        st = CAPTION_STYLES["karaoke"]["style"]
        self.assertEqual((st["hl_mode"], st["hl_color"]), ("box", "#ffd400"))


class RenderedStylesTests(SimpleTestCase):
    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def test_the_spoken_word_is_readable_in_every_look(self):
        import numpy as np

        self.assertEqual(len(CAPTION_STYLES), 7)
        for key in CAPTION_STYLES:
            item = _item(key)
            idle = render_frame([item], IDLE_AT, W, H)
            self.assertTrue((abs(idle - 32).max(axis=2) > 40).sum() > 200, f"{key}: the caption is on screen before the first word")
            for t in ACTIVE_AT:
                frame = render_frame([item], t, W, H)
                changed = abs(frame - idle).max(axis=2) > 24
                if changed.sum() < 20:
                    # a look that deliberately does not flash the word («lower»: same colour): the whole caption must read instead
                    self.assertEqual(item["hl_color"], item["color"], f"{key}@{t}: the spoken word does not change but should")
                    changed = abs(frame - 32).max(axis=2) > 40
                ys, xs = np.nonzero(changed)
                region = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
                lum = _lum(region).ravel()
                dark, light = float(np.percentile(lum, 5)), float(np.percentile(lum, 95))
                ratio = (light + 0.05) / (dark + 0.05)
                self.assertGreaterEqual(ratio, 4.5, f"{key}@{t}s: the spoken word's region has contrast {ratio:.2f}:1 (a flat blob?)")
                self.assertGreater(float(region.std()), 25.0, f"{key}@{t}s: the spoken word's region is uniform")
                self.assertGreater(light, 0.18, f"{key}@{t}s: the spoken word's region is uniformly dark")

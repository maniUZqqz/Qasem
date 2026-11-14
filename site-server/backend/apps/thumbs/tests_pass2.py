"""دورِ دومِ آزمونِ چغر (۱۴۰۵/۰۸/۲۳): ایرادهایی که با استفادهٔ واقعی از تامنیل‌ساز برای «چغر» پیدا شد.

* موضوعِ «چغر؛ دستیار هوش مصنوعیِ مربی‌ها …»: عنوان نباید وسطِ «هوش | مصنوعی» بریده شود و توضیحِ پس از «؛» زیرعنوان است؛
* «*یک دقیقه*؟»: علامتِ چسبیده به واژهٔ پررنگ با فاصله جدا نشود؛
* پوسترِ رترو در استوری/ریلز: برچسبِ بالا زیرِ نوارِ بالای برنامه نیفتد؛
* بدونِ عکسِ سوژه و با لوگو: «نشانِ برند» جای حلقهٔ خالی را می‌گیرد.
"""
import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from . import hooks, phrases, typo
from . import formats as F
from . import render as R
from .styles import STYLES

TOPIC = "چغر؛ دستیار هوش مصنوعیِ مربی‌ها برای برنامهٔ ورزشی و غذایی"


class ClauseTopicTests(SimpleTestCase):
    def test_semicolon_splits_title_and_descriptor(self):
        tp = phrases.parse_topic(TOPIC)
        self.assertEqual(tp.main, "چغر")
        self.assertTrue(tp.inner.startswith("دستیار هوش مصنوعیِ"), tp.inner)

    def test_time_and_short_tails_are_not_split(self):
        self.assertEqual(phrases.parse_topic("ساعت ۱۰:۳۰ تمرین").main, "ساعت ۱۰:۳۰ تمرین")
        self.assertEqual(phrases.parse_topic("تمرین؛ بله").main, "تمرین؛ بله")          # توضیحِ تک‌واژه‌ای جدا نمی‌شود

    def test_clip_never_cuts_inside_a_compound(self):
        for n in range(1, 7):
            head, rest = phrases.clip("دستیار هوش مصنوعیِ مربی‌ها برای برنامهٔ تناسب اندام", n)
            self.assertFalse(head.endswith("هوش") or head.endswith("تناسب"), (n, head))
            self.assertFalse(rest.startswith("مصنوعی") or rest.startswith("اندام"), (n, rest))

    def test_rule_ideas_build_clean_titles_around_the_name(self):
        ideas = hooks.rule_ideas(TOPIC, fmt="story", count=8, store_name="چغر")
        self.assertGreaterEqual(len(ideas), 5)
        for i in ideas:
            plain = typo.plain(i["title"])
            self.assertIn("چغر", plain, i["title"])
            self.assertNotIn("مصنوعی", plain, i["title"])
            self.assertFalse(plain.rstrip("؟").endswith("هوش"), plain)
            self.assertFalse(i["subtitle"].startswith("مصنوعی"), i["subtitle"])
        self.assertTrue(any(i["subtitle"].startswith("دستیار هوش مصنوعی") for i in ideas))


class GluedPunctuationTests(SimpleTestCase):
    def test_question_mark_stays_on_the_highlighted_word(self):
        lines, marked = typo.parse_marked("در کمتر از *یک دقیقه*؟")
        self.assertTrue(marked)
        self.assertEqual([w for w, _ in lines[0]], ["در", "کمتر", "از", "یک", "دقیقه؟"])
        self.assertEqual([f for _, f in lines[0]], [False, False, False, True, True])

    def test_spaced_and_leading_marks_are_unchanged(self):
        self.assertEqual(typo.parse_marked("کمتر از *یک دقیقه* ؟")[0][0][-1], ("؟", False))
        self.assertEqual(typo.parse_marked("*چغر*، دستیار")[0][0], [("چغر،", True), ("دستیار", False)])
        self.assertEqual(typo.plain("کمتر از *یک دقیقه*؟"), "کمتر از یک دقیقه؟")


def _inputs(logo=False, subject=False):
    inp = R.Inputs(brand_colors=["#126F85", "#163F75"], store_name="چغر")
    if logo:
        tile = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
        mark = Image.new("RGBA", (180, 90), (22, 63, 117, 255))
        tile.alpha_composite(mark, (60, 105))
        inp.logo = tile
    return inp


class StoryKickerAndEmblemTests(SimpleTestCase):
    def _spec(self, style, fmt, **content):
        raw = {"format": fmt, "style": style, "content": {"title": "چغر", "kicker": "برای مربی‌ها", "subtitle": "برنامه در کمتر از یک دقیقه", **content}}
        return R.clean_spec(raw, STYLES)

    def test_retro_kicker_is_below_the_story_top_bar(self):
        res = R.render(self._spec("retro_poster", "story"), _inputs(), scale=0.4, keep_layers=True)
        fmt = F.get("story")
        avoid = F.avoid_rects(fmt, res.size)
        label = next(layer for layer in res.layers if layer["name"] == "برچسبِ بالا")
        box = label.get("box") or label.get("bbox") or label.get("rect")
        self.assertIsNotNone(box, label)
        x0, y0, x1, y1 = box[:4]
        for a in avoid:
            ix, iy = min(x1, a[2]) - max(x0, a[0]), min(y1, a[3]) - max(y0, a[1])
            self.assertFalse(ix > 0 and iy > 0, ("kicker under the app bar", box, a))

    def test_brand_emblem_replaces_the_empty_ring_when_a_logo_exists(self):
        with_logo = R.render(self._spec("minimal_luxury", "ig_portrait"), _inputs(logo=True), scale=0.4, keep_layers=True)
        without = R.render(self._spec("minimal_luxury", "ig_portrait"), _inputs(logo=False), scale=0.4, keep_layers=True)
        self.assertIn("نشانِ برند", [layer["name"] for layer in with_logo.layers])
        self.assertNotIn("نشانِ برند", [layer["name"] for layer in without.layers])
        self.assertIn(R.NO_SUBJECT_WARNING, with_logo.warnings)           # هنوز می‌گوید عکسِ سوژه نیست
        # مرکزِ حلقه دیگر خالی نیست: دیسکِ سفید با نشانِ تیره
        a = np.asarray(with_logo.image.convert("L"), dtype=np.float32)
        b = np.asarray(without.image.convert("L"), dtype=np.float32)
        self.assertGreater(float(np.abs(a - b).mean()), 0.5)

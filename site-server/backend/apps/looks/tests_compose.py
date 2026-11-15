"""ساختنِ دستورِ تصویر از سبک: عکسِ محصول فقط «صحنه و نور»، پوستر دستورِ کامل، پس‌زمینه بدونِ آدم، سبکِ نامناسب ⇒ توضیحِ فارسی؛ پیشنهاد برای فروشگاه."""
from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.stores.models import Store

from . import compose, fit, library

User = get_user_model()

ILLUSTRATED = ["anime_90s_cel", "claymation_stopmotion", "pixel_art_16bit", "paper_cutout", "flat_vector_motion", "die_cut_sticker", "comic_ink", "toy_brick_3d",
               "watercolour_storybook", "risograph_print"]


class ComposeTests(SimpleTestCase):
    def test_product_preserving_kinds_refuse_an_illustrated_look_with_a_persian_explanation(self):
        for key in ILLUSTRATED:
            self.assertIn(key, library.STYLES, key)
            for kind in compose.PRODUCT_KINDS:
                with self.assertRaises(compose.LookError) as cm:
                    compose.compose(key, kind)
                self.assertEqual(cm.exception.code, "look_changes_product")
                msg = cm.exception.message_fa
                self.assertIn(library.STYLES[key]["name_fa"], msg)
                self.assertTrue(re.search(r"[؀-ۿ]", msg) and "پوستر" in msg and "عکسِ محصول" in msg, msg)
                # هر سه سبکِ مجازی که پیشنهاد می‌شود واقعاً مجاز است
                for name in compose.safe_names(3):
                    self.assertIn(f"«{name}»", msg)
            self.assertEqual(compose.public_check(key, "PRODUCT_SHOT")["ok"], False)
            self.assertEqual(compose.public_check(key, "POSTER"), {"ok": True})
            self.assertTrue(compose.compose(key, "POSTER")["positive"])
            self.assertTrue(compose.compose(key, "NEW_IMAGE")["positive"])

    def test_a_product_safe_look_gives_only_scene_and_light_plus_the_product_guard(self):
        safe = [k for k, v in library.STYLES.items() if v["product_safe"]]
        self.assertTrue(safe)
        for key in safe:
            for kind in compose.PRODUCT_KINDS:
                c = compose.compose(key, kind)
                self.assertTrue(c["scene_only"])
                self.assertIn(fit.PRODUCT_GUARD, c["positive"])
                self.assertEqual(c["guard"], fit.PRODUCT_GUARD)
                body = c["positive"].replace(fit.PRODUCT_GUARD, "")
                self.assertIsNone(fit.DENY.search(body.lower()), (key, body))
                for frag in fit.scene_fragments(library.STYLES[key]):
                    self.assertIn(frag, c["positive"])
                self.assertIn("altered product", c["negative"])
                self.assertIn("changed logo", c["negative"])
            full = compose.compose(key, "POSTER")
            self.assertFalse(full["scene_only"])
            self.assertNotIn(fit.PRODUCT_GUARD, full["positive"])

    def test_theme_colours_reach_the_product_kinds_only_as_scene_colour_words(self):
        c = compose.compose("cinematic_realistic", "PRODUCT_SHOT", theme_key="warm_sunset")
        self.assertIn("warm golden hour palette", c["positive"])
        self.assertEqual(c["palette"], library.THEMES["warm_sunset"]["palette"])
        for tk, t in library.THEMES.items():
            c = compose.compose("cinematic_realistic", "ENHANCED", theme_key=tk)
            for frag in fit.fragments(c["positive"]):
                if frag != fit.PRODUCT_GUARD and frag not in library.STYLES["cinematic_realistic"]["image_positive"] and frag != library.STYLES["cinematic_realistic"]["lighting"]:
                    self.assertIsNone(fit.DENY.search(frag.lower()), (tk, frag))

    def test_text_and_chart_words_never_reach_a_prompt(self):
        for key in library.STYLES:
            for kind in ("POSTER", "NEW_IMAGE", "THUMB_BG", "SAMPLE"):
                c = compose.compose(key, kind)
                for frag in fit.fragments(c["positive"]):
                    self.assertIsNone(compose.TEXT_FRAGMENT.search(frag), (key, kind, frag))
                self.assertIn("text", c["negative"])

    def test_background_and_sample_kinds_have_no_person_words(self):
        for key in library.STYLES:
            for kind in compose.SUBJECTLESS_KINDS:
                for frag in fit.fragments(compose.compose(key, kind)["positive"]):
                    self.assertIsNone(compose.SUBJECT_FRAGMENT.search(frag), (key, kind, frag))

    def test_hints_palette_and_brand_colours(self):
        c = compose.compose("noir_bw", "POSTER")
        self.assertEqual(c["palette"], library.STYLES["noir_bw"]["palette"])
        self.assertTrue(4 <= c["hints"]["steps"] <= 60 and c["hints"]["guidance"] > 0 and c["hints"]["model"])
        self.assertEqual(c["brand_colors"], [])
        c2 = compose.compose("noir_bw", "POSTER", theme_key="mono_noir", notes="  یادداشت  ")
        self.assertEqual(c2["theme"], "mono_noir")
        self.assertEqual(c2["palette"], library.THEMES["mono_noir"]["palette"])

    def test_bad_input_raises_lookerror_with_persian_text(self):
        for args, code in ((("nope", "POSTER"), "unknown_look"), (("noir_bw", "WRONG"), "bad_kind")):
            with self.assertRaises(compose.LookError) as cm:
                compose.compose(*args)
            self.assertEqual(cm.exception.code, code)
            self.assertTrue(re.search(r"[؀-ۿ]", cm.exception.message_fa))
        with self.assertRaises(compose.LookError) as cm:
            compose.compose("noir_bw", "POSTER", theme_key="no_theme")
        self.assertEqual(cm.exception.code, "unknown_theme")

    def test_ensure_in_prompt_keeps_the_director_text_and_adds_missing_fragments(self):
        c = compose.compose("noir_bw", "PRODUCT_SHOT")
        out = compose.ensure_in_prompt("a bottle on a table, soft light", c)
        self.assertTrue(out.startswith("a bottle on a table"))
        for frag in fit.fragments(c["positive"]):
            self.assertIn(frag.lower(), out.lower())
        self.assertEqual(compose.ensure_in_prompt(out, c), out, "تکراری اضافه نمی‌شود")
        self.assertIn("altered product", compose.merge_negative("blurry", c))

    def test_look_block_for_the_ai_director(self):
        pos = compose.look_block(compose.compose("anime_90s_cel", "POSTER"))
        self.assertIn("Look chosen by the store owner", pos)
        self.assertIn("recognisable", pos)
        scene = compose.look_block(compose.compose("noir_bw", "PRODUCT_SHOT"))
        self.assertIn("PRODUCT RULE", scene)
        self.assertIn("ONLY the scene", scene)


class SuggestTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("looks-owner", password="x")

    def store(self, name="فروشگاه", **kw):
        return Store.objects.create(owner=self.owner, name=name, **kw)

    def test_chagher_style_profile_gets_suggestions_from_its_own_profile_only(self):
        chagher = self.store("چغر", business_type="اپلیکیشن و نرم‌افزار", description="دستیار هوش مصنوعیِ مربی‌های باشگاه و ورزش؛ پیش‌نویسِ برنامهٔ تمرین",
                             target_audience="مربی‌های باشگاه", colors={"primary": "#126F85", "secondary": "#163F75"})
        s = library.suggest(chagher)
        self.assertTrue(s["matched"])
        self.assertTrue(3 <= len(s["looks"]) <= 5)
        self.assertEqual(len({x["look"] for x in s["looks"]}), len(s["looks"]))
        for x in s["looks"]:
            self.assertIn(x["look"], library.STYLES)
            self.assertTrue(x["reason_fa"] and x["business_fa"])
        self.assertEqual({x["business"] for x in s["looks"]}, {"tech", "fitness"})
        self.assertEqual(len(s["themes"]), 2)
        for t in s["themes"]:
            self.assertIn(t["theme"], library.THEMES)
        self.assertIn("کسب‌وکار", s["basis_fa"])
        # هیچ نگاشتِ ویژه‌ای برای یک فروشگاهِ خاص نیست: همان پروفایل با نامِ دیگر ⇒ همان پیشنهاد
        twin = self.store("هر نامی", business_type=chagher.business_type, description=chagher.description, target_audience=chagher.target_audience, colors=chagher.colors)
        self.assertEqual(library.suggest(twin), s)

    def test_business_types_map_to_their_groups_and_unknown_gets_generic_choices(self):
        cases = {"پوشاک و مد": "fashion", "کافه و قنادی": "food", "طلا و جواهر": "jewelry", "آموزشگاه و دوره": "education", "گردشگری و هتل": "travel"}
        for text, group in cases.items():
            s = library.suggest(self.store(text, business_type=text))
            self.assertTrue(s["matched"], text)
            self.assertEqual(s["looks"][0]["business"], group, text)
        empty = library.suggest(self.store("بی‌نوع"))
        self.assertFalse(empty["matched"])
        self.assertEqual(empty["looks"][0]["business"], "generic")
        self.assertEqual(empty["themes"], [])
        self.assertTrue(empty["basis_fa"])

    def test_theme_suggestions_follow_the_brand_colour(self):
        warm = library.suggest(self.store("a", business_type="طلا", colors={"primary": "#D4AF37"}))
        cool = library.suggest(self.store("b", business_type="طلا", colors={"primary": "#1D4ED8"}))
        self.assertNotEqual([t["theme"] for t in warm["themes"]], [t["theme"] for t in cool["themes"]])
        self.assertEqual(compose.brand_colors(self.store("c", colors={"primary": "#abcdef", "x": "bad"})), ["#ABCDEF"])

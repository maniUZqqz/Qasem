"""دورِ اصلاحِ تامنیل‌ساز (۱۴۰۵/۰۸/۲۳): هر مشکلی که بازبین دیده بود یک آزمونِ ماندگار دارد.

* لوگوی «خودکار» هیچ‌وقت روی عنوان/زیرعنوان/برچسب/نشان نمی‌نشیند (۱۲۰ ترکیبِ سبک × قالب، دو نسخهٔ A/B)؛
* نشانِ گردِ قیمت/تخفیف روی متن نمی‌افتد؛
* بدونِ عکسِ سوژه، «انفجار و جرقهٔ جاپرکن» نیست و هشدارِ فارسی می‌آید؛ عکسِ ساده (گرادیان) سوژه حساب نمی‌شود؛
* کادرِ «عدد» فارسی می‌شود؛ خط‌های اجباریِ «|» عنوان را به نقطهٔ ریز تبدیل نمی‌کنند؛
* نسخه‌های A/B با چشم از هم جدا هستند؛
* ایده‌پردازیِ بدونِ هوش مصنوعی: عنوان‌ها وسطِ جمله تمام نمی‌شوند، زیرعنوان خالی نیست، «جمله» با «عبارتِ اسمی» فرق دارد؛
* دلیلِ نبودنِ هوش مصنوعی وسطِ کلمه بریده نمی‌شود.
"""
import io
import math

import numpy as np
from django.test import SimpleTestCase, TestCase
from PIL import Image

from . import fixtures, hooks, phrases, typo
from . import formats as F
from . import primitives as P
from . import render as R
from .styles import STYLES
from .tests_render import CONTENT, SCALE, inputs, spec


def area(a, b) -> float:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    return ix * iy if ix > 0 and iy > 0 else 0.0


def circle_hits_rect(bbox, rect, shrink=0.95) -> bool:
    cx, cy, r = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, (bbox[2] - bbox[0]) / 2 * shrink
    dx, dy = max(rect[0] - cx, 0, cx - rect[2]), max(rect[1] - cy, 0, cy - rect[3])
    return math.hypot(dx, dy) < r


class AutoLogoTests(SimpleTestCase):
    #: شکلِ لوگو: کشیده، مربع (مثلِ لوگوی چغر ۶۴۰×۶۴۰) و بلند. لوگوی مربع کاشیِ بلندتری می‌سازد و جلدِ مجله در ۱۶:۹ را بی‌گوشهٔ آزاد می‌کرد
    LOGOS = {"wide": (300, 120), "square": (400, 400), "tall": (160, 320)}

    def with_logo(self, shape: str):
        inp = inputs(logo=True)
        w, h = self.LOGOS[shape]
        inp.logo = Image.new("RGBA", (w, h), (20, 120, 140, 255))
        return inp

    def check(self, res, ctx):
        logo = next((x for x in res.layers if x["kind"] == "logo"), None)
        self.assertIsNotNone(logo, ctx)
        for t in res.texts:
            if not t.get("deco"):
                self.assertEqual(area(logo["bbox"], t["bbox"]), 0, (ctx, "لوگو روی متن", t["name"], logo["bbox"], t["bbox"]))
        for x in res.layers:
            if x["kind"] == "badge":
                self.assertEqual(area(logo["bbox"], x["bbox"]), 0, (ctx, "لوگو روی برچسب/نشان", x["name"]))

    def test_default_logo_never_covers_text_or_badges(self):
        """همهٔ ۱۵ سبک × ۸ قالب با لوگو و موقعیتِ «خودکار» (پیش‌فرض)، برای لوگوی کشیده و مربع."""
        for shape in ("wide", "square"):
            inp = self.with_logo(shape)
            for style in STYLES:
                for fmt in F.FORMATS:
                    with self.subTest(shape=shape, style=style, format=fmt):
                        self.check(R.render(spec(style, fmt), inp, scale=SCALE), (shape, style, fmt))

    def test_default_logo_in_the_second_ab_variant_too(self):
        """نسخهٔ B (سوژه آن‌طرف) هم همین قاعده را دارد."""
        for shape in ("wide", "square"):
            inp = self.with_logo(shape)
            for style in STYLES:
                for fmt in F.FORMATS:
                    with self.subTest(shape=shape, style=style, format=fmt):
                        self.check(R.render(spec(style, fmt, colors={"variation": 1}), inp, scale=SCALE), (shape, style, fmt, "B"))

    def test_tall_logo_on_every_style_and_format(self):
        inp = self.with_logo("tall")
        for style in STYLES:
            for fmt in F.FORMATS:
                with self.subTest(style=style, format=fmt):
                    self.check(R.render(spec(style, fmt), inp, scale=SCALE), ("tall", style, fmt))

    def test_square_logo_on_the_busy_magazine_cover_in_16_9(self):
        """جلدِ مجله در ۱۶:۹: سرلوحه بالا، ستونِ تیتر راست، نشان، و ناحیهٔ پرهیزِ آپارات پایین‌چپ ⇒ لوگوی مربع باید لغزیده یا کوچک شود."""
        content = {**CONTENT, "badge": "تازه"}
        for fmt in ("aparat", "youtube", "telegram"):
            with self.subTest(format=fmt):
                res = R.render(spec("magazine_cover", fmt, content=content), self.with_logo("square"), scale=SCALE)
                self.check(res, ("magazine_cover", fmt))
                logo = next(x for x in res.layers if x["kind"] == "logo")["bbox"]
                self.assertGreaterEqual((logo[2] - logo[0]) / res.size[0], 0.045, "لوگو بیش از حد کوچک شد")

    def test_the_reported_repro_cases(self):
        """بازبین: «رویارویی» روی پستِ ۴:۵ و «قهرمانِ محصول» روی پستِ مربع، عنوانِ «*۷* اشتباهِ رایج در تمرینِ پا»."""
        inp = self.with_logo("square")
        for style, fmt in (("versus", "ig_portrait"), ("product_hero", "ig_square"), ("versus", "story"), ("split_ba", "ig_portrait"),
                           ("neon", "telegram"), ("magazine_cover", "youtube"), ("face_text", "telegram"), ("pinterest_collage", "telegram"),
                           ("cinema_poster", "telegram"), ("sticker_outline", "story")):
            with self.subTest(style=style, format=fmt):
                sp = spec(style, fmt, content={**CONTENT, "title": "*۷* اشتباهِ رایج در تمرینِ پا"})
                res = R.render(sp, inp, scale=SCALE)
                self.check(res, (style, fmt))
                title = next(t for t in res.texts if t["name"].startswith("عنوان"))
                logo = next(x for x in res.layers if x["kind"] == "logo")
                self.assertEqual(area(logo["bbox"], title["bbox"]), 0)

    def test_manual_position_is_still_respected(self):
        inp = inputs(logo=True)
        quad = {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1)}
        for pos, (qx, qy) in quad.items():
            with self.subTest(pos=pos):
                res = R.render(spec("face_text", "ig_square", logo={"show": True, "position": pos}), inp, scale=SCALE)
                b = next(x for x in res.layers if x["kind"] == "logo")["bbox"]
                cx, cy = (b[0] + b[2]) / 2 / res.size[0], (b[1] + b[3]) / 2 / res.size[1]
                self.assertEqual((cx > 0.5, cy > 0.5), (bool(qx), bool(qy)), (pos, b))

    def test_logo_can_be_hidden(self):
        res = R.render(spec("face_text", "youtube", logo={"show": False, "position": "auto"}), inputs(logo=True), scale=SCALE)
        self.assertFalse(any(x["kind"] == "logo" for x in res.layers))

    def test_logo_shrinks_when_every_corner_is_busy(self):
        """متنِ پُرِ همهٔ لبه‌ها: لوگو باز هم یک جا می‌گیرد (کم‌برخوردترین) و رندر نمی‌ترکد."""
        long_ = "عنوانی بسیار بلند که همهٔ پهنا را می‌گیرد و باید جا شود"
        res = R.render(spec("versus", "ig_square", content={**CONTENT, "title": long_, "subtitle": long_}), inputs(logo=True), scale=SCALE)
        self.assertTrue(any(x["kind"] == "logo" for x in res.layers))


class BadgePlacementTests(SimpleTestCase):
    STYLES_WITH_BADGE = ("face_text", "sticker_outline", "product_hero", "pinterest_collage", "magazine_cover", "retro_poster")

    def check(self, res, ctx):
        for x in res.layers:
            if x["name"] != "نشانِ تخفیف/قیمت":
                continue
            for t in res.texts:
                if t.get("deco") or t["name"].startswith("متنِ نشان"):
                    continue
                self.assertFalse(circle_hits_rect(x["bbox"], t["bbox"], 0.9), (ctx, "نشان روی متن", t["name"], x["bbox"], t["bbox"]))

    def test_badge_never_sits_on_title_or_subtitle(self):
        inp = inputs()
        for style in self.STYLES_WITH_BADGE:
            for fmt in F.FORMATS:
                for var in (0, 1):
                    with self.subTest(style=style, format=fmt, variation=var):
                        self.check(R.render(spec(style, fmt, colors={"variation": var}), inp, scale=SCALE), (style, fmt, var))

    def test_reported_cases_face_text_variant_b_and_pinterest_on_youtube(self):
        inp = inputs()
        content = {**CONTENT, "subtitle": "قبل از شروع ببینید", "badge": "تازه"}
        for style, var in (("face_text", 1), ("face_text", 0), ("pinterest_collage", 0), ("pinterest_collage", 1)):
            with self.subTest(style=style, variation=var):
                res = R.render(spec(style, "youtube", content=content, colors={"variation": var}), inp, scale=SCALE)
                self.check(res, (style, var))
                sub = next(t for t in res.texts if t["name"] == "زیرعنوان")
                badge = next(x for x in res.layers if x["name"] == "نشانِ تخفیف/قیمت")
                self.assertFalse(circle_hits_rect(badge["bbox"], sub["bbox"], 0.95))


class NoSubjectTests(SimpleTestCase):
    PLACEHOLDER_NAMES = ("انفجارِ جایگزین", "جرقه", "شکلِ جایگزین")

    def test_no_cartoon_placeholder_in_any_style_or_format(self):
        inp = R.Inputs(brand_colors=["#126F85", "#163F75"])
        for style in STYLES:
            for fmt in F.FORMATS:
                with self.subTest(style=style, format=fmt):
                    res = R.render(spec(style, fmt), inp, scale=SCALE)
                    names = " ".join(x["name"] for x in res.layers)
                    for bad in self.PLACEHOLDER_NAMES:
                        self.assertNotIn(bad, names)
                    self.assertGreater(float(np.asarray(res.image.convert("L"), dtype=np.float32).std()), 18)

    def test_recommended_styles_warn_when_there_is_no_photo(self):
        inp = R.Inputs()
        for style, sd in STYLES.items():
            if sd.subject != "recommended":
                continue
            with self.subTest(style=style):
                res = R.render(spec(style, "youtube" if "youtube" in sd.formats else sd.formats[0]), inp, scale=SCALE)
                self.assertIn(R.NO_SUBJECT_WARNING, res.warnings)

    def test_with_a_subject_there_is_no_warning(self):
        res = R.render(spec("face_text", "youtube"), inputs(), scale=SCALE)
        self.assertNotIn(R.NO_SUBJECT_WARNING, res.warnings)

    def test_blank_gradient_photo_is_not_a_subject(self):
        grad = P.gradient((600, 600), [(0.0, "#2563eb"), (1.0, "#93c5fd")], 40).convert("RGB")
        self.assertTrue(P.is_blank(grad))
        self.assertTrue(P.is_blank(Image.new("RGB", (400, 300), "#ffffff")))
        radial = P.radial((500, 500), (250, 250), 400, [(0.0, "#ffffff"), (1.0, "#334155")]).convert("RGB")
        self.assertTrue(P.is_blank(radial))
        # آدم، کالا روی زمینهٔ سفید و منظره «ساده» نیستند
        person = Image.new("RGB", (640, 820), "#ffffff")
        person.paste(fixtures.person().convert("RGB"), (0, 0), fixtures.person().getchannel("A"))
        self.assertFalse(P.is_blank(person))
        prod = Image.new("RGB", (520, 760), "#ffffff")
        prod.paste(fixtures.product().convert("RGB"), (0, 0), fixtures.product().getchannel("A"))
        self.assertFalse(P.is_blank(prod))
        self.assertFalse(P.is_blank(fixtures.scene()))

    def test_decorative_backdrop_without_a_product_is_blank_but_small_products_are_not(self):
        """نمونهٔ ساختگیِ «عکسِ محصولِ جای‌نگهدار»: گرادیانِ فیروزه‌ای با دو نوارِ کم‌رنگ و چند متوازی‌الاضلاعِ ریز و هیچ کالایی."""
        from PIL import ImageDraw

        from PIL import ImageFilter

        for alpha in (28, 20, 12):                      # ۲۸ ≈ فایلِ واقعیِ «backdrop-teal»؛ کم‌رنگ‌تر هم ساده است
            bg = P.gradient((720, 960), [(0.0, "#16707f"), (1.0, "#163f75")], 60).convert("RGBA")
            ov = Image.new("RGBA", bg.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(ov)
            d.rounded_rectangle([30, 590, 560, 630], radius=20, fill=(255, 255, 255, alpha))
            d.rounded_rectangle([145, 660, 590, 700], radius=20, fill=(255, 255, 255, alpha))
            d.polygon([(505, 175), (585, 175), (565, 195), (485, 195)], fill=(255, 255, 255, alpha + 6))
            backdrop = Image.alpha_composite(bg, ov.filter(ImageFilter.GaussianBlur(3))).convert("RGB")
            self.assertTrue(P.is_blank(backdrop), alpha)
        for frac in (0.25, 0.4):                       # کالا روی زمینهٔ نرم؛ از ۱۸٪ِ پهنا به بالا باید «سوژه» حساب شود
            canvas = P.gradient((900, 1200), [(0.0, "#e8eef5"), (1.0, "#cfd9e6")], 60).convert("RGB")
            pr = fixtures.product()
            w = int(900 * frac)
            pr = pr.resize((w, int(w * pr.height / pr.width)), Image.Resampling.LANCZOS)
            canvas.paste(pr.convert("RGB"), ((900 - w) // 2, (1200 - pr.height) // 2), pr.getchannel("A"))
            self.assertFalse(P.is_blank(canvas), frac)


class DigitsAndForcedLinesTests(SimpleTestCase):
    def test_numeric_only_strings_become_persian_but_latin_text_is_untouched(self):
        self.assertEqual(typo.to_fa_digits("7"), "۷")
        self.assertEqual(typo.to_fa_digits("20%"), "۲۰%")
        self.assertEqual(typo.to_fa_digits("10:30"), "۱۰:۳۰")
        self.assertEqual(typo.to_fa_digits("1,250"), "۱٬۲۵۰")
        for keep in ("HIIT", "3D", "4K", "Wi-Fi 6", "iPhone 16", ""):
            self.assertEqual(typo.to_fa_digits(keep), keep)

    def test_big_number_field_is_drawn_with_persian_digits(self):
        res = R.render(spec("number_list", "ig_portrait", content={"number": "7", "title": "7 اشتباه رایج در تمرین پا"}), inputs(), scale=SCALE)
        num = next(t for t in res.texts if t["name"] == "عدد")
        self.assertEqual(num["text"], "۷")
        title = next(t for t in res.texts if t["name"] == "عنوان")
        self.assertFalse(any(ch in title["text"] for ch in "0123456789"), title["text"])

    def test_three_forced_lines_stay_readable(self):
        """«قبل |*۳۰ روز*| بعد» روی پوسترِ سینمایی: سه خط، نه یک نقطهٔ ۹ پیکسلی."""
        for fmt in ("poster", "pinterest", "story", "ig_portrait"):
            with self.subTest(format=fmt):
                sp = spec("cinema_poster", fmt, content={"title": "قبل |*۳۰ روز*| بعد", "subtitle": "با چغر شروع کنید"})
                res = R.render(sp, inputs(), scale=SCALE)
                t = next(t for t in res.texts if t["name"] == "عنوانِ پوستر")
                self.assertEqual(t["lines"], 3)
                self.assertGreaterEqual(t["px"] / res.size[0], 0.05, t)

    def test_forced_lines_in_other_styles(self):
        for style in ("face_text", "neon", "number_list", "minimal_luxury", "retro_poster"):
            with self.subTest(style=style):
                res = R.render(spec(style, "ig_portrait", content={"title": "الف|ب|ج|د", "subtitle": "x"}), inputs(), scale=SCALE)
                t = next(t for t in res.texts if t["name"].startswith("عنوان"))
                self.assertGreaterEqual(t["px"] / res.size[0], 0.03, t)

    def test_text_fit_does_not_shrink_below_floor_for_forced_breaks(self):
        st = typo.TextStyle(font_key="lalezar", weight=400)
        blk = typo.render_text("اول|دوم|سوم", 600, 420, st, max_lines=2, min_px=12, max_px=200)
        self.assertIsNotNone(blk)
        self.assertEqual(blk.lines, 3)
        self.assertGreater(blk.px, 60)


class VariantsDifferTests(SimpleTestCase):
    """نسخه‌های A/B/…/F باید با چشم فرق داشته باشند (قبلاً A و B و D در چیدمانِ سوژه‌وسطی یکی بودند)."""

    @staticmethod
    def mad(a: Image.Image, b: Image.Image) -> float:
        x = np.asarray(a.convert("RGB").resize((64, 64)), dtype=np.float32)
        y = np.asarray(b.convert("RGB").resize((64, 64)), dtype=np.float32)
        return float(np.abs(x - y).mean())

    def renders(self, style, fmt, n=6):
        from . import services

        sp = spec(style, fmt)
        plans = services.variation_plan(sp, n)
        inp = inputs(logo=True)
        return plans, [R.render(s, inp, scale=0.22).image for s, _ in plans]

    def test_every_pair_is_distinguishable(self):
        for style, fmt in (("number_list", "ig_portrait"), ("number_list", "youtube"), ("face_text", "ig_portrait"), ("minimal_luxury", "ig_square"),
                           ("product_hero", "ig_portrait"), ("question_hook", "story"), ("neon", "ig_portrait"), ("sticker_outline", "ig_square"),
                           ("magazine_cover", "ig_portrait"), ("quote_card", "ig_square"), ("cinema_poster", "poster")):
            plans, ims = self.renders(style, fmt)
            self.assertEqual(len(plans), 6)
            for i in range(6):
                for j in range(i + 1, 6):
                    with self.subTest(style=style, format=fmt, pair=f"{chr(65 + i)}{chr(65 + j)}"):
                        self.assertGreater(self.mad(ims[i], ims[j]), 6.0)

    def test_a_vs_b_and_a_vs_d_are_clearly_different_on_centred_layouts(self):
        for style, fmt in (("number_list", "ig_portrait"), ("face_text", "ig_portrait"), ("product_hero", "ig_portrait"), ("minimal_luxury", "ig_square")):
            plans, ims = self.renders(style, fmt, 4)
            with self.subTest(style=style, format=fmt):
                self.assertGreater(self.mad(ims[0], ims[1]), 15.0)
                self.assertGreater(self.mad(ims[0], ims[3]), 15.0)

    def test_notes_are_persian_and_name_the_change(self):
        from . import services

        plans = services.variation_plan(spec("number_list", "ig_portrait"), 6)
        self.assertEqual(plans[0][1], "نسخهٔ اصلی")
        for _, note in plans[1:]:
            self.assertTrue(typo.is_rtl(note), note)
        self.assertIn("حال‌وهوای", plans[1][1])
        self.assertIn("فونتِ", plans[3][1])
        self.assertEqual(len({p[0]["colors"]["mood"] + p[0]["style"] + p[0]["font"] for p in plans[:4]}), 4)
        self.assertEqual(len(services.variation_plan(spec("neon", "youtube"), 99)), services.MAX_VARIANTS)
        self.assertEqual(len(services.variation_plan(spec("neon", "youtube"), 0)), 1)

    def test_moods_of_a_variant_set_come_from_different_palette_branches(self):
        """با رنگِ برند «پرانرژی/گرم/سرد» یک پالت می‌سازند؛ جایگزین‌ها باید از شاخهٔ دیگر باشند."""
        from . import palette, services

        same_branch = {"vivid", "warm", "cool"}
        for base, alts in services.MOOD_ALTS.items():
            self.assertEqual(len(set(alts)), 3, base)
            self.assertNotIn(base, alts)
            self.assertLessEqual(len(set(alts) & same_branch), 1, (base, alts))
            for m in alts:
                self.assertIn(m, palette.MOODS)


# ───────────────────────────── ایده‌پردازیِ بدونِ هوش مصنوعی

AUDIENCE = ("مربی‌های باشگاه و مربی‌های شخصی که برای ورزشکارانشان برنامهٔ ورزشی و غذایی می‌نویسند؛ "
            "و ورزشکارانی که خودشان برنامهٔ مناسبِ محیطِ تمرین (خانه یا باشگاه) می‌خواهند.")
#: نمونه‌های ساختگی با همان ریخت و دشواریِ موردهای گزارش‌شده (نه متنِ واقعیِ فروشگاه)
PRODUCTS = [
    {"name": "برنامه‌سازِ دستیِ نمونه (بدونِ هوش مصنوعی)", "short": "مربی خودش جلسه‌ها و حرکت‌ها را می‌چیند و فایلِ برندشده می‌گیرد — فعلاً بدونِ هزینهٔ توکن"},
    {"name": "برنامهٔ ورزشی + غذایی با هوش مصنوعی", "short": "پیش‌نویسِ کاملِ برنامهٔ ورزشی و غذاییِ اختصاصیِ یک ورزشکار در کمتر از یک دقیقه — ۵۰ توکن"},
    {"name": "برنامهٔ تکی با هوش مصنوعی (فقط ورزشی یا فقط غذایی)", "short": "فقط برنامهٔ ورزشی یا فقط برنامهٔ غذایی — ۲۵ توکن"},
    {"name": "کتابخانهٔ حرکت‌ها و اسکنِ دستگاه", "short": "بیش از ۱٬۳۰۰ حرکتِ فارسی با گیف و عکس، و اسکنِ دستگاه‌های باشگاه با دوربین — فعلاً بدونِ هزینه"},
    {"name": "بستهٔ توکنِ «عادی» — ۵۰ توکن", "short": "اعتبارِ ساختنِ برنامه در چغر؛ هر ۵۰ توکن ۶۰۰٬۰۰۰ تومان"},
]
TOPICS = ["برنامهٔ ورزشی شخصی برای مبتدی‌ها در خانه", "رژیم غذایی برای افزایش وزن", "۷ اشتباه در تمرین پا", "تمرین شکم و پهلو", "چطور بدون باشگاه عضله بسازیم",
          "دمبل یا هالتر", "چای سبز", "عادت‌های سالم", "آیا کراتین برای مبتدی‌ها خوب است؟", "یوگا", "کتابخانهٔ حرکت‌ها و اسکنِ دستگاه برای مربی‌ها"]


def plain_words(text: str) -> list[str]:
    return typo.plain(text).split()


class IdeaQualityMixin:
    def assert_sound(self, text: str, ctx, *, allow_empty=False):
        plain = typo.plain(text)
        if not plain:
            self.assertTrue(allow_empty, (ctx, "متنِ خالی"))
            return
        words = plain.split()
        self.assertFalse(phrases.dangling(words[-1].rstrip("؟?!.")) and not plain.endswith(("؟", "?")), (ctx, "روی واژهٔ ناتمام تمام شد", plain))
        self.assertNotIn(words[0], phrases.COORD, (ctx, plain))
        self.assertEqual(plain.count("(") + plain.count(")"), 0, (ctx, "پرانتزِ باز/بسته", plain))
        for q in "«»":                                                                  # گیومه در عنوان نیاید
            self.assertNotIn(q, plain, (ctx, plain))
        for a, b in zip(words, words[1:]):                                              # «در در»، «اشتباه اشتباه»
            self.assertNotEqual(phrases.norm(a), phrases.norm(b), (ctx, "واژهٔ تکراری", plain))
        self.assertLessEqual(len(words), 12, (ctx, plain))

    def assert_ideas_sound(self, ideas, ctx):
        self.assertTrue(ideas, ctx)
        for i in ideas:
            self.assert_sound(i["title"], (ctx, i["formula"], "title"))
            self.assert_sound(i["subtitle"], (ctx, i["formula"], "subtitle"))
            self.assertTrue(typo.plain(i["subtitle"]), (ctx, i["formula"], "زیرعنوانِ خالی"))
            self.assertLessEqual(len(plain_words(i["title"])), 11, (ctx, i["title"]))
            self.assertEqual(i["title"].count("*") % 2, 0, (ctx, i["title"]))


class IdeaQualityTests(IdeaQualityMixin, SimpleTestCase):
    def test_every_topic_every_format_gives_sound_titles_and_subtitles(self):
        for topic in TOPICS:
            for fmt in F.FORMATS:
                with self.subTest(topic=topic, format=fmt):
                    self.assert_ideas_sound(hooks.rule_ideas(topic, fmt=fmt, count=8, audience=AUDIENCE, store_name="چغر"), (topic, fmt))

    def test_products_give_sound_titles_and_subtitles(self):
        for prod in PRODUCTS:
            for fmt in ("youtube", "ig_portrait", "ig_square", "story"):
                with self.subTest(product=prod["name"], format=fmt):
                    self.assert_ideas_sound(hooks.rule_ideas("x", fmt=fmt, count=8, product=prod, audience=AUDIENCE, store_name="چغر"), (prod["name"], fmt))

    def test_long_topic_is_cut_before_the_preposition_and_the_rest_becomes_the_subtitle(self):
        ideas = hooks.rule_ideas("برنامهٔ ورزشی شخصی برای مبتدی‌ها در خانه", fmt="youtube", count=8, audience=AUDIENCE)
        for i in ideas:
            self.assertFalse(typo.plain(i["title"]).endswith("برای"), i["title"])
        first = next(i for i in ideas if i["formula"] == "list_mistakes")
        self.assertEqual(typo.plain(first["title"]), "۵ اشتباهِ رایج در برنامهٔ ورزشی شخصی")
        self.assertEqual(first["subtitle"], "برای مبتدی‌ها در خانه")           # اطلاعات گم نشده است

    def test_no_title_ends_on_a_dangling_word(self):
        """نمونه‌های گزارش: «…شخصی برای»، «(بدونِ»، «…افزایش»، «…تمرین»، «…با را ببینید»، «…یا فقط غذایی)؟»."""
        bad_endings = {"برای", "با", "از", "در", "و", "یا", "را", "که", "بدونِ", "بدون", "افزایش", "یک"}
        for topic in TOPICS:
            for fmt in ("youtube", "ig_portrait"):
                for i in hooks.rule_ideas(topic, fmt=fmt, count=8, audience=AUDIENCE):
                    last = typo.plain(i["title"]).rstrip("؟?").split()[-1]
                    self.assertNotIn(phrases.norm(last), {phrases.norm(x) for x in bad_endings}, (topic, i["title"]))
        for prod in PRODUCTS:
            for i in hooks.rule_ideas("x", fmt="youtube", count=8, product=prod, audience=AUDIENCE):
                last = typo.plain(i["title"]).rstrip("؟?").split()[-1]
                self.assertNotIn(phrases.norm(last), {phrases.norm(x) for x in bad_endings}, (prod["name"], i["title"]))

    def test_lost_word_cases(self):
        """«رژیم غذایی برای افزایش *وزن*»: وزن نباید گم شود؛ «۷ اشتباه در تمرین *پا*» همان‌طور که کاربر نوشت."""
        for i in hooks.rule_ideas("رژیم غذایی برای افزایش وزن", fmt="youtube", count=8):
            blob = typo.plain(i["title"]) + " " + i["subtitle"]
            if "افزایش" in blob:
                self.assertIn("وزن", blob, i["title"])
        ideas = hooks.rule_ideas("۷ اشتباه در تمرین پا", fmt="youtube", count=8)
        listed = [i for i in ideas if i["number"]]
        self.assertEqual(len(listed), 1)
        self.assertEqual(typo.plain(listed[0]["title"]), "۷ اشتباه در تمرین پا")
        self.assertEqual(listed[0]["number"], "۷")
        for i in ideas:
            self.assertNotIn("۷ اشتباه در ۷", typo.plain(i["title"]))
            self.assertFalse(typo.plain(i["title"]).count("۷") > 1, i["title"])

    def test_audience_phrase_is_a_whole_group(self):
        self.assertEqual(hooks.audience_phrase(AUDIENCE), "مربی‌های باشگاه")
        self.assertEqual(hooks.audience_phrase("ورزشکاران"), "ورزشکاران")
        self.assertEqual(hooks.audience_phrase(""), "")
        ideas = hooks.rule_ideas("تمرین شکم و پهلو", fmt="youtube", count=8, audience=AUDIENCE)
        aud = [i for i in ideas if i["formula"] == "for_audience"]
        self.assertTrue(aud)
        self.assertEqual(typo.plain(aud[0]["title"]), "تمرین شکم و پهلو برای مربی‌های باشگاه")
        for i in ideas:                                                # «…شکم و پهلو» نباید «…شکم» بشود
            self.assertNotIn("تمرین شکم حرف", typo.plain(i["title"]))

    def test_how_to_topics_do_not_use_noun_only_formulas(self):
        ideas = hooks.rule_ideas("چطور بدون باشگاه عضله بسازیم", fmt="youtube", count=8)
        self.assertGreaterEqual(len(ideas), 4)
        for i in ideas:
            t = typo.plain(i["title"])
            for nonsense in ("را از اول بشناسید", "واقعاً جواب می‌دهد", "قبل و بعد", "اشتباهِ رایج در", "قدم‌به‌قدم یاد بگیرید"):
                self.assertNotIn(nonsense, t)
            self.assertIn("چطور بدون باشگاه عضله بسازیم", t)
        self.assertTrue(any(typo.plain(i["title"]).endswith("؟") for i in ideas))          # جمله‌ی پرسشی «؟» می‌گیرد
        q = hooks.rule_ideas("آیا کراتین برای مبتدی‌ها خوب است؟", fmt="youtube", count=8)
        self.assertTrue(q)
        for i in q:
            self.assertLessEqual(typo.plain(i["title"]).count("؟"), 1, i["title"])          # «؟؟» نشود

    def test_topic_kind_detection(self):
        for t, kind in (("برنامهٔ ورزشی", "noun"), ("چطور عضله بسازیم", "clause"), ("چرا همه ورزش می‌کنند", "clause"), ("آیا کراتین خوب است", "clause"),
                        ("تمرین راست‌دست", "noun"), ("مربی و ورزشکار", "noun"), ("دمبل یا هالتر", "noun")):
            with self.subTest(topic=t):
                self.assertEqual(phrases.parse_topic(t).kind, kind)

    def test_product_parentheses_and_dashes_move_to_the_subtitle(self):
        ideas = hooks.rule_ideas("x", fmt="ig_portrait", count=8, product=PRODUCTS[0], audience=AUDIENCE)
        for i in ideas:
            self.assertNotIn("(", i["title"] + i["subtitle"])
        hero = next(i for i in ideas if i["formula"] == "new_product")
        self.assertEqual(hero["title"], "برنامه‌سازِ دستیِ نمونه")
        self.assertEqual(hero["subtitle"], "مربی خودش جلسه‌ها و حرکت‌ها را می‌چیند و فایلِ برندشده می‌گیرد")
        pack = hooks.rule_ideas("x", fmt="ig_portrait", count=8, product=PRODUCTS[4])
        hero = next(i for i in pack if i["formula"] == "new_product")
        self.assertEqual(hero["title"], "بستهٔ توکنِ عادی")
        self.assertNotIn("تومان", hero["subtitle"])                    # قیمت فقط وقتی کاربر خواسته

    def test_product_subtitle_is_a_whole_clause_not_a_cut_sentence(self):
        for prod, want in ((PRODUCTS[1], "پیش‌نویسِ کاملِ برنامهٔ ورزشی و غذاییِ اختصاصیِ یک ورزشکار"),
                           (PRODUCTS[3], "بیش از ۱٬۳۰۰ حرکتِ فارسی با گیف و عکس")):
            hero = next(i for i in hooks.rule_ideas("x", fmt="ig_portrait", count=8, product=prod) if i["formula"] == "new_product")
            self.assertEqual(hero["subtitle"], want)

    def test_versus_from_a_parenthesis(self):
        ideas = hooks.rule_ideas("x", fmt="youtube", count=8, product=PRODUCTS[2])
        vs = [i for i in ideas if i["style"] == "versus"]
        self.assertTrue(vs)
        self.assertEqual(typo.plain(vs[0]["title"]), "فقط ورزشی یا فقط غذایی؟")
        self.assertEqual((vs[0]["label_a"], vs[0]["label_b"]), ("فقط ورزشی", "فقط غذایی"))
        self.assertEqual(hooks.split_versus("دمبل یا هالتر"), ("دمبل", "هالتر"))
        self.assertEqual(hooks.split_versus("الف یا اینکه ب"), ("الف", "ب"))
        self.assertIsNone(hooks.split_versus("دمبل"))
        d = [i for i in hooks.rule_ideas("دمبل یا هالتر", fmt="youtube", count=8) if i["style"] == "versus"]
        self.assertEqual(typo.plain(d[0]["title"]), "دمبل یا هالتر؟")          # نه «دمبل یا هالتر یا هالتر؟»

    def test_audience_formula_is_skipped_when_the_topic_already_has_a_for_clause(self):
        for i in hooks.rule_ideas("رژیم غذایی برای افزایش وزن", fmt="youtube", count=8, audience=AUDIENCE):
            self.assertNotEqual(i["formula"], "for_audience")

    def test_titles_are_unique_per_style(self):
        for topic in TOPICS:
            ideas = hooks.rule_ideas(topic, fmt="youtube", count=8)
            keys = [(typo.plain(i["title"]), i["style"]) for i in ideas]
            self.assertEqual(len(keys), len(set(keys)), topic)

    def test_still_no_invented_claims(self):
        for topic in TOPICS:
            for i in hooks.rule_ideas(topic, fmt="story", count=8, audience=AUDIENCE):
                for text in (i["title"], i["subtitle"], i["badge"], i["kicker"]):
                    for risky in ("درصد", "تومان", "ریال", "تخفیف", "٪", "%", "رایگان", "تضمین"):
                        self.assertNotIn(risky, text, (topic, text))

    def test_product_clause_with_risky_words_is_skipped(self):
        self.assertEqual(phrases.first_clause("ویرایش رایگان است؛ برنامه را در کمتر از یک دقیقه می‌سازد"), "برنامه را در کمتر از یک دقیقه می‌سازد")
        self.assertEqual(phrases.first_clause("هر ۵۰ توکن ۶۰۰٬۰۰۰ تومان"), "")


class PhraseToolsTests(SimpleTestCase):
    def test_clip_never_ends_on_a_function_word(self):
        cases = [("برنامهٔ ورزشی شخصی برای مبتدی‌ها در خانه", 3, "برنامهٔ ورزشی شخصی", "برای مبتدی‌ها در خانه"),
                 ("برنامهٔ ورزشی شخصی برای مبتدی‌ها در خانه", 4, "برنامهٔ ورزشی شخصی", "برای مبتدی‌ها در خانه"),
                 ("برنامهٔ ورزشی شخصی برای مبتدی‌ها در خانه", 5, "برنامهٔ ورزشی شخصی برای مبتدی‌ها", "در خانه"),
                 ("رژیم غذایی برای افزایش وزن", 3, "رژیم غذایی", "برای افزایش وزن"),
                 ("رژیم غذایی برای افزایش وزن", 5, "رژیم غذایی برای افزایش وزن", ""),
                 ("تمرین شکم و پهلو", 3, "تمرین شکم و پهلو", ""),            # گروهِ هم‌پایه نصف نمی‌شود
                 ("پیش‌نویسِ کامل در سه دقیقه", 3, "پیش‌نویسِ کامل", "در سه دقیقه")]
        for text, n, head, rest in cases:
            with self.subTest(text=text, n=n):
                self.assertEqual(phrases.clip(text, n), (head, rest))
        self.assertEqual(phrases.clip("", 3), ("", ""))
        self.assertEqual(phrases.clip("یک", 3)[0], "")             # فقط واژهٔ ناتمام ⇒ چیزی برنمی‌گردد
        self.assertEqual(phrases.clip("سلام دنیا", 1)[0], "سلام")

    def test_dangling_words(self):
        for w in ("برای", "و", "یا", "را", "که", "با", "از", "در", "به", "بدونِ", "یک", "این", "برنامهٔ", "کاملِ", "دربارهٔ", "+"):
            self.assertTrue(phrases.dangling(w), w)
        for w in ("ورزشی", "خانه", "پا", "مبتدی‌ها", "۵۰", "چغر"):
            self.assertFalse(phrases.dangling(w), w)

    def test_split_paren(self):
        self.assertEqual(phrases.split_paren("برنامه‌ساز (بدونِ هوش مصنوعی)"), ("برنامه‌ساز", "بدونِ هوش مصنوعی"))
        self.assertEqual(phrases.split_paren("بسته «عادی» — ۵۰ توکن"), ("بسته عادی", "۵۰ توکن"))
        self.assertEqual(phrases.split_paren("الف (ب"), ("الف ب", ""))

    def test_first_clause(self):
        self.assertEqual(phrases.first_clause("بیش از ۱٬۳۰۰ حرکتِ فارسی با گیف و عکس، و اسکنِ دستگاه‌ها — فعلاً بدونِ هزینه"), "بیش از ۱٬۳۰۰ حرکتِ فارسی با گیف و عکس")
        self.assertEqual(phrases.first_clause(""), "")
        self.assertEqual(phrases.first_clause("a b"), "")                    # غیرفارسی

    def test_lead_number_topics(self):
        t = phrases.parse_topic("7 نکته برای خرید مکمل")
        self.assertEqual((t.lead_n, t.lead_noun, t.lead_prep, t.main), ("۷", "نکته", "برای", "خرید مکمل"))
        t = phrases.parse_topic("۳ روز تا شروع")                       # «روز» واژهٔ فهرست نیست
        self.assertEqual(t.lead_n, "")

    def test_mark_key_prefers_a_content_word(self):
        self.assertEqual(phrases.mark_key("چطور بدون باشگاه"), "چطور بدون *باشگاه*")
        self.assertEqual(phrases.mark_key("ورزش"), "*ورزش*")
        self.assertEqual(phrases.mark_key(""), "")


class ReasonTextTests(SimpleTestCase):
    #: پیامِ واقعیِ «هر دو مسیر جواب ندادند» وقتی سرورِ پردازش خاموش و متیس بسته است (همان که بازبین بریده‌شده دید)
    REAL = ("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — لوکال (Ollama روی سرورِ پردازش): سرورِ پردازش خاموش است؛ متیس (پشتیبان): "
            "سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ این داده به سرویسِ بیرونی (متیس) را نمی‌دهد. ")
    #: نسخهٔ خیلی بلندتر (توضیحِ «سرورِ پردازش آنلاین نیست…» هم داخلش است)
    LONG = ("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — لوکال (Ollama روی سرورِ پردازش): سرورِ پردازشِ «نمونه» آنلاین نیست — روی "
            "سیستمِ گرافیکی START.bat ِ بستهٔ UpMarket-Processing را اجرا کنید؛ متیس (پشتیبان): سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ "
            "این داده به سرویسِ بیرونی (متیس) را نمی‌دهد. و دوباره امتحان کنید بعد از آنکه سرورِ پردازش روشن شد و هوش مصنوعی برگشت.")

    @staticmethod
    def tokens(text: str) -> set[str]:
        return {t.strip("؛.،:—-()«»") for t in text.replace("—", " ").split()}

    def test_the_real_router_message_fits_without_any_cut(self):
        out = hooks.friendly_reason(self.REAL)
        self.assertLessEqual(len(out), 170)
        self.assertFalse(out.endswith("…"), out)
        self.assertIn("سرورِ پردازش خاموش است", out)
        self.assertTrue(out.endswith("را نمی‌دهد."), out)                       # قبلاً: «…(متیس) را نمی‌ده…»
        self.assertNotIn("نمی‌ده…", out)

    def test_long_router_message_is_never_cut_mid_word(self):
        for limit in (40, 60, 90, 120, 170, 240):
            cut = hooks.fit_text(self.LONG, limit)
            self.assertLessEqual(len(cut), limit, (limit, cut))
            core = cut.rstrip("…").rstrip()
            self.assertTrue(core)
            self.assertTrue(self.tokens(core) <= self.tokens(self.LONG), (limit, cut, self.tokens(core) - self.tokens(self.LONG)))
            if cut.endswith("…"):
                self.assertFalse(phrases.dangling(core.split()[-1]), (limit, cut))
        out = hooks.friendly_reason(self.LONG)
        self.assertLessEqual(len(out), 170)
        self.assertTrue(self.tokens(out.rstrip("…")) <= self.tokens(hooks.friendly_reason(self.LONG, 999)))

    def test_fit_text_prefers_whole_clauses(self):
        self.assertEqual(hooks.fit_text("کوتاه است", 50), "کوتاه است")
        self.assertEqual(hooks.fit_text("اولی کامل است؛ دومی هم کامل است؛ سومی خیلی خیلی بلند است و جا نمی‌شود", 36), "اولی کامل است؛ دومی هم کامل است")
        out = hooks.fit_text("الف " * 100, 50)
        self.assertTrue(out.endswith("…") and len(out) <= 50)

    def test_reason_from_router_failures(self):
        class F_:
            def __init__(self, kind, message):
                self.kind, self.message = kind, message

        class AllFailed(Exception):
            failures = {"local": F_("offline", "x"), "metis": F_("policy", "سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ این داده به سرویسِ بیرونی (متیس) را نمی‌دهد. ...")}

        out = hooks.reason_from_exception(AllFailed("long " * 80))
        self.assertLessEqual(len(out), 240)
        self.assertIn("سرورِ پردازش", out)
        self.assertIn("متیس", out)
        self.assertNotIn("…", out)
        self.assertEqual(hooks.reason_from_exception(RuntimeError("boom")), "boom")
        self.assertEqual(hooks.reason_from_exception(None, fallback_text="اعتبار credit تمام شد"), "اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)")

    def test_old_contract_still_holds(self):
        self.assertEqual(hooks.friendly_reason(None), "")
        self.assertLessEqual(len(hooks.friendly_reason("الف " * 200)), 170)
        self.assertNotIn("{", hooks.friendly_reason('سرورِ پردازش پاسخ نداد {"detail": {"a": 1}}   دوباره امتحان کنید'))


# ───────────────────────────── API

class NoSubjectApiTests(TestCase):
    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        from django.contrib.auth import get_user_model
        from django.test import override_settings
        from rest_framework.test import APIClient

        from apps.stores.models import Store

        self.media = Path(tempfile.mkdtemp(prefix="nmthumbs-fix-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmthumbs-fix-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self._rm = shutil.rmtree
        self.owner = get_user_model().objects.create_user("thumbs-fix-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", target_audience="مربی‌های باشگاه", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/thumbnails"

    def tearDown(self):
        self.override.disable()
        self._rm(self.media, ignore_errors=True)
        self._rm(self.data, ignore_errors=True)

    def upload(self, img, name="p.png") -> int:
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        buf.name = name
        r = self.api.post(f"{self.base}/library/upload/", {"files": [buf]}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["assets"][0]["id"]

    def test_final_render_without_a_photo_warns_and_has_no_placeholder(self):
        spec_ = {"format": "ig_square", "style": "product_hero",
                 "content": {"kicker": "پیشنهاد", "title": "*برنامهٔ* ورزشی + غذایی را ببینید", "subtitle": "یک راهنمای کوتاه", "cta": "دیدن و سفارش"}}
        r = self.api.post(f"{self.base}/render/", {"spec": spec_, "variants": 1}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        item = r.json()["items"][0]
        self.assertEqual(item["state"], "READY")
        self.assertIn(R.NO_SUBJECT_WARNING, item["warnings"])
        full = self.api.get(f"{self.base}/items/{item['id']}/").json()
        layer_names = " ".join(x["name"] for x in full.get("layers", []))
        for bad in ("انفجارِ جایگزین", "جرقه"):
            self.assertNotIn(bad, layer_names)

    def test_preview_warns_too(self):
        r = self.api.post(f"{self.base}/preview/", {"spec": {"format": "youtube", "style": "face_text", "content": {"title": "*سلام* دنیا"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(R.NO_SUBJECT_WARNING, r.json()["warnings"])

    def test_a_blank_gradient_product_photo_is_ignored_with_a_clear_note(self):
        grad = P.gradient((700, 700), [(0.0, "#0ea5e9"), (1.0, "#e0f2fe")], 60).convert("RGB")
        aid = self.upload(grad)
        r = self.api.post(f"{self.base}/preview/", {"spec": {"format": "ig_square", "style": "product_hero", "subject": {"asset": aid},
                                                             "content": {"title": "*محصول* من"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        from . import cutout

        self.assertIn(cutout.BLANK_NOTE, body["warnings"])
        self.assertFalse(any(x["kind"] == "subject" or x["kind"] == "photo" for x in body["layers"]))
        # عکسِ واقعی سرِ جایش می‌ماند
        real = self.upload(fixtures.person())
        r = self.api.post(f"{self.base}/preview/", {"spec": {"format": "ig_square", "style": "product_hero", "subject": {"asset": real},
                                                             "content": {"title": "*محصول* من"}}}, format="json")
        self.assertNotIn(cutout.BLANK_NOTE, r.json()["warnings"])
        self.assertTrue(any(x["kind"] == "subject" for x in r.json()["layers"]))

    def test_ideas_endpoint_titles_are_sound_for_the_reported_topic(self):
        r = self.api.post(f"{self.base}/ideas/", {"topic": "برنامهٔ ورزشی شخصی برای مبتدی‌ها در خانه", "format": "youtube", "ai": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        for i in r.json()["ideas"]:
            self.assertFalse(typo.plain(i["title"]).endswith("برای"), i["title"])
            self.assertTrue(typo.plain(i["subtitle"]), i)

    def test_big_number_is_persian_through_the_api(self):
        r = self.api.post(f"{self.base}/preview/", {"spec": {"format": "ig_portrait", "style": "number_list",
                                                             "content": {"number": "7", "title": "7 اشتباه رایج در تمرین پا"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        num = next(t for t in r.json()["texts"] if t["name"] == "عدد")
        self.assertEqual(num["text"], "۷")


class AiFieldLimitTests(SimpleTestCase):
    def test_long_ai_text_is_cut_on_a_word_boundary(self):
        from . import ideation

        sub = "این یک زیرعنوانِ بسیار بسیار بلند است که باید روی مرزِ واژه بریده شود و نباید وسطِ کلمه تمام شود"
        out = ideation.clean_ai_ideas({"ideas": [{"title": "*ورزش* در خانه", "subtitle": sub, "style": "face_text"}]}, fmt="youtube", source_text="")
        s = out[0]["subtitle"]
        self.assertTrue(0 < len(s) <= 60, s)
        self.assertTrue(sub.startswith(s), s)
        self.assertEqual(sub[len(s)], " ", s)
        self.assertFalse(phrases.dangling(s.split()[-1]), s)

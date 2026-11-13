"""موتورِ ساختِ تامنیل (بدونِ دیتابیس): هر سبک × هر قالب با متنِ فارسی، حاشیهٔ امن، متنِ بلند، بدونِ عکس، با عکس، با پس‌زمینه."""
import numpy as np
from django.test import SimpleTestCase
from PIL import Image, ImageChops

from . import fixtures, hooks, palette, typo
from . import formats as F
from . import render as R
from .styles import STYLES

SCALE = 0.34          # پیش‌نمایشِ کوچک: ماتریسِ ۹۶ تایی سریع بماند
CONTENT = {"title": "*۷* اشتباهِ ورزشکارهای تازه‌کار", "subtitle": "قبل از شروع ببینید", "kicker": "جدید", "badge": "ویژه", "number": "۷",
           "tagline": "داستانی که باید دید", "credits": "کارگردان: نام نمونه | تهیه‌کننده: نام نمونه", "cta": "همین حالا ببینید",
           "label_a": "ورزشکار الف", "label_b": "ورزشکار ب"}


def spec(style, fmt, **over):
    raw = {"format": fmt, "style": style, "content": dict(CONTENT)}
    raw.update(over)
    return R.clean_spec(raw, STYLES)


def inputs(subject=True, second=True, bg=False, logo=False):
    inp = R.Inputs(brand_colors=["#126F85", "#163F75"], store_name="چغر")
    if subject:
        inp.subject, inp.subject_is_cutout = fixtures.person(), True
    if second:
        inp.subject2, inp.subject2_is_cutout = fixtures.person(skin="#d9a577", shirt="#dc2626", mood="sad"), True
    if bg:
        inp.background = fixtures.scene()
    if logo:
        inp.logo = Image.new("RGBA", (300, 120), (20, 120, 140, 255))
    return inp


def stddev(img):
    return float(np.asarray(img.convert("L"), dtype=np.float32).std())


def overlap_frac(box, rect):
    ix = max(0, min(box[2], rect[2]) - max(box[0], rect[0]))
    iy = max(0, min(box[3], rect[3]) - max(box[1], rect[1]))
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    return ix * iy / area


class MatrixTests(SimpleTestCase):
    """هر سبک روی هر قالب: اندازهٔ دقیق، خالی نبودن، رسمِ واقعیِ متنِ فارسی، رعایتِ ناحیهٔ پرهیز."""

    def test_raqm_is_available(self):
        self.assertTrue(typo.HAS_RAQM, "libraqm باید باشد تا حروفِ فارسی بچسبند")

    def test_every_style_on_every_format(self):
        inp = inputs()
        for style in STYLES:
            for fmt in F.FORMATS:
                with self.subTest(style=style, format=fmt):
                    sp = spec(style, fmt)
                    res = R.render(sp, inp, scale=SCALE)
                    self.assertEqual(res.image.size, F.scaled(F.get(fmt), SCALE))
                    self.assertEqual(res.size, res.image.size)
                    self.assertGreater(stddev(res.image), 18, "تصویرِ تقریباً خالی")
                    titles = [t for t in res.texts if t["text"] and t["name"].startswith("عنوان")]
                    self.assertTrue(titles, "عنوان کشیده نشد")
                    W, H = res.size
                    for t in res.texts:
                        x0, y0, x1, y1 = t["bbox"]
                        self.assertTrue(0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H, ("متن بیرون از بوم", t))
                    kinds = {layer["kind"] for layer in res.layers}
                    self.assertIn("background", kinds)
                    self.assertIn("text", kinds)

    def test_text_is_really_drawn_where_the_report_says(self):
        """با و بدونِ عنوان رندر می‌گیریم؛ داخلِ کادرِ گزارش‌شده باید پیکسل‌ها فرق کنند."""
        inp = inputs()
        for style in STYLES:
            for fmt in ("youtube", "story", "poster"):
                with self.subTest(style=style, format=fmt):
                    with_t = R.render(spec(style, fmt), inp, scale=SCALE)
                    c2 = dict(CONTENT, title="")
                    bare = R.render(R.clean_spec({"format": fmt, "style": style, "content": c2}, STYLES), inp, scale=SCALE)
                    t = next(t for t in with_t.texts if t["name"].startswith("عنوان"))
                    x0, y0, x1, y1 = t["bbox"]
                    a = with_t.image.crop((x0, y0, x1, y1))
                    b = bare.image.crop((x0, y0, x1, y1))
                    diff = np.asarray(ImageChops.difference(a, b).convert("L"), dtype=np.float32)
                    self.assertGreater(float((diff > 40).mean()), 0.04, "جای متن فرقی نکرد")

    def test_title_respects_platform_avoid_zones(self):
        inp = inputs()
        for style in STYLES:
            for fmt, f in F.FORMATS.items():
                if not f.avoid:
                    continue
                with self.subTest(style=style, format=fmt):
                    res = R.render(spec(style, fmt), inp, scale=SCALE)
                    avoid = F.avoid_rects(f, res.size)
                    for t in res.texts:
                        if not t["name"].startswith("عنوان"):
                            continue
                        for a in avoid:
                            self.assertLess(overlap_frac(t["bbox"], a), 0.12, (t["name"], t["bbox"], a))

    def test_all_text_stays_inside_safe_rect_for_title(self):
        inp = inputs()
        for style in STYLES:
            for fmt, f in F.FORMATS.items():
                res = R.render(spec(style, fmt), inp, scale=SCALE)
                sx0, sy0, sx1, sy1 = F.safe_rect(f, res.size)
                pad = res.size[0] * 0.05                      # جلوه‌ها (سایه/درخشش) کمی بیرون می‌زنند
                for t in res.texts:
                    if t["name"].startswith("عنوان"):
                        b = t["bbox"]
                        with self.subTest(style=style, format=fmt):
                            self.assertGreaterEqual(b[0], sx0 - pad)
                            self.assertLessEqual(b[2], sx1 + pad)
                            self.assertGreaterEqual(b[1], sy0 - pad)
                            self.assertLessEqual(b[3], sy1 + pad)


class VariantsOfInputTests(SimpleTestCase):
    def test_no_images_at_all_is_never_empty(self):
        inp = R.Inputs(brand_colors=[])
        for style in STYLES:
            with self.subTest(style=style):
                res = R.render(spec(style, "ig_portrait"), inp, scale=SCALE)
                self.assertGreater(stddev(res.image), 18)
                self.assertTrue(any(t["name"].startswith("عنوان") for t in res.texts))

    def test_photo_subject_instead_of_cutout(self):
        inp = R.Inputs(subject=fixtures.scene(), subject_is_cutout=False, subject2=fixtures.scene(seed=2), subject2_is_cutout=False)
        for style in STYLES:
            with self.subTest(style=style):
                res = R.render(spec(style, "youtube"), inp, scale=SCALE)
                self.assertGreater(stddev(res.image), 18)

    def test_photo_background_and_logo(self):
        inp = inputs(bg=True, logo=True)
        for style in STYLES:
            with self.subTest(style=style):
                sp = spec(style, "ig_square", background={"kind": "photo"})
                res = R.render(sp, inp, scale=SCALE)
                self.assertTrue(any(layer["kind"] == "logo" for layer in res.layers), "لوگو نیامد")
                self.assertGreater(stddev(res.image), 18)

    def test_photo_background_without_image_falls_back(self):
        res = R.render(spec("neon", "youtube", background={"kind": "photo"}), inputs(), scale=SCALE)
        self.assertGreater(stddev(res.image), 18)

    def test_long_text_and_english_mixed(self):
        long_title = "این یک عنوانِ بسیار بسیار بلند است که باید خودش را در جعبه جا بدهد بدونِ بیرون‌زدن از بوم و بدونِ همپوشانی"
        for style in STYLES:
            with self.subTest(style=style):
                sp = spec(style, "youtube", content={"title": long_title, "subtitle": long_title, "kicker": long_title, "badge": long_title})
                res = R.render(sp, inputs(), scale=SCALE)
                for t in res.texts:
                    b = t["bbox"]
                    self.assertTrue(0 <= b[0] and b[2] <= res.size[0] and 0 <= b[1] and b[3] <= res.size[1], t)
        res = R.render(spec("face_text", "youtube", content={"title": "iPhone ۱۶ را *ببینید* 2026"}), inputs(), scale=SCALE)
        self.assertTrue(res.texts)

    def test_scale_changes_size_not_layout(self):
        sp = spec("face_text", "youtube")
        a = R.render(sp, inputs(), scale=0.3)
        b = R.render(sp, inputs(), scale=0.6)
        self.assertEqual(b.size, (F.scaled(F.get("youtube"), 0.6)))
        ta = next(t for t in a.texts if t["name"] == "عنوان")["bbox"]
        tb = next(t for t in b.texts if t["name"] == "عنوان")["bbox"]
        # مرکزِ نسبیِ متن در هر دو مقیاس نزدیک است
        ca = ((ta[0] + ta[2]) / 2 / a.size[0], (ta[1] + ta[3]) / 2 / a.size[1])
        cb = ((tb[0] + tb[2]) / 2 / b.size[0], (tb[1] + tb[3]) / 2 / b.size[1])
        self.assertAlmostEqual(ca[0], cb[0], delta=0.03)
        self.assertAlmostEqual(ca[1], cb[1], delta=0.03)

    def test_layers_kept_for_layered_export(self):
        res = R.render(spec("face_text", "youtube"), inputs(), scale=SCALE, keep_layers=True)
        self.assertGreaterEqual(len(res.kept), 5)
        self.assertEqual(len(res.kept), len(res.layers))

    def test_arrow_accent_is_a_layer_and_can_be_turned_off(self):
        for style in ("face_text", "question_hook", "sticker_outline"):
            for fmt in ("youtube", "ig_portrait", "story"):
                with self.subTest(style=style, format=fmt):
                    on = R.render(spec(style, fmt), inputs(), scale=SCALE)
                    self.assertIn("فلشِ اشاره", [layer["name"] for layer in on.layers])
                    off = R.render(spec(style, fmt, accents={"arrow": False}), inputs(), scale=SCALE)
                    self.assertNotIn("فلشِ اشاره", [layer["name"] for layer in off.layers])
                    ab = on.layers[[layer["name"] for layer in on.layers].index("فلشِ اشاره")]["bbox"]
                    self.assertTrue(0 <= ab[0] < ab[2] <= on.size[0] and 0 <= ab[1] < ab[3] <= on.size[1], ab)
        # بدونِ سوژه فلشی نیست
        res = R.render(spec("face_text", "youtube"), R.Inputs(), scale=SCALE)
        self.assertNotIn("فلشِ اشاره", [layer["name"] for layer in res.layers])

    def test_guides_draw_safe_rect(self):
        plain = R.render(spec("face_text", "story"), inputs(), scale=SCALE)
        guided = R.render(spec("face_text", "story", guides=True), inputs(), scale=SCALE)
        self.assertNotEqual(plain.image.tobytes(), guided.image.tobytes())

    def test_determinism(self):
        sp = spec("sticker_outline", "story", seed=5)
        a = R.render(sp, inputs(), scale=SCALE).image.tobytes()
        b = R.render(sp, inputs(), scale=SCALE).image.tobytes()
        self.assertEqual(a, b)

    def test_ab_variations_differ(self):
        base = spec("face_text", "youtube")
        other = spec("face_text", "youtube", colors={"variation": 1})
        a = R.render(base, inputs(), scale=SCALE).image
        b = R.render(other, inputs(), scale=SCALE).image
        self.assertGreater(float(np.abs(np.asarray(a, dtype=int) - np.asarray(b, dtype=int)).mean()), 5)


class SpecTests(SimpleTestCase):
    def test_clean_spec_rejects_unknown_and_trims(self):
        with self.assertRaises(R.SpecError):
            R.clean_spec({"format": "nope", "style": "neon"}, STYLES)
        with self.assertRaises(R.SpecError):
            R.clean_spec({"format": "youtube", "style": "nope"}, STYLES)
        sp = R.clean_spec({"format": "story", "style": "neon", "content": {"title": "x" * 500, "evil": "y"}, "colors": {"primary": "red", "accent": "#FFAA00"},
                           "subject": {"asset": "7", "scale": 9}, "background": {"kind": "weird"}, "font": "comic"}, STYLES)
        self.assertEqual(len(sp["content"]["title"]), R.MAX_TITLE)
        self.assertNotIn("evil", sp["content"])
        self.assertEqual(sp["colors"]["primary"], "")
        self.assertEqual(sp["colors"]["accent"], "#ffaa00")
        self.assertEqual(sp["subject"]["asset"], 7)
        self.assertEqual(sp["subject"]["scale"], 1.4)
        self.assertEqual(sp["background"]["kind"], "auto")
        self.assertEqual(sp["font"], typo.AUTO_FONT)

    def test_formats_have_documented_sizes(self):
        self.assertEqual(F.get("youtube").size, (1280, 720))
        self.assertEqual(F.get("ig_portrait").size, (1080, 1350))
        self.assertEqual(F.get("ig_square").size, (1080, 1080))
        self.assertEqual(F.get("story").size, (1080, 1920))
        self.assertEqual(F.get("pinterest").size, (1000, 1500))
        self.assertEqual(F.get("poster").size, (1200, 1800))
        self.assertEqual(F.get("telegram").size, (1280, 720))
        self.assertEqual(F.get("aparat").size, (1280, 720))
        for f in F.FORMATS.values():
            self.assertTrue(f.margin[0] > 0)

    def test_every_style_declares_formats_and_fields(self):
        for k, s in STYLES.items():
            self.assertTrue(any(a == "title" for a, _ in s.fields), k)
            self.assertTrue(set(s.formats) <= set(F.FORMATS), k)
            self.assertIn(s.mood, palette.MOODS, k)
            self.assertIn(s.font, typo.FONT_CHOICES, k)
            self.assertIn(k, hooks.CONCEPTS)
            self.assertIn(k, hooks.BG_PROMPTS)


class TypoTests(SimpleTestCase):
    def test_persian_digits_and_markup(self):
        self.assertEqual(typo.to_fa_digits("۷ روش و 12 نکته، 1,250,000 تومان"), "۷ روش و ۱۲ نکته، ۱٬۲۵۰٬۰۰۰ تومان")
        self.assertEqual(typo.to_fa_digits("iPhone 16"), "iPhone 16")
        self.assertEqual(typo.plain("الف *ب* ج|د"), "الف ب ج د")
        groups, marked = typo.parse_marked("الف *ب ج* د|ه")
        self.assertTrue(marked)
        self.assertEqual(len(groups), 2)
        self.assertEqual([w for w, h in groups[0] if h], ["ب", "ج"])

    def test_text_fits_box(self):
        st = typo.TextStyle(font_key="lalezar", weight=400, stroke_w=0.08, stroke="#000000")
        blk = typo.render_text("این یک عنوانِ نسبتاً بلند برای آزمونِ جاگیری است", 500, 260, st, max_lines=3, min_px=12, max_px=200)
        self.assertIsNotNone(blk)
        self.assertLessEqual(blk.nominal[0], 500 + 2)
        self.assertLessEqual(blk.nominal[1], 260 + 2)
        self.assertGreater(blk.px, 20)
        self.assertIsNone(typo.render_text("   ", 100, 100, st))

    def test_shaping_connects_letters(self):
        """«سلام» با raqm یک رشتهٔ چسبیده است: عرضش از حروفِ جدا (هر حرف تنها) کوتاه‌تر است."""
        from PIL import ImageFont

        path = typo.font_path("vazirmatn", 700)
        f = ImageFont.truetype(path, 100)
        joined = f.getlength("سلام", direction="rtl", language="fa")
        isolated = sum(f.getlength(ch) for ch in "سلام")
        self.assertLess(joined, isolated)


class PaletteTests(SimpleTestCase):
    def test_brand_colors_drive_palette_and_contrast(self):
        for mood in palette.MOODS:
            p = palette.build(mood, ["#126F85", "#163F75"])
            self.assertGreaterEqual(palette.colorx.contrast(p.text, p.bg1), 3.0, mood)
            self.assertGreaterEqual(palette.colorx.contrast(p.accent, p.bg1), 2.0, mood)
        a, b = palette.build("vivid", ["#126F85"], variation=0), palette.build("vivid", ["#126F85"], variation=1)
        self.assertNotEqual((a.bg1, a.bg2), (b.bg1, b.bg2))

    def test_store_colors_shapes(self):
        self.assertEqual(palette.brand_colors_of({"primary": "#112233", "secondary": "#445566"}), ["#112233", "#445566"])
        self.assertEqual(palette.brand_colors_of(["#abcdef", "bad"]), ["#abcdef"])
        self.assertEqual(palette.brand_colors_of({}, ["#123456"]), ["#123456"])
        self.assertEqual(palette.brand_colors_of(None), [])


class BriefCoverageTests(SimpleTestCase):
    """هر چیزی که مالک خواسته با نامِ دقیق وجود دارد؛ نبودنِ هر کدام این آزمون را می‌شکند (درسِ «همه‌اش را اضافه نکرده بودی»)."""

    FORMATS = {"youtube": (1280, 720), "aparat": (1280, 720), "telegram": (1280, 720), "ig_portrait": (1080, 1350), "ig_square": (1080, 1080),
               "story": (1080, 1920), "pinterest": (1000, 1500)}
    #: سبک‌های فهرستِ درخواست + سبک‌های افزوده
    STYLES_ASKED = {"face_text": "چهرهٔ بزرگ + متنِ درشت", "split_ba": "قبل/بعد", "number_list": "عدد/لیست", "question_hook": "سؤال/کنجکاوی",
                    "minimal_luxury": "مینیمالِ لوکس", "cinema_poster": "پوسترِ سینمایی با بلوکِ عنوان و سطرِ اعتبار", "pinterest_collage": "کلاژِ پینترستی",
                    "product_hero": "قهرمانِ محصول", "sticker_outline": "استیکرِ حاشیه‌دار", "neon": "نئون"}
    STYLES_EXTRA = ("news_bold", "versus", "magazine_cover", "retro_poster", "quote_card")

    def test_all_asked_formats_exist_with_exact_sizes(self):
        for key, size in self.FORMATS.items():
            with self.subTest(format=key):
                self.assertEqual(F.get(key).size, size)
        w, h = F.get("poster").size
        self.assertEqual(w * 3, h * 2, "پوسترِ فیلم باید ۲:۳ باشد")

    def test_all_asked_styles_exist(self):
        for key in list(self.STYLES_ASKED) + list(self.STYLES_EXTRA):
            with self.subTest(style=key):
                self.assertIn(key, STYLES)
        self.assertGreaterEqual(len(STYLES), 15)

    def test_cinema_poster_has_title_block_and_credits(self):
        """«بلوکِ عنوان + متنِ ریزِ اعتبار» واقعاً کشیده می‌شود."""
        res = R.render(spec("cinema_poster", "poster"), inputs(), scale=SCALE)
        names = {t["name"] for t in res.texts}
        self.assertIn("بلوکِ اعتبار", names)
        self.assertTrue(any(n.startswith("عنوان") for n in names))

    def test_layered_composition_has_every_layer_kind(self):
        """پس‌زمینه، سوژهٔ بریده، عنوان، تزئین و نشان/فلش، لوگو و رنگِ برند در یک طرح."""
        res = R.render(spec("face_text", "youtube"), inputs(bg=True, logo=True), scale=SCALE, keep_layers=True)
        kinds = {layer["kind"] for layer in res.layers}
        for k in ("background", "subject", "text", "badge", "accent"):
            self.assertIn(k, kinds, k)
        self.assertTrue(any("لوگو" in layer["name"] for layer in res.layers))

    def test_new_styles_draw_persian_text_in_every_format(self):
        inp = inputs()
        for style in ("magazine_cover", "retro_poster", "quote_card"):
            for fmt in F.FORMATS:
                with self.subTest(style=style, format=fmt):
                    res = R.render(spec(style, fmt), inp, scale=SCALE)
                    self.assertTrue(any(t["text"] for t in res.texts))
                    self.assertGreater(stddev(res.image), 18)

    def test_cover_lines_stay_clear_of_the_face(self):
        """جلدِ مجله: متنِ تیترِ کاور نباید روی ۶۰٪ِ بالای سوژه (چهره) بیفتد."""
        inp = inputs()
        for fmt in ("ig_portrait", "story", "pinterest", "poster"):
            with self.subTest(format=fmt):
                res = R.render(spec("magazine_cover", fmt), inp, scale=SCALE, keep_layers=True)
                subj = next(layer for layer in res.layers if layer["kind"] == "subject")
                x0, y0, x1, y1 = subj["bbox"]
                face_bottom = y0 + (y1 - y0) * 0.6
                for t in res.texts:
                    if t["name"] in ("تیترِ اصلیِ کاور", "تیترِ دومِ کاور"):
                        self.assertGreaterEqual(t["bbox"][1], face_bottom - res.size[1] * 0.02, (t["name"], t["bbox"], subj["bbox"]))

"""کتابخانهٔ «سبک تصویر»: ۱۱۶ سبک + ۲۴ تم، کامل‌بودنِ داده‌ها، آزمونِ مجوز (نامِ استودیو/برند/هنرمند در هیچ دستوری نیست)، جست‌وجو، نمونه‌های رنگی.

SOURCE: ported from InstAI:tests/test_style_library.py + tests/test_styles.py @ 2f8aa90, adapted for store advertising (NMarketing; Django TestCase instead of pytest).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.test import SimpleTestCase

from . import aliases, compose, fit, library, preview_svg, schema
from .builtin_styles import BUILTIN_STYLES
from .builtin_themes import BUILTIN_THEMES

# نام‌هایی که در داده‌های یک سبک (نام، توضیح، برچسب، دستور) هرگز نباید بیایند: استودیو، فرانچایز، برند، سازندهٔ محتوا، هنرمند
BANNED = ["ghibli", "pixar", "disney", "dreamworks", "cartoon network", "nickelodeon", "lego", "minecraft", "playstation", "ps2", "zackd", "zack d", "dan koe", "kodak",
          "polaroid", "funko", "warhol", "lichtenstein", "hokusai", "mucha", "monet", "simpsons", "adventure time", "wallace", "alegria", "naruto", "dragon ball",
          "one piece", "marvel", "blade runner", "gatsby", "frutiger", "toei", "madhouse", "kyoto animation", "ufotable", "mappa", "jujutsu", "attack on titan",
          "demon slayer", "miyazaki", "shinkai", "dc comics", "ghost in the shell", "akira", "adobe", "photoshop", "premiere", "midjourney", "instagram", "netflix",
          "ikea", "nike", "coca", "google", "microsoft"]

# فهرستِ خودِ مالک، همان‌طور که نوشته: هر کدام باید دست‌کم یک سبک را پیدا کند
OWNER_LIST = ["Pixel Art", "ChalkBoard", "Glow Sketch", "PS2 style", "Comic Art", "Flat Vector", "Dan Koe style", "CGI Motion", "Lego", "ZackD Films style", "Anime",
              "Studio Ghibli", "Disney", "Cartoon Network", "Watercolor", "Cel Shading", "Line Art", "Silhouette", "Claymation", "Stop Motion", "Low Poly", "Voxel Art",
              "Papercraft", "Origami", "Isometric", "Photorealistic CGI", "2.5D Parallax", "Synthwave", "Film Noir", "Cyberpunk", "Steampunk", "Pop Art", "Stained Glass",
              "Graffiti", "Blueprint", "Glitch Art", "Whiteboard", "Kinetic Typography", "Infographic", "Corporate Memphis", "Stickman", "Flat 2D", "3D Claymation",
              "Glassmorphism", "Chrome 22K", "Cineview", "Risograph", "Paper Collage", "Particles", "Neo-brutalism", "Bauhaus", "Memphis", "Vaporwave"]


def rows() -> list[dict]:
    return library.list_entries()


class LibraryDataTests(SimpleTestCase):
    def test_all_116_looks_and_24_themes_exist_in_every_group_and_realism_level(self):
        self.assertEqual(len(library.STYLES), 116)
        self.assertEqual(len(library.THEMES), 24)
        self.assertEqual(len(rows()), 116)
        self.assertEqual(len(library.list_themes()), 24)
        self.assertEqual(set(library.STYLES), set(BUILTIN_STYLES))
        by_group: dict[str, int] = {}
        for s in library.STYLES.values():
            by_group[s["group"]] = by_group.get(s["group"], 0) + 1
        self.assertEqual(set(by_group), set(schema.GROUPS), "هر گروه سبک دارد و هر سبک گروهِ شناخته‌شده")
        self.assertGreaterEqual(min(by_group.values()), 8)
        self.assertEqual({s["realism"] for s in library.STYLES.values()}, set(schema.REALISM))
        self.assertEqual(sum(g["count"] for g in library.groups()), 116)
        self.assertEqual(sum(g["count"] for g in library.realism_levels()), 116)

    def test_every_look_is_complete_and_has_valid_generation_hints(self):
        for key, s in library.STYLES.items():
            self.assertTrue(s["name_fa"] and s["name_en"] and s["description_fa"] and s["description_en"], key)
            self.assertTrue(s["image_positive"] and s["image_negative"] and s["video_positive"] and s["video_negative"] and s["sample_prompt"], key)
            self.assertTrue(re.search(r"[؀-ۿ]", s["name_fa"]), f"{key}: نامِ فارسی فارسی نیست")
            self.assertTrue(re.search(r"[؀-ۿ]", s["description_fa"]), key)
            self.assertIn(s["group"], schema.GROUPS, key)
            self.assertTrue(s["suitability"] and set(s["suitability"]) <= set(schema.SUITABILITY), key)
            self.assertIn(s["theme_key"], BUILTIN_THEMES, key)
            self.assertGreaterEqual(len(s["palette"]), 5, key)
            self.assertTrue(all(re.match(r"^#[0-9A-F]{6}$", c) for c in s["palette"]), key)
            g = s["gen"]
            self.assertIn(g["model"], schema.BASE_MODELS, key)
            self.assertNotEqual(g["model"], "sdxl_anime", "نامِ قدیمیِ InstAI باید به مدلِ واقعیِ NM نگاشت شود")
            self.assertIn(g["aspect"], schema.ASPECTS, key)
            self.assertTrue(4 <= g["steps"] <= 60 and 0 <= g["cfg"] <= 30 and g["sampler"], key)
            self.assertIn(s["motif"], preview_svg.MOTIFS, f"{key}: نمونهٔ رنگی برای الگوی {s['motif']!r} نقاشی ندارد")
            for gone in ("techniques", "fps_feel"):
                self.assertNotIn(gone, s, f"{key}: فیلدِ سریال‌محورِ InstAI ({gone}) باید حذف شود")
            self.assertTrue(set(s["ad_fit"]) <= set(schema.AD_FITS) and s["ad_fit"], key)
            self.assertIsInstance(s["product_safe"], bool)
        for key, t in library.THEMES.items():
            self.assertTrue(t["name_fa"] and t["name_en"] and t["description_fa"] and t["lighting"] and t["mood"] and t["prompt_fragment"], key)
            self.assertEqual(len(t["palette"]), 6, key)
            self.assertTrue(all(re.match(r"^#[0-9A-F]{6}$", c) for c in t["palette"]), key)
            self.assertNotIn("typography", t, f"{key}: تایپوگرافیِ زیرنویسِ سریال در NM جایی ندارد")
            self.assertTrue(re.search(r"[؀-ۿ]", t["name_fa"]), key)

    def test_no_studio_brand_or_creator_name_is_in_the_data_or_any_composed_prompt(self):
        blob = json.dumps([library.STYLES, library.THEMES], ensure_ascii=False).lower()
        self.assertEqual([w for w in BANNED if w in blob], [])
        # و در هیچ دستورِ ساخته‌شده‌ای، برای هیچ نوعِ تبلیغ و هیچ تمی
        for key in library.STYLES:
            for kind in compose.KINDS:
                for theme in ("", library.STYLES[key]["theme_key"]):
                    try:
                        c = compose.compose(key, kind, theme_key=theme)
                    except compose.LookError:
                        self.assertIn(kind, compose.PRODUCT_KINDS)
                        continue
                    text = " ".join(str(c[k]) for k in ("positive", "negative", "name_en", "name_fa")).lower()
                    self.assertEqual([w for w in BANNED if w in text], [], (key, kind))
        # لحنِ «بلوک Look» برای کارگردانِ هوش مصنوعی هم
        for key in list(library.STYLES)[:30]:
            c = compose.compose(key, "POSTER")
            self.assertEqual([w for w in BANNED if w in compose.look_block(c).lower()], [], key)

    def test_aliases_and_known_as_are_search_and_display_only_and_never_reach_a_prompt(self):
        self.assertEqual([k for k in aliases.ALIASES if k not in library.STYLES], [])
        self.assertEqual([k for k in aliases.KNOWN_AS if k not in library.STYLES], [])
        blob_data = json.dumps(library.STYLES, ensure_ascii=False).lower()
        for key, caption in aliases.KNOWN_AS.items():
            for w in BANNED:
                if w in caption.lower():
                    self.assertNotIn(w, blob_data, key)
            row = next(r for r in rows() if r["key"] == key)
            self.assertEqual(row["known_as"], caption)
            for kind in ("POSTER", "NEW_IMAGE", "THUMB_BG", "SAMPLE"):
                text = json.dumps(compose.compose(key, kind), ensure_ascii=False).lower()
                self.assertEqual([w for w in BANNED if w in caption.lower() and w in text], [], (key, kind))
        c = compose.compose("toy_brick_3d", "POSTER")
        self.assertNotIn("lego", json.dumps(c, ensure_ascii=False).lower())
        for row in rows():
            self.assertEqual(row["search_terms"], aliases.terms_for(row["key"]))

    def test_reserved_url_words_are_not_look_keys(self):
        self.assertFalse({"themes", "compose", "check", "suggest", "samples"} & set(library.STYLES))

    def test_the_owners_whole_list_is_searchable_by_the_names_he_uses(self):
        lib = rows()
        for name in OWNER_LIST:
            self.assertTrue(library.filter_entries(lib, q=name), f"nothing found for {name!r}")
        expect = {"ghibli": "painterly_pastoral", "lego": "toy_brick_3d", "ps2": "early_console_3d", "dan koe": "minimal_bw_essay", "zackd": "fast_3d_explainer",
                  "disney": "fairytale_feature_2d", "cartoon network": "bold_angular_tv_toon", "pixar": "cg_family_3d", "chrome 22k": "chrome_metal_type"}
        for q, key in expect.items():
            self.assertIn(key, [r["key"] for r in library.filter_entries(lib, q=q)], q)
        self.assertIn("painterly_pastoral", [r["key"] for r in library.filter_entries(lib, q="ژیبلی")])
        self.assertIn("early_console_3d", [r["key"] for r in library.filter_entries(lib, q="پی اس ۲")])
        self.assertEqual(library.filter_entries(lib, q="zzzz-not-a-style"), [])

    def test_a_caption_or_a_pasted_full_name_with_brackets_finds_its_style(self):
        lib = rows()
        for key, caption in aliases.KNOWN_AS.items():
            for q in (caption, caption.lower(), caption.replace("-", " ")):
                self.assertIn(key, [r["key"] for r in library.filter_entries(lib, q=q)], (key, q))
        self.assertEqual([r["key"] for r in library.filter_entries(lib, q="Lego-like bricks")], ["toy_brick_3d"])
        for q in ("Chrome 22K (chrome metallic type)", "«Chrome 22K»", "(Chrome 22K)", "Chrome 22K, chrome", "\"Lego-like bricks\"", "(Pixel Art)", "«Glassmorphism»"):
            self.assertTrue(library.filter_entries(lib, q=q), q)
        self.assertEqual(library.filter_entries(lib, q="(zzzz not a style)"), [])

    def test_persian_and_arabic_variants_and_digit_alphabets_fold_together(self):
        self.assertEqual(library.fold("كيف ۱۲٣"), library.fold("کیف 123"))
        self.assertEqual(library.fold("نیم‌فاصله-و"), "نیم فاصله و")
        lib = rows()
        a = [r["key"] for r in library.filter_entries(lib, q="پیکسل")]
        b = [r["key"] for r in library.filter_entries(lib, q="پيكسل")]
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_the_browser_side_search_ignores_the_same_punctuation_as_the_server(self):
        ts = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "looks" / "lookSearch.ts"
        text = ts.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if ln.startswith("const PUNCTUATION"))
        for ch in "()[]{}<>«»\"“”‘’,;:!?،؛؟/\\|":
            self.assertTrue(ch in line or "\\u%04x" % ord(ch) in line or ("\\" + ch) in line, f"{ch!r} در سرور نادیده گرفته می‌شود ولی در مرورگر نه")
        self.assertIn("FILLER", text)

    def test_filters_by_group_realism_ad_fit_and_product_safe(self):
        lib = rows()
        r = library.filter_entries(lib, group="craft")
        self.assertTrue(r and all(x["group"] == "craft" for x in r))
        r = library.filter_entries(lib, realism="realistic")
        self.assertTrue(r and all(x["realism"] == "realistic" for x in r))
        r = library.filter_entries(lib, product_safe=True)
        self.assertEqual({x["key"] for x in r}, {k for k, v in library.STYLES.items() if v["product_safe"]})
        self.assertTrue(library.filter_entries(lib, ad_fit="poster") and library.filter_entries(lib, ad_fit="story") and library.filter_entries(lib, ad_fit="reel"))
        both = library.filter_entries(lib, q="lego", group=library.STYLES["toy_brick_3d"]["group"])
        self.assertEqual([x["key"] for x in both], ["toy_brick_3d"])
        self.assertEqual(library.filter_entries(lib, q="lego", group="motion_type"), [], "فیلترها با هم «و» می‌شوند")
        order = [g["key"] for g in library.groups()]
        seen = [x["group"] for x in lib]
        self.assertEqual(seen, sorted(seen, key=order.index), "فهرست به ترتیبِ گروه‌هاست")

    def test_every_look_has_a_valid_deterministic_swatch(self):
        for key, s in library.STYLES.items():
            svg = preview_svg.render({**s, "key": key})
            root = ET.fromstring(svg)
            self.assertTrue(root.tag.endswith("svg") and len(svg) < 120_000, key)
        s = library.STYLES["cg_family_3d"]
        self.assertEqual(preview_svg.render({**s, "key": "cg_family_3d"}), preview_svg.render({**s, "key": "cg_family_3d"}))
        ids = []
        for key in ("cg_family_3d", "claymation_stopmotion"):
            ids += re.findall(r'id="([a-z0-9]+)"', preview_svg.render({**library.STYLES[key], "key": key}))
        self.assertEqual(len(ids), len(set(ids)), "شناسه‌های گرادیان در یک صفحه با هم برخورد نکند")
        self.assertTrue(preview_svg.render({"key": "x"}).startswith("<svg"))

    def test_normalisers_clamp_and_drop_unknown_and_series_only_fields(self):
        st = schema.normalize_style({"name_en": "x", "realism": "nonsense", "palette": ["#fff", "#112233", "red"], "fps_feel": "999", "techniques": ["wan_i2v", "bogus"], "evil": 1,
                                     "gen": {"steps": 999, "model": "sdxl_anime", "aspect": "7:3", "cfg": "x"}, "ad_fit": ["poster", "nope"], "motif": "Pixel!!"})
        self.assertEqual(st["realism"], "anime")
        self.assertEqual(st["palette"], ["#112233"])
        self.assertTrue("fps_feel" not in st and "techniques" not in st and "evil" not in st)
        self.assertEqual(st["gen"]["steps"], 60)
        self.assertEqual(st["gen"]["model"], "sdxl", "sdxl_anime ⇒ sdxl")
        self.assertEqual(st["gen"]["aspect"], "9:16")
        self.assertEqual(st["ad_fit"], ["poster"])
        self.assertEqual(st["motif"], "pixel")
        th = schema.normalize_theme({"name_en": "t", "typography": {"title_weight": "huge"}, "palette": ["#010203", "zzz"]})
        self.assertNotIn("typography", th)
        self.assertEqual(th["palette"], ["#010203"])

    def test_join_dedupes_fragments(self):
        self.assertEqual(library.join("a, b", "B, c", ""), "a, b, c")


class FitTests(SimpleTestCase):
    def test_business_table_only_names_real_looks_with_a_reason(self):
        for gkey, title, words, picks in fit.BUSINESS:
            self.assertTrue(title and words and 3 <= len(picks) <= 5, gkey)
            for look_key, why in picks:
                self.assertIn(look_key, library.STYLES, f"{gkey}: {look_key}")
                self.assertTrue(why.strip(), (gkey, look_key))
                self.assertFalse(re.search(r"\d+\s*(٪|%|درصد)", why), f"{gkey}/{look_key}: دلیل نباید آمار بسازد")
        for look_key, why in fit.GENERIC[1]:
            self.assertIn(look_key, library.STYLES)
        self.assertEqual([k for k in fit.AD_FIT_OVERRIDES if k not in library.STYLES], [])

    def test_product_safe_looks_are_photographic_and_have_scene_fragments(self):
        safe = [k for k, v in library.STYLES.items() if v["product_safe"]]
        self.assertGreaterEqual(len(safe), 6)
        for key in safe:
            s = library.STYLES[key]
            self.assertLessEqual(schema.REALISM_ORDER.index(s["realism"]), schema.REALISM_ORDER.index("semi_realistic"), key)
            self.assertGreaterEqual(len(fit.scene_fragments(s)), fit.MIN_SCENE_FRAGMENTS, key)
            self.assertNotIn(key, fit.PRODUCT_BLOCK)
            self.assertIn("product_photo", s["ad_fit"])
        for key in ("anime_90s_cel", "claymation_stopmotion", "pixel_art_16bit", "paper_cutout", "flat_vector_motion", "die_cut_sticker", "comic_ink"):
            self.assertFalse(library.STYLES[key]["product_safe"], key)
            self.assertNotIn("product_photo", library.STYLES[key]["ad_fit"])

    def test_scene_fragments_never_contain_subject_restyling_words(self):
        for key, s in library.STYLES.items():
            for frag in fit.scene_fragments(s):
                self.assertIsNone(fit.DENY.search(frag.lower()), (key, frag))

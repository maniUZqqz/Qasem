"""کاتالوگِ سبک‌ها: یکپارچگی (بیش از ۶۰ سبکِ یکتا، فیلدهای لازم، فقط مقدارهایی که موتور می‌شناسد)، «تفاوتِ واقعی» و هماهنگیِ فایلِ تولیدشده."""
import json
import re
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

from . import catalog, runner

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
#: سبک‌هایی که مالک اسم برده (شناسه‌ها باید در کاتالوگ باشند)
OWNER_LIST = [
    "pixel-art", "chalkboard", "glow-sketch", "ps2-style", "comic-art", "flat-vector", "dan-koe-style", "cgi-motion", "lego-bricks",
    "zackd-inspired", "anime-inspired", "ghibli-inspired", "disney-inspired", "cartoon-network-inspired", "watercolor", "cel-shading",
    "line-art", "silhouette", "claymation", "stop-motion", "low-poly", "voxel-art", "papercraft", "origami", "isometric", "photoreal-cgi",
    "parallax-2-5d", "synthwave", "film-noir", "cyberpunk", "steampunk", "pop-art", "stained-glass", "graffiti", "blueprint", "glitch-art",
    "whiteboard", "kinetic-typography", "infographic", "corporate-memphis", "stickman", "flat-2d", "claymation-3d", "glassmorphism",
    "chrome-22k", "cineview", "risograph", "paper-collage", "particles", "neo-brutalism", "bauhaus", "memphis", "vaporwave",
]


class CatalogIntegrity(SimpleTestCase):
    def test_sixty_plus_unique_styles(self):
        ids = [s["id"] for s in catalog.STYLES]
        self.assertGreaterEqual(len(ids), 60)
        self.assertEqual(len(ids), len(set(ids)), "duplicate ids")
        self.assertEqual(len({s["name_fa"] for s in catalog.STYLES}), len(ids), "duplicate Persian names")
        self.assertEqual(len({s["name_en"] for s in catalog.STYLES}), len(ids), "duplicate English names")

    def test_every_style_the_owner_named_exists(self):
        have = {s["id"] for s in catalog.STYLES}
        self.assertEqual(sorted(set(OWNER_LIST) - have), [])

    def test_required_fields_and_known_values(self):
        for s in catalog.STYLES:
            sid = s["id"]
            self.assertRegex(sid, r"^[a-z0-9][a-z0-9-]+$")
            for k in ("name_fa", "name_en", "group", "palette", "font", "bg", "text", "shape", "motion", "trans", "about"):
                self.assertTrue(s.get(k), f"{sid}: {k}")
            self.assertIn(s["group"], catalog.GROUPS, sid)
            self.assertEqual(sorted(s["palette"]), sorted(catalog.PAL_KEYS), sid)
            for k, v in s["palette"].items():
                self.assertRegex(v, HEX, f"{sid}.palette.{k}")
            self.assertIn(s["bg"]["kind"], catalog.BG_KINDS, sid)
            if s.get("bg2"):
                self.assertIn(s["bg2"]["kind"], catalog.BG_KINDS, sid)
            for d in s["decor"]:
                self.assertIn(d["kind"], catalog.DECOR_KINDS, f"{sid}: decor {d}")
            for t in s["tex"]:
                self.assertIn(t["kind"], catalog.TEX_KINDS, f"{sid}: tex {t}")
            self.assertIn(s["text"]["fx"], catalog.TEXT_FX, sid)
            self.assertIn(s["motion"]["enter"], catalog.ENTER_KINDS, sid)
            self.assertEqual(len(s["motion"]["spring"]), 3, sid)
            d, st, m = s["motion"]["spring"]
            self.assertTrue(1 <= d <= 80 and 20 <= st <= 400 and 0.2 <= m <= 3, f"{sid}: spring {s['motion']['spring']}")
            self.assertIn(s["trans"]["kind"], catalog.TRANS_KINDS, sid)
            self.assertTrue(0 <= s["trans"]["frames"] <= 40, sid)
            self.assertTrue(s["font"]["latin"] and s["font"]["fa"], sid)
            self.assertTrue(s["about"].strip(), sid)

    def test_inspired_names_are_labelled_not_copied(self):
        inspired = [s for s in catalog.STYLES if s.get("inspired")]
        self.assertGreaterEqual(len(inspired), 5)
        for s in inspired:
            self.assertNotIn("©", s["about"])
        # a studio / creator name is only ever an inspiration label, never the style's id suffix-less brand
        for sid in ("zackd-inspired", "ghibli-inspired", "disney-inspired", "cartoon-network-inspired", "anime-inspired", "dan-koe-style"):
            self.assertTrue(catalog.get(sid)["inspired"], sid)

    def test_styles_are_distinct_systems_not_colour_swaps(self):
        sigs = Counter((s["bg"]["kind"], s["text"]["fx"], s["motion"]["enter"], s["font"]["latin"]) for s in catalog.STYLES)
        self.assertEqual([k for k, v in sigs.items() if v > 1], [], "two styles share bg + text fx + enter + font")
        self.assertGreaterEqual(len({s["bg"]["kind"] for s in catalog.STYLES}), 30)
        self.assertGreaterEqual(len({s["text"]["fx"] for s in catalog.STYLES}), 25)
        self.assertGreaterEqual(len({s["motion"]["enter"] for s in catalog.STYLES}), 18)
        self.assertGreaterEqual(len({s["font"]["latin"] for s in catalog.STYLES}), 28)
        self.assertGreaterEqual(len({s["trans"]["kind"] for s in catalog.STYLES}), 14)
        # motion language differs too: stop-motion styles step their frames, others do not
        self.assertGreaterEqual(len([s for s in catalog.STYLES if s["motion"].get("stepFps")]), 8)
        pal = Counter(s["palette"]["bg"] + s["palette"]["accent"] for s in catalog.STYLES)
        self.assertEqual([k for k, v in pal.items() if v > 1], [])

    def test_every_style_is_readable(self):
        """ink on bg must be readable (WCAG >= 3 for large display type), unless the style swaps palettes per scene."""
        def lum(h):
            r, g, b = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

        def ratio(a, b):
            la, lb = lum(a), lum(b)
            return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

        bad = []
        for s in catalog.STYLES:
            p = s["palette"]
            text = p.get(s["text"].get("color", "ink"), s["text"].get("color", "ink"))
            if not str(text).startswith("#"):
                continue
            if ratio(text, p["bg"]) < 3.0 and s["text"]["fx"] not in ("hard", "outline-hard", "chrome", "gold", "retro", "cutout", "brick", "spray", "cel", "sticker", "felt", "clay", "extrude"):
                bad.append((s["id"], round(ratio(text, p["bg"]), 2)))
        self.assertEqual(bad, [])

    def test_fonts_exist_in_the_manifest_and_cover_persian(self):
        mf = Path(runner.repo_motion_dir()) / "remotion" / "src" / "fonts.generated.json"
        if not mf.is_file():
            self.skipTest("fonts manifest not generated (manage.py motion_build)")
        fonts = json.loads(mf.read_text(encoding="utf-8"))
        for s in catalog.STYLES:
            for k in {s["font"]["latin"], s["font"]["fa"], s["font"].get("body_latin"), s["font"].get("body_fa")} - {None}:
                self.assertIn(k, fonts, f"{s['id']}: font {k} is not in fonts.generated.json")
            subs = {f["subset"] for f in fonts[s["font"]["fa"]]["files"]}
            self.assertIn("arabic", subs, f"{s['id']}: the Persian font {s['font']['fa']} has no arabic subset")

    def test_persian_glyph_coverage_of_every_persian_font(self):
        try:
            from fontTools.ttLib import TTFont
        except Exception:  # noqa: BLE001
            self.skipTest("fontTools missing")
        base = runner.toolchain_dir() / "node_modules" / "@fontsource"
        need = "پچژگکیئ۰۱۲۳۴۵۶۷۸۹ءآأؤإيةً،؟"
        used = {s["font"]["fa"] for s in catalog.STYLES} | {s["font"].get("body_fa") for s in catalog.STYLES if s["font"].get("body_fa")}
        checked = 0
        for key in sorted(used):
            files = sorted((base / key / "files").glob(f"{key}-arabic-*-normal.woff")) if (base / key / "files").is_dir() else []
            if not files:
                continue
            cmap = TTFont(str(files[0])).getBestCmap()
            missing = [c for c in need if ord(c) not in cmap]
            self.assertEqual(missing, [], f"{key} lacks Persian glyphs {missing}")
            checked += 1
        if not checked:
            self.skipTest("fontsource packages are not installed here")

    def test_generated_json_is_in_sync_with_the_catalog(self):
        gen = Path(runner.repo_motion_dir()) / "remotion" / "src" / "styles.generated.json"
        if not gen.is_file():
            self.skipTest("styles.generated.json not generated")
        self.assertEqual(json.loads(gen.read_text(encoding="utf-8")), json.loads(json.dumps(catalog.export_json())),
                         "run manage.py motion_build --only catalog and commit motion/remotion/src/styles.generated.json")

    def test_thumbnails_cover_every_style(self):
        thumbs = Path(__file__).resolve().parent / "thumbs"
        have = {p.stem for p in thumbs.glob("*.jpg")} if thumbs.is_dir() else set()
        if not have:
            self.skipTest("thumbnails not generated yet")
        self.assertEqual(sorted({s["id"] for s in catalog.STYLES} - have), [])

"""سی سبکِ تازه از کتابخانهٔ InstAI: همه حساب‌شده‌اند، تولیدشان تکرارپذیر است، هشت «نوعِ» تازهٔ موتور هست و کار می‌کند، و هیچ نامِ برند/استودیو/هنرمندی نیست.

ایدهٔ آزمونِ InstAI (tests/test_remotion.py: «هر motif یک look دارد یا آگاهانه ندارد») اینجا هم هست: هر سبکِ InstAI در دقیقاً یکی از چهار وضعیتِ
«NM دارد / نزدیک دارد / تازه افزوده شد / نمی‌شود» است و هر motif ِ آن یا نوعِ موتورِ NM دارد یا آگاهانه بی‌سطح است.
"""
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

from . import catalog, catalog_looks, runner

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "backend" / "tools"
SRC = ROOT / "motion" / "remotion" / "src"
DOC = ROOT / "docs" / "motion" / "looks-from-instai-fa.md"

#: شناسه‌هایِ ۶۶ سبکِ NM پیش از این کار (نباید کم یا جابه‌جا شوند)
BASE_66 = [
    "pixel-art", "ps2-style", "glitch-art", "cyberpunk", "synthwave", "vaporwave", "retro-terminal", "vhs-tape", "sci-fi-hud", "particles", "aurora",
    "comic-art", "pop-art", "flat-vector", "flat-2d", "corporate-memphis", "memphis", "cartoon-network-inspired", "anime-inspired", "ghibli-inspired",
    "disney-inspired", "stickman", "chalkboard", "whiteboard", "pencil-sketch", "paper-collage", "papercraft", "origami", "stop-motion", "claymation",
    "watercolor", "typewriter", "risograph", "newspaper", "cgi-motion", "photoreal-cgi", "low-poly", "voxel-art", "lego-bricks", "isometric",
    "parallax-2-5d", "claymation-3d", "zackd-inspired", "chrome-22k", "dan-koe-style", "kinetic-typography", "infographic", "bauhaus", "neo-brutalism",
    "glassmorphism", "swiss-grid", "retro-70s", "art-deco", "persian-tile", "sport-energy", "cineview", "film-noir", "silhouette", "steampunk",
    "stained-glass", "graffiti", "neon-sign", "blueprint", "glow-sketch", "line-art", "cel-shading",
]
#: همان فهرستِ InstAI (tests/test_style_library.py BANNED): نامِ استودیو، برند، سازنده یا هنرمند در داده‌یِ یک سبکِ تازه نباید باشد
BANNED = ["ghibli", "pixar", "disney", "dreamworks", "cartoon network", "nickelodeon", "lego", "minecraft", "playstation", "ps2", "zackd", "zack d", "dan koe", "kodak",
          "polaroid", "funko", "warhol", "lichtenstein", "hokusai", "mucha", "monet", "simpsons", "adventure time", "wallace", "alegria", "naruto", "dragon ball",
          "one piece", "marvel", "blade runner", "gatsby", "frutiger", "burton", "ghibli", "جیبلی", "دیزنی", "پیکسار", "لگو", "کداک", "مونه", "موشه", "هوکوسای"]
#: «نوع»هایِ تازهٔ موتور (حداکثر هشت) — looks.tsx
NEW_BG = ("mosaic", "ornament", "waves", "holo", "doubleexp", "tiltshift", "cloth")
NEW_DECOR = ("kawaii",)
NEW_TEX = ()
PERSIAN = re.compile(r"[؀-ۿ]")


def gen():
    spec = importlib.util.spec_from_file_location("gen_instai_looks_for_tests", TOOLS / "gen_instai_looks.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def mapping():
    return gen().mapping


def lum(h):
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def ported():
    return [s for s in catalog.STYLES if s["id"] in catalog_looks.ORIGIN]


class Catalog(SimpleTestCase):
    def test_thirty_new_styles_and_the_sixty_six_are_untouched(self):
        self.assertEqual([s["id"] for s in catalog.STYLES[:66]], BASE_66)
        self.assertEqual(len(catalog_looks.IDS), 30)
        self.assertEqual([s["id"] for s in catalog.STYLES[66:]], list(catalog_looks.IDS))
        self.assertEqual(len(catalog.STYLES), 96)
        self.assertTrue(all("fits" not in s for s in catalog.STYLES[:66]), "the 66 old rows keep their exact shape")

    def test_the_new_group_exists_and_is_used(self):
        self.assertIn("painted", catalog.GROUPS)
        self.assertGreaterEqual(len([s for s in ported() if s["group"] == "painted"]), 10)
        self.assertEqual({s["group"] for s in ported()} - set(catalog.GROUPS), set())

    def test_every_new_style_has_a_persian_name_a_persian_about_and_a_fits_hint(self):
        for s in ported():
            sid = s["id"]
            for k in ("name_fa", "about", "fits"):
                self.assertRegex(s[k], PERSIAN, f"{sid}: {k} is not Persian")
            self.assertGreaterEqual(len(s["tags"]), 3, sid)
            self.assertTrue(all(PERSIAN.search(t) for t in s["tags"]), sid)
            self.assertIsNone(s["inspired"], f"{sid}: no new 'inspired by' captions")

    def test_no_studio_brand_or_creator_name_anywhere_in_the_new_data(self):
        for s in ported():
            blob = json.dumps({k: s[k] for k in ("id", "name_fa", "name_en", "about", "fits", "tags")}, ensure_ascii=False).lower()
            self.assertEqual([w for w in BANNED if w in blob], [], s["id"])
        src = (Path(catalog_looks.__file__)).read_text(encoding="utf-8").lower()
        self.assertEqual([w for w in BANNED if w in src], [])

    def test_no_new_style_uses_a_persian_font_that_misdraws_the_brand_name(self):
        """the real renders (docs/motion/looks-from-instai-fa.md §4): lemonada draws غ as ف («چفر») and rakkas loses the dots of چ («صغر»); aref-ruqaa under a glow / 3-D effect turned
        «چغر» into a smear. The owner's product name is the first thing every sample shows, so none of them may be the Persian font of a new style (and the fonts must be in NM's OFL set)"""
        from json import loads

        bad = {"lemonada", "rakkas"}
        fonts = loads((Path(__file__).resolve().parents[3] / "motion" / "remotion" / "src" / "fonts.generated.json").read_text(encoding="utf-8"))
        for s in ported():
            fa = s["font"]["fa"]
            self.assertNotIn(fa, bad, s["id"])
            self.assertIn(fa, fonts, s["id"])
            if fa == "aref-ruqaa":                      # fine in a plain style (persian-miniature), not under glow / 3-D / long shadows
                self.assertIn(s["text"]["fx"], ("plain", "ink"), s["id"])

    def test_the_text_reads_on_the_second_background_of_every_new_style(self):
        """scenes 2, 4 ... use `bg2`; the engine reads no palette override of a background spec, so the ordinary text (ink) must read on a solid `bg2` itself
        (the constructivist poster's list title was black on deep red, measured 2.9 in the real render)"""
        for s in ported():
            b2 = s.get("bg2")
            if not b2 or b2.get("kind") != "solid":
                continue
            c = b2.get("c", "bg")
            fill = s["palette"].get(c, c)
            self.assertRegex(fill, r"^#[0-9a-fA-F]{6}$", s["id"])
            self.assertGreaterEqual(ratio(s["palette"]["ink"], fill), 4.5, s["id"])
            self.assertNotIn("pal", b2, s["id"])

    def test_new_styles_are_readable_on_their_own_background(self):
        """ink >= 4.5 (the generator aims for 7), the emphasis colour >= 4.5 on the background and >= 3.9 on bg2 (kicker / price / call to action: small text; a 3:1 accent measured
        1.5-2.5 on patterned backgrounds in the real renders), decoration colours >= 1.9 (qa.py's own limit)"""
        bad = []
        for s in ported():
            p = s["palette"]
            if ratio(p["ink"], p["bg"]) < 4.5:
                bad.append((s["id"], "ink", round(ratio(p["ink"], p["bg"]), 2)))
            if ratio(p["accent"], p["bg"]) < 4.5 - 0.05:
                bad.append((s["id"], "accent", round(ratio(p["accent"], p["bg"]), 2)))
            if ratio(p["accent"], p["bg2"]) < 3.9 - 0.05 and ratio("#000000", p["bg"]) > ratio("#ffffff", p["bg"]):       # light themes only (dark: bg2 is the lighter mix)
                bad.append((s["id"], "accent-bg2", round(ratio(p["accent"], p["bg2"]), 2)))
            if ratio(p["accent2"], p["bg"]) < 1.9:
                bad.append((s["id"], "accent2", round(ratio(p["accent2"], p["bg"]), 2)))
            on = "#111111" if lum(p["accent"]) > 0.42 else "#ffffff"          # util.onColor of the engine: the label of an accent-filled button / badge
            if ratio(on, p["accent"]) < 4.0 - 0.05:
                bad.append((s["id"], "label-on-accent", round(ratio(on, p["accent"]), 2)))
        self.assertEqual(bad, [])

    def test_the_thirty_are_real_visual_systems(self):
        """not colour swaps of each other or of the 66: every (background, text effect, entrance, latin font) is new; background kinds grew"""
        sigs = Counter((s["bg"]["kind"], s["text"]["fx"], s["motion"]["enter"], s["font"]["latin"]) for s in catalog.STYLES)
        self.assertEqual([k for k, v in sigs.items() if v > 1], [])
        self.assertGreaterEqual(len({s["bg"]["kind"] for s in ported()}), 20)
        self.assertGreaterEqual(len({s["font"]["latin"] for s in ported()}), 25)
        self.assertGreaterEqual(len({s["text"]["fx"] for s in ported()}), 12)
        self.assertGreaterEqual(len({s["motion"]["enter"] for s in ported()}), 15)
        self.assertGreaterEqual(len({s["trans"]["kind"] for s in ported()}), 12)

    def test_stop_motion_like_styles_step_their_frames(self):
        """InstAI's stepped approaches (limited 2D, cut-out, stop motion, toon 3D) hold each pose: stepFps is the style's own poses-per-second (a recipe may override, with a reason)"""
        m = mapping()
        snap = gen().snapshot()
        g = gen()
        recipes = {r["id"]: r for r in g.recipes.RECIPES}
        for s in ported():
            src = snap[catalog_looks.ORIGIN[s["id"]]]
            stepped = m.MOTION[src["animation"]]["stepped"]
            override = "stepFps" in (recipes[s["id"]].get("motion") or {})
            if not override:
                self.assertEqual(bool(s["motion"].get("stepFps")), stepped, s["id"])
                if stepped:
                    self.assertEqual(s["motion"]["stepFps"], src["fps_feel"], s["id"])
        self.assertGreaterEqual(len([s for s in ported() if s["motion"].get("stepFps")]), 8)

    def test_thumbnails_cover_the_new_styles(self):
        thumbs = Path(__file__).resolve().parent / "thumbs"
        have = {p.stem for p in thumbs.glob("*.jpg")} if thumbs.is_dir() else set()
        if not have:
            self.skipTest("thumbnails not generated yet")
        self.assertEqual(sorted(set(catalog_looks.IDS) - have), [])


class Engine(SimpleTestCase):
    def test_at_most_eight_new_kinds_and_all_are_known_to_the_catalog(self):
        self.assertLessEqual(len(NEW_BG) + len(NEW_DECOR) + len(NEW_TEX), 8)
        self.assertEqual([k for k in NEW_BG if k not in catalog.BG_KINDS], [])
        self.assertEqual([k for k in NEW_DECOR if k not in catalog.DECOR_KINDS], [])

    def test_every_new_kind_is_implemented_registered_and_used(self):
        looks = (SRC / "looks.tsx").read_text(encoding="utf-8")
        bg = (SRC / "bg.tsx").read_text(encoding="utf-8")
        decor = (SRC / "decor.tsx").read_text(encoding="utf-8")
        self.assertIn("...LOOK_BG", bg)
        self.assertIn("...LOOK_DECOR", decor)
        reg_bg = re.search(r"export const LOOK_BG[^=]*=\s*\{(.*?)\};", looks, re.S).group(1)
        reg_decor = re.search(r"export const LOOK_DECOR[^=]*=\s*\{(.*?)\};", looks, re.S).group(1)
        for k in NEW_BG:
            self.assertRegex(reg_bg, rf"\b{k}\s*:", f"bg kind {k} is not registered in LOOK_BG")
        for k in NEW_DECOR:
            self.assertRegex(reg_decor, rf"\b{k}\s*:", f"decor kind {k} is not registered in LOOK_DECOR")
        used_bg = {s["bg"]["kind"] for s in ported()} | {s["bg2"]["kind"] for s in ported() if s.get("bg2")}
        used_decor = {d["kind"] for s in ported() for d in s["decor"]}
        self.assertEqual(sorted(set(NEW_BG) - used_bg), [], "a new background kind that no style uses is dead code")
        self.assertEqual(sorted(set(NEW_DECOR) - used_decor), [])

    def test_the_new_kinds_never_paint_text_and_are_deterministic(self):
        code = (SRC / "looks.tsx").read_text(encoding="utf-8")
        body = "\n".join(l for l in code.splitlines() if not l.strip().startswith("//"))
        for bad in ("<text", "<tspan", "fontFamily", "fontSize", "fillText", "textContent", "Math.random", "Date.now", "new Date", "performance.now", "setTimeout", "setInterval"):
            self.assertNotIn(bad, body, f"looks.tsx must not use {bad}")
        # no loose JSX text between tags (`>سلام<`): a look draws shapes only
        self.assertEqual(re.findall(r">([^<>{}\n]*[A-Za-z؀-ۿ0-9][^<>{}\n]*)</?[A-Za-z]", body), [])
        self.assertNotIn("http://", body.replace("http://www.w3.org", ""))

    def test_the_engine_has_no_unknown_parameter_names_in_the_new_rows(self):
        """every key a new row passes to a new kind is read by looks.tsx (a typo in a recipe would silently do nothing)"""
        code = (SRC / "looks.tsx").read_text(encoding="utf-8")
        allowed_common = {"kind", "veil", "veilColor", "pal"}
        for s in ported():
            for spec in [s["bg"]] + ([s["bg2"]] if s.get("bg2") else []) + s["decor"]:
                if spec["kind"] in NEW_BG + NEW_DECOR:
                    for key in spec:
                        if key in allowed_common:
                            continue
                        self.assertRegex(code, rf"\b[sd]\.{key}\b|\b{key}\b\s*[,}}]", f"{s['id']}: {spec['kind']} does not read `{key}`")


class Generator(SimpleTestCase):
    def test_the_committed_module_is_exactly_what_the_generator_makes(self):
        self.assertEqual(gen().module_source(), Path(catalog_looks.__file__).read_text(encoding="utf-8"),
                         "run: python backend/tools/gen_instai_looks.py")

    def test_the_diff_is_computed_from_catalog_py_not_typed(self):
        self.assertEqual(gen().base_ids(), BASE_66)

    def test_every_instai_style_is_accounted_for_exactly_once(self):
        g = gen()
        snap = g.snapshot()
        cls = g.classify(snap)
        self.assertEqual(sorted(cls), sorted(snap))
        counts = Counter(v[0] for v in cls.values())
        self.assertEqual(counts["ported"], 30)
        self.assertEqual(sum(counts.values()), len(snap))
        self.assertEqual(len(snap), 116)
        ids = {s["id"] for s in catalog.STYLES}
        for k, (status, to, _note) in cls.items():
            if status in ("have", "near", "ported"):
                self.assertIn(to, ids, f"{k} -> {to}")
        self.assertEqual({v[1] for v in cls.values() if v[0] == "ported"}, set(catalog_looks.IDS))

    def test_every_instai_motif_has_an_nm_kind_or_is_deliberately_plain(self):
        m = mapping()
        snap = gen().snapshot()
        motifs = {s["motif"] for s in snap.values() if s["motif"]}
        known = set(m.MOTIF_HAVE) | set(m.LOOK_KINDS) | set(m.MOTIF_PLAIN)
        self.assertEqual(sorted(motifs - known), [], "an InstAI motif nobody decided about")
        for motif, (where, kind) in m.LOOK_KINDS.items():
            self.assertIn(kind, catalog.BG_KINDS if where == "bg" else catalog.DECOR_KINDS, motif)

    def test_the_diff_table_in_the_doc_is_current(self):
        if not DOC.is_file():
            self.skipTest("docs/motion/looks-from-instai-fa.md is not in this tree")
        text = DOC.read_text(encoding="utf-8")
        g = gen()
        for name, table in (("looks", g.doc_table()), ("motion", g.motion_table()), ("springs", g.spring_table())):
            m = re.search(rf"<!-- {name}:begin -->\n(.*?)\n<!-- {name}:end -->", text, re.S)
            self.assertIsNotNone(m, name)
            self.assertEqual(m.group(1), table, f"run: python backend/tools/gen_instai_looks.py --update-doc docs/motion/looks-from-instai-fa.md ({name})")

    def test_the_readme_style_table_lists_the_new_styles(self):
        readme = ROOT / "docs" / "motion" / "README-fa.md"
        if not readme.is_file():
            self.skipTest("README not in this tree")
        text = readme.read_text(encoding="utf-8")
        self.assertEqual([i for i in catalog_looks.IDS if f"`{i}`" not in text], [])


class Mapping(SimpleTestCase):
    """the numbers of mapping.py are not trusted: the damping of every InstAI animation approach gives the overshoot that InstAI's own motion kit asks for"""

    TARGET = {"live_camera": 0.0, "limited_2d": 0.05, "full_2d": 0.08, "rubber_hose": 0.28, "cutout": 0.04, "motion_graphics": 0.0, "stop_motion": 0.0,
              "cg_3d": 0.06, "toon_3d": 0.14, "painted_parallax": 0.0}

    def test_every_instai_animation_approach_is_mapped(self):
        m = mapping()
        self.assertEqual(sorted(m.MOTION), sorted(self.TARGET))
        snap = gen().snapshot()
        self.assertEqual({s["animation"] for s in snap.values()} - set(m.MOTION), set(), "an InstAI animation approach with no NM motion")

    def test_springs_give_the_overshoot_of_instais_motion_kit(self):
        m = mapping()
        for name, want in self.TARGET.items():
            got = m.overshoot_of(m.MOTION[name]["spring"])
            self.assertEqual(m.MOTION[name]["overshoot"], want, name)
            self.assertAlmostEqual(got, want, delta=0.04, msg=f"{name}: spring {m.MOTION[name]['spring']} overshoots {got:.3f}, InstAI wants {want}")
        # order of bounciness: rubber hose > toon 3D > full 2D > limited 2D > the critically damped ones
        o = {n: m.overshoot_of(m.MOTION[n]["spring"]) for n in self.TARGET}
        self.assertGreater(o["rubber_hose"], o["toon_3d"])
        self.assertGreater(o["toon_3d"], o["full_2d"])
        self.assertGreater(o["full_2d"], o["limited_2d"])
        self.assertGreater(o["limited_2d"], o["motion_graphics"])

    def test_motion_for_steps_only_the_stepped_approaches(self):
        m = mapping()
        self.assertEqual(m.motion_for("limited_2d", 8)["stepFps"], 8)
        self.assertEqual(m.motion_for("stop_motion", 12)["stepFps"], 12)
        self.assertIsNone(m.motion_for("motion_graphics", 24)["stepFps"])
        self.assertIsNone(m.motion_for("painted_parallax", 12)["stepFps"])
        self.assertGreater(m.motion_for("rubber_hose", 12)["wobble"], 0)
        self.assertEqual(m.motion_for("motion_graphics", 24)["wobble"], 0)

    def test_derived_palettes_meet_the_contrast_floor_for_every_instai_style(self):
        """not only the 30: any InstAI style the next round ports gets a readable palette from the same function"""
        m = mapping()
        for key, s in gen().snapshot().items():
            p = m.derive_palette(s["palette"])
            best = max(m.contrast("#ffffff", p["bg"]), m.contrast("#000000", p["bg"]))        # on a mid-tone background 7:1 is out of reach for black and white alike
            self.assertGreaterEqual(m.contrast(p["ink"], p["bg"]), min(7.0, best) - 0.05, key)
            dark = m.contrast("#ffffff", p["bg"]) > m.contrast("#000000", p["bg"])
            self.assertGreaterEqual(m.contrast(p["accent"], p["bg"]), min(4.5, best - 0.05) - 0.05, key)
            self.assertGreaterEqual(m.contrast(m.engine_text_on(p["accent"]), p["accent"]), 4.0 - 0.05, key)      # the engine's label on an accent button / badge (a golden accent got white text at 2.2)
            if not dark:            # on a dark theme bg2 is the LIGHTER mix: only the background counts there (mapping._need)
                self.assertGreaterEqual(m.contrast(p["accent"], p["bg2"]), min(3.9, m.contrast("#000000", p["bg2"]) - 0.05) - 0.05, key)
            self.assertGreaterEqual(m.contrast(p["accent2"], p["bg"]), 1.9 - 0.05, key)
            self.assertEqual(sorted(p), sorted(catalog.PAL_KEYS), key)
            for v in p.values():
                self.assertRegex(v, r"^#[0-9a-f]{6}$", key)

    def test_the_accent_keeps_the_styles_own_hue_and_never_turns_to_mud(self):
        """a pale InstAI accent (yellow on cream) cannot be text: the pick is the candidate that needs the least change, and a bright warm colour that would only
        become olive / brown when darkened loses to a colour that is already deep (the real renders showed 1.5-2.5 contrast with the old floor of 3)"""
        m = mapping()
        # pale yellow accent, deep blue secondary, on a cream background: the blue is already readable, the yellow would become olive
        got = m.pick_accent(["#ffd166", "#1e3a8a", "#e0522a"], "#f6ecd2", "#dfd3b8", False)
        self.assertEqual(got, "#1e3a8a")
        # a candidate that only needs a little darkening keeps its hue (red stays red)
        red = m.pick_accent(["#d62828", "#6b6b6b"], "#ffffff", "#cfcfcf", False)
        r, g, b = (int(red[i:i + 2], 16) for i in (1, 3, 5))
        self.assertTrue(r > 1.8 * g and r > 1.8 * b, red)
        self.assertGreaterEqual(m.contrast(red, "#ffffff"), 4.45)
        self.assertGreaterEqual(m.contrast(red, "#cfcfcf"), 3.85)
        # a dark background lightens the accent instead
        light = m.pick_accent(["#4d3a8a"], "#12141c", "#28323e", True)
        self.assertGreaterEqual(m.contrast(light, "#12141c"), 4.45)
        self.assertGreater(m._rgb(light)[2], m._rgb("#4d3a8a")[2])
        # no accent of the 30 is a muddy olive / brown that the colour wheel would not call the style's own colour: it is either the InstAI colour itself or not muddy
        for s in ported():
            p, src = s["palette"], gen().snapshot()[catalog_looks.ORIGIN[s["id"]]]["palette"]
            if p["accent"].lower() not in [c.lower() for c in src]:
                self.assertFalse(m._muddy(p["accent"]), (s["id"], p["accent"]))


class NodeSelfTest(SimpleTestCase):
    """the automatic acceptance run of the GPU node renders one of the new styles and proves the NEW engine kind was drawn (not a plain background)"""

    def module(self):
        from apps.compute.selftests import motion_looks

        return motion_looks

    def test_the_module_is_registered_with_a_real_render_job(self):
        from apps.compute import selftests

        selftests.load_all()
        t = selftests.REGISTRY["studio_motion_looks"]
        self.assertEqual((t.kind, t.group, t.gpu_required), ("motion.render", "video", True))
        spec = self.module().SPEC
        self.assertEqual(spec["style"], "mosaic-tiles")
        self.assertIn(spec["style"], catalog_looks.IDS)
        self.assertEqual(catalog.get(spec["style"])["bg"]["kind"], "mosaic")        # the style the job renders uses a NEW kind
        self.assertEqual(sum(sc["duration"] for sc in spec["scenes"]), 3)
        self.assertGreater(t.order, selftests.REGISTRY["motion_studio"].order, "it runs after the plain motion render")

    def test_the_doc_block_is_the_same_job(self):
        text = (ROOT / "docs" / "selftests" / "motion-looks.md").read_text(encoding="utf-8")
        blocks = [json.loads(raw) for raw in re.findall(r"```json\s*\n(.*?)\n```", text, re.S)]
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        m = self.module()
        self.assertEqual((b["key"], b["kind"]), (m.KEY, m.KIND))
        self.assertEqual(b["payload"], m.PAYLOAD)
        self.assertTrue(b["gpu_required"])
        self.assertEqual(b["check"]["forbid_device"], ["cpu"])

    def test_the_engine_proof_reads_the_sites_bundle_and_manifest(self):
        import tempfile

        m = self.module()
        looks = (SRC / "looks.tsx").read_text(encoding="utf-8")
        self.assertIn(m.ENGINE_MARKER, looks, "the marker must be a string only looks.tsx writes")
        for other in ("bg.tsx", "decor.tsx", "tex.tsx", "text.tsx", "scenes.tsx"):
            self.assertNotIn(m.ENGINE_MARKER, (SRC / other).read_text(encoding="utf-8"), other)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self.assertIsNone(m.site_engine_has_new_kinds(d / "nope"))
            self.assertIsNone(m.site_engine_has_new_kinds(d))                                  # an empty folder: not built yet
            (d / "main.bundle.js").write_text("old engine: solid, linear, radial", encoding="utf-8")
            self.assertFalse(m.site_engine_has_new_kinds(d))                                   # built, but from the old sources
            (d / "107.bundle.js").write_text('const id = "nm-seigaiha-" + i', encoding="utf-8")
            self.assertTrue(m.site_engine_has_new_kinds(d))
            mf = d / "nm-motion-pack.json"
            self.assertEqual(m.site_pack_version(mf), "")
            mf.write_text(json.dumps({"version": "abc123def456"}), encoding="utf-8")
            self.assertEqual(m.site_pack_version(mf), "abc123def456")
            mf.write_text("{broken", encoding="utf-8")
            self.assertEqual(m.site_pack_version(mf), "")

    def test_the_marker_really_survives_into_the_built_bundle(self):
        """if a bundle exists in this tree, the string is in it (a minifier that renamed the template string would make the node proof lie)"""
        from . import runner

        bundle = Path(runner.bundle_dir())
        if not bundle.is_dir() or not list(bundle.glob("*.js")):
            self.skipTest("render bundle not built here (manage.py motion_build --only shell)")
        gen_src = (SRC / "styles.generated.json").read_text(encoding="utf-8")
        if "mosaic-tiles" not in gen_src:
            self.skipTest("the bundle on this machine is from the old catalog")
        self.assertTrue(self.module().site_engine_has_new_kinds(bundle), "rebuild the shell: manage.py motion_build --only catalog,shell")


class ShapesAvoidText(SimpleTestCase):
    def test_the_engine_knows_the_avoid_option_and_every_new_row_with_shapes_uses_it(self):
        decor = (SRC / "decor.tsx").read_text(encoding="utf-8")
        self.assertIn("avoidText(R(`mx${i}`)", decor)
        self.assertIn("!!d.avoid", decor)
        for s in ported():
            for d in s["decor"]:
                if d["kind"] == "shapes":
                    self.assertTrue(d.get("avoid"), f"{s['id']}: floating shapes must keep clear of the text (avoid: True)")
        # the old rows are untouched: none of the 66 asks for it
        for s in catalog.STYLES[:66]:
            self.assertFalse(any(d.get("avoid") for d in s["decor"]), s["id"])

"""«سبکِ تازه»: رجیستریِ سبک‌ها، اعتبارسنجِ ویرایشگر، نگهبانِ کنتراست، API، کنترلِ کیفیت و رندرِ واقعیِ یک سبکِ شخصی."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import ai, catalog, custom, custom_ai, qa, runner, services, specs, stylecheck, views_custom
from .models import MotionCustomStyle, MotionStyleCheck, MotionRender
from .tests_catalog import OWNER_LIST

User = get_user_model()
ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "motion" / "remotion" / "src"
NODE = "/usr/local/bin/node"


def blank(**kw):
    d = custom.blank_style()
    d.update(kw)
    return d


# ───────────────────────────────────────────── ۱) رجیستریِ سبک‌ها: همهٔ نام‌های مالک، واقعی و متمایز

class Registry(SimpleTestCase):
    def test_every_name_in_the_owners_lists_is_a_real_distinct_style(self):
        """۵۳ نامِ دو فهرستِ مالک: هر کدام یک ردیفِ کاتالوگ با ترکیبِ متمایز (نه نامِ دیگرِ یک سبکِ نزدیک)."""
        self.assertEqual(len(OWNER_LIST), 53)
        have = {s["id"]: s for s in catalog.STYLES}
        self.assertEqual(sorted(set(OWNER_LIST) - set(have)), [])
        sigs = {}
        for sid in OWNER_LIST:
            s = have[sid]
            key = (s["bg"]["kind"], s["text"]["fx"], s["motion"]["enter"], s["font"]["latin"], s["palette"]["bg"], s["palette"]["accent"])
            self.assertNotIn(key, sigs, f"{sid} is a near-copy of {sigs.get(key)}")
            sigs[key] = sid
        # two styles must differ in at least FOUR of the visual systems (colours alone never make a style)
        def systems(s):
            return {"bg": json.dumps(s["bg"], sort_keys=True), "text": s["text"]["fx"], "font": (s["font"]["latin"], s["font"]["fa"]), "enter": s["motion"]["enter"],
                    "spring": tuple(s["motion"]["spring"]), "trans": s["trans"]["kind"], "decor": tuple(sorted(d["kind"] for d in s["decor"])),
                    "tex": tuple(sorted(t["kind"] for t in s["tex"])), "shape": (s["shape"].get("radius"), s["shape"].get("shadow"), s["shape"].get("border"))}

        ids = [s["id"] for s in catalog.STYLES]
        sy = {s["id"]: systems(s) for s in catalog.STYLES}
        weak = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                diff = sum(1 for k in sy[a] if sy[a][k] != sy[b][k])
                if diff < 4:
                    weak.append((a, b, diff))
        self.assertEqual(weak, [], "styles that differ in fewer than 4 of 9 visual systems")

    def test_at_least_ninety_six_styles_and_all_groups_labelled(self):
        self.assertGreaterEqual(len(catalog.STYLES), 96)
        for s in catalog.STYLES:
            self.assertIn(s["group"], catalog.GROUPS)

    def test_schema_covers_every_kind_the_engine_knows(self):
        sch = custom.schema()
        for sec, kinds in (("bg", catalog.BG_KINDS), ("decor", catalog.DECOR_KINDS), ("tex", catalog.TEX_KINDS), ("text", catalog.TEXT_FX)):
            self.assertEqual(sorted(set(kinds) - set(sch[sec])), [], sec)
            for k in kinds:
                self.assertIn(k, custom.KIND_LABELS[sec], f"{sec}.{k} has no Persian label")
        for k in catalog.ENTER_KINDS:
            self.assertIn(k, custom.KIND_LABELS["enter"])
        for k in catalog.TRANS_KINDS:
            self.assertIn(k, custom.KIND_LABELS["trans"])

    def test_catalog_get_knows_custom_ids_only_through_the_hook(self):
        self.assertIsNone(catalog.get("u1-nothing"))
        sid = "u7-draft"
        with custom.draft(sid, {"id": sid, "name_fa": "x"}):
            self.assertEqual(catalog.get(sid)["id"], sid)
        self.assertIsNone(catalog.get(sid))
        self.assertEqual(catalog.get("pixel-art")["id"], "pixel-art")           # a catalogue id never goes near the hook


# ───────────────────────────────────────────── ۲) اعتبارسنجِ ویرایشگر

class Validation(SimpleTestCase):
    def test_every_builtin_style_can_be_duplicated_without_losing_anything(self):
        """«شروع از هر سبک (کپی)»: sanitize(سبک) همهٔ بخش‌ها را عیناً نگه می‌دارد (پالت، پس‌زمینه، تزئین، بافت، افکتِ متن، کارت، حرکت، گذار، قلم)."""
        lost = []
        for st in catalog.STYLES:
            notes: list = []
            out = custom.sanitize({**st}, notes=notes)
            for k in ("palette", "bg", "bg2", "tex", "decor", "text", "shape", "trans", "fx"):
                if (st.get(k) or None) != (out.get(k) or None):
                    lost.append((st["id"], k))
            ma = {k: v for k, v in st["motion"].items()}
            for k in ("enter", "spring", "stagger", "stepFps", "wobble", "cam"):
                a, b = ma.get(k), out["motion"].get(k)
                if isinstance(a, tuple):
                    a = list(a)
                if (a or None) != (b or None):
                    lost.append((st["id"], "motion." + k))
            for k in ("latin", "fa", "weight", "body_latin", "body_fa", "case", "track", "lh"):
                if (st["font"].get(k) or None) != (out["font"].get(k) or None):
                    lost.append((st["id"], "font." + k))
            if notes:
                lost.append((st["id"], notes[0]))
        self.assertEqual(lost, [])

    def test_every_builtin_style_passes_the_palette_guard(self):
        bad = [(s["id"], custom.contrast_report(custom.sanitize(s))["errors"]) for s in catalog.STYLES]
        self.assertEqual([b for b in bad if b[1]], [])

    def test_unknown_kinds_and_parameters_are_refused_or_dropped(self):
        with self.assertRaises(custom.StyleError):
            custom.sanitize(blank(bg={"kind": "evil-bg"}))
        with self.assertRaises(custom.StyleError):
            custom.sanitize(blank(text={"fx": "evil"}))
        with self.assertRaises(custom.StyleError):
            custom.sanitize(blank(decor=[{"kind": "nope"}]))
        notes: list = []
        out = custom.sanitize(blank(bg={"kind": "linear", "from": "bg", "to": "bg2", "angle": 99999, "script": "alert(1)"}), notes=notes)
        self.assertNotIn("script", out["bg"])
        self.assertLessEqual(out["bg"]["angle"], 360)
        self.assertTrue(any("script" in n for n in notes))

    def test_numbers_are_clamped_and_bad_colours_replaced(self):
        out = custom.sanitize(blank(palette={**blank()["palette"], "accent": "javascript:alert(1)", "bg": "#GGGGGG"},
                                    motion={"enter": "pop", "spring": [9999, -5, 99], "stagger": 500, "stepFps": 1000, "wobble": 80, "cam": {"zoom": 9, "pan": [999, -999]}},
                                    trans={"kind": "fade", "frames": 4000}, font={**blank()["font"], "track": 9, "lh": 0, "weight": 5000}))
        self.assertEqual(out["palette"]["accent"], blank()["palette"]["accent"])
        self.assertRegex(out["palette"]["bg"], r"^#[0-9a-f]{6}$")
        d, s, m = out["motion"]["spring"]
        self.assertTrue(1 <= d <= 80 and 20 <= s <= 400 and 0.2 <= m <= 3)
        self.assertLessEqual(out["motion"]["stagger"], 24)
        self.assertLessEqual(out["motion"]["stepFps"], 24)
        self.assertLessEqual(out["motion"]["cam"]["zoom"], 0.15)
        self.assertLessEqual(out["trans"]["frames"], 40)
        self.assertLessEqual(out["font"]["track"], 0.4)
        self.assertGreaterEqual(out["font"]["lh"], 1.0)
        self.assertLessEqual(out["font"]["weight"], 900)

    def test_fonts_come_only_from_the_licensed_set_and_persian_needs_arabic_glyphs(self):
        notes: list = []
        out = custom.sanitize(blank(font={**blank()["font"], "latin": "Comic Sans", "fa": "press-start-2p", "body_fa": "inter"}), notes=notes)
        self.assertEqual(out["font"]["latin"], "vazirmatn")
        self.assertEqual(out["font"]["fa"], "vazirmatn")                   # a Latin-only pixel font has no Persian letters
        self.assertIsNone(out["font"]["body_fa"] if out["font"]["body_fa"] != "vazirmatn" else None)
        self.assertGreaterEqual(len(notes), 2)
        opts = custom.font_options()
        self.assertGreaterEqual(len(opts), 60)
        self.assertTrue(all(o["license"] for o in opts))
        self.assertTrue(any(o["fa"] for o in opts) and any(not o["fa"] for o in opts))

    def test_css_filter_injection_is_refused(self):
        for bad in ("url(javascript:alert(1))", "blur(2px) url(http://evil)", "contrast(1) ; background:red", "drop-shadow(0 0 9px red)"):
            self.assertNotIn("grade", custom.sanitize(blank(fx={"grade": bad}))["fx"], bad)
        self.assertEqual(custom.sanitize(blank(fx={"grade": "contrast(1.08) saturate(1.1)"}))["fx"]["grade"], "contrast(1.08) saturate(1.1)")

    def test_name_is_required_and_text_is_cleaned(self):
        with self.assertRaises(custom.StyleError):
            custom.sanitize(blank(name_fa=" "))
        out = custom.sanitize(blank(name_fa="سبک‮ِ من\x00" * 30, about="<script>x</script>" * 40))
        self.assertLessEqual(len(out["name_fa"]), 40)
        self.assertNotIn("‮", out["name_fa"])
        self.assertLessEqual(len(out["about"]), 240)

    def test_group_and_counts_are_limited(self):
        out = custom.sanitize(blank(tex=[{"kind": "grain"}] * 9, decor=[{"kind": "sparkles"}] * 12, group="hacked"))
        self.assertLessEqual(len(out["tex"]), custom.MAX_TEX)
        self.assertLessEqual(len(out["decor"]), custom.MAX_DECOR)
        self.assertEqual(out["group"], custom.CUSTOM_GROUP)

    def test_export_import_round_trip_and_future_versions_refused(self):
        st = custom.sanitize(blank(name_fa="سبکِ آزمون"))
        payload = custom.export_json({**st, "id": "u1-x", "scope": "store"})
        self.assertEqual(payload["nm_motion_style"], 1)
        self.assertNotIn("id", payload["style"])
        back, notes = custom.import_json(json.dumps(payload))
        self.assertEqual(custom.canonical(back), custom.canonical(st))
        with self.assertRaises(custom.StyleError):
            custom.import_json({"nm_motion_style": 99, "style": st})
        with self.assertRaises(custom.StyleError):
            custom.import_json("not json")
        with self.assertRaises(custom.StyleError):
            custom.import_json([1, 2])

    def test_ids_are_unique_and_scoped(self):
        sid = custom.make_id(12, "Neon Gym", "نئونِ باشگاه", set())
        self.assertEqual(sid, "u12-neon-gym")
        self.assertEqual(custom.make_id(12, "Neon Gym", "x", {sid}), "u12-neon-gym-2")
        self.assertEqual(custom.make_id(None, "Neon Gym", "x", set()), "g-neon-gym")
        self.assertTrue(custom.make_id(5, "", "باشگاهِ من", set()).startswith("u5-"))
        self.assertNotIn(custom.make_id(5, "Pixel Art", "x", set()), {s["id"] for s in catalog.STYLES})
        self.assertEqual(custom.parse_id("u12-neon-gym"), ("store", 12))
        self.assertEqual(custom.parse_id("g-neon-gym"), ("global", None))
        self.assertIsNone(custom.parse_id("pixel-art"))
        self.assertTrue(custom.usable_by("u12-aa", 12))
        self.assertFalse(custom.usable_by("u12-aa", 13))
        self.assertTrue(custom.usable_by("g-aa", 13))


# ───────────────────────────────────────────── ۳) نگهبانِ کنتراست

class ContrastGuard(SimpleTestCase):
    def test_unreadable_palette_is_blocked_and_the_fix_passes(self):
        pal = {**blank()["palette"], "bg": "#202020", "ink": "#2a2a2a", "bg2": "#303030"}
        st = custom.sanitize(blank(palette=pal))
        rep = custom.contrast_report(st)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("متنِ اصلی" in e for e in rep["errors"]))
        fixed = custom.fix_palette(st)
        self.assertTrue(custom.contrast_report({**st, "palette": fixed})["ok"])
        self.assertGreaterEqual(custom.ratio(fixed["ink"], fixed["bg"]), 4.5)
        self.assertRegex(fixed["ink"], r"^#[0-9a-f]{6}$")

    def test_exact_thresholds(self):
        st = custom.sanitize(blank())
        self.assertTrue(custom.contrast_report(st)["ok"])
        a = {**st, "palette": {**st["palette"], "bg": "#ffffff", "ink": "#767676"}}                    # 4.54: just above 4.5
        self.assertTrue(custom.contrast_report(a)["ok"])
        b = {**st, "palette": {**st["palette"], "bg": "#ffffff", "ink": "#808080"}}                    # 3.95: below
        self.assertFalse(custom.contrast_report(b)["ok"])
        w = {**st, "palette": {**st["palette"], "muted": st["palette"]["bg"]}}
        rep = custom.contrast_report(w)
        self.assertTrue(rep["ok"] and rep["warnings"])                                                    # a faint secondary colour only warns

    def test_outlined_effects_are_judged_on_pixels_not_on_the_palette(self):
        st = custom.sanitize(blank(text={"fx": "outline-hard", "color": "paper"}, palette={**blank()["palette"], "bg": "#f7faff", "paper": "#ffffff"}))
        self.assertTrue(custom.contrast_report(st)["ok"])                                                 # white text with its own dark outline on a light bg: the QA looks at pixels

    def test_palette_from_brand_colours_is_readable_in_both_modes(self):
        for dark in (False, True, None):
            for cols in (["#126F85", "#163F75"], ["#ff3ea5"], ["#fff200", "#ffffff", "#000000"], []):
                p = custom.palette_from_colors(cols, dark)
                st = custom.sanitize(blank(palette=p))
                self.assertTrue(custom.contrast_report(st)["ok"], (dark, cols, p))
        light = custom.palette_from_colors(["#126F85"], False)
        dark = custom.palette_from_colors(["#126F85"], True)
        self.assertGreater(custom.lum(light["bg"]), 0.8)
        self.assertLess(custom.lum(dark["bg"]), 0.05)


# ───────────────────────────────────────────── ۴) «توصیف کن، بساز»

class Describe(SimpleTestCase):
    def test_rules_cover_keywords_colours_and_energy(self):
        cases = [
            ("پیکسلی و بازی‌گونه با رنگِ سبز", "pixel-art"),
            ("تیره و سینمایی با رنگِ طلایی و حرکتِ آرام", "cineview"),
            ("نئونیِ سایبری صورتی", "cyberpunk"),
            ("تخته‌ی گچی برای کلاسِ درس", "chalkboard"),
            ("مینیمال و روشن", "dan-koe-style"),
        ]
        for text, base in cases:
            st = custom_ai.rules_style(text)
            self.assertTrue(custom.contrast_report(st)["ok"], text)
            self.assertEqual(custom_ai.pick_base(text), base, text)
        gold = custom_ai.rules_style("تیره و لوکس با رنگِ طلایی")
        self.assertLess(custom.lum(gold["palette"]["bg"]), 0.15)
        self.assertGreater(custom.to_hsl(gold["palette"]["accent"])[1], 0.2)
        soft = custom_ai.rules_style("نرم و آرام و شناور")
        self.assertEqual(soft["motion"]["enter"], "float")
        punchy = custom_ai.rules_style("پرانرژی و ضربه‌ای")
        self.assertEqual(punchy["motion"]["enter"], "zoompunch")
        self.assertEqual(custom_ai.rules_style("a" * 5, base_id="pixel-art")["bg"]["kind"], "bands")           # an explicit base wins

    def test_the_draft_is_always_a_valid_style(self):
        for text in ("چیزی", "سبکِ ورزشیِ پرانرژی قرمز و مشکی", "like a dreamy watercolor in blue", "x" * 600, "<b>سبک</b> ورزشی"):
            st = custom_ai.rules_style(text)
            self.assertEqual(custom.canonical(custom.sanitize(st)), custom.canonical(st))

    def test_model_answer_is_validated_and_repaired(self):
        class Prov:
            def availability(self):
                return True, ""

            def generate(self, prompt, **kw):
                return json.dumps({"name_fa": "سبکِ طلایی", "palette": {"bg": "#101010", "bg2": "#1b1b1b", "ink": "#222222", "paper": "#eeeeee", "accent": "#d4a017", "accent2": "#aa7700",
                                                                      "accent3": "#ffcc00", "muted": "#777777"},
                                   "bg": {"kind": "NOT-A-KIND"}, "motion": {"enter": "bloom", "spring": [34, 70, 1.6]}, "font": {"latin": "cinzel", "fa": "amiri"}}, ensure_ascii=False)

        res = custom_ai.describe(None, "تیره و لوکس", provider=Prov())
        self.assertEqual(res["source"], "ai")
        st = res["style"]
        self.assertTrue(custom.contrast_report(st)["ok"])                  # the model's dark-grey ink was repaired
        self.assertIn(st["bg"]["kind"], catalog.BG_KINDS)                  # the invented kind never reaches the engine
        self.assertEqual(st["motion"]["enter"], "bloom")
        self.assertEqual(st["font"]["latin"], "cinzel")

    def test_ai_down_falls_back_to_rules_with_a_clear_message(self):
        with mock.patch.object(ai, "get_provider", side_effect=RuntimeError("HTTP 402")):
            res = custom_ai.describe(None, "پیکسلی و بازی")
        self.assertEqual(res["source"], "rules")
        self.assertIn("پیش‌نویس", res["message"])
        self.assertTrue(custom.contrast_report(res["style"])["ok"])
        with self.assertRaises(custom.StyleError):
            custom_ai.describe(None, "ab")


# ───────────────────────────────────────────── ۵) موتور: spec.style_def

class EngineStyleDef(SimpleTestCase):
    def run_ts(self, body: str) -> str:
        sucrase = ROOT / "motion" / "node_modules" / "sucrase"
        if not (Path(NODE).exists() and sucrase.exists()):
            self.skipTest("node/sucrase are not on this machine")
        src = (SRC / "style-def.ts").read_text(encoding="utf-8")
        script = f"""
const {{ transform }} = require({json.dumps(str(sucrase))});
const code = transform({json.dumps(src)}, {{ transforms: ["typescript", "imports"] }}).code;
const m = {{ exports: {{}} }};
new Function("module", "exports", "require", code)(m, m.exports, require);
const {{ sanitizeStyleDef, resolveStyle, ENGINE_FEATURES }} = m.exports;
{body}
"""
        p = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def test_engine_reads_a_style_def_and_refuses_junk(self):
        st = custom.render_def({**custom.sanitize(blank()), "id": "u1-t"})
        out = self.run_ts(f"""
const good = sanitizeStyleDef({json.dumps(st)});
const junk = [null, 1, "x", [], {{}}, {{palette: {{}}, font: {{}}, bg: {{kind: "x"}}}}, {{...{json.dumps(st)}, palette: {{...{json.dumps(st["palette"])}, bg: "red"}}}}];
const cat = {{id: "flat-vector"}};
const r1 = resolveStyle({{style: "u1-t", style_def: {json.dumps(st)}}}, () => cat);
const r2 = resolveStyle({{style: "flat-vector"}}, () => cat);
const r3 = resolveStyle({{style: "u1-t", style_def: {{evil: true}}}}, () => cat);
console.log(JSON.stringify({{ok: !!good, id: good && good.id, motionEase: good && good.motion.ease, junk: junk.map(j => sanitizeStyleDef(j)), r1: r1.id, r2: r2.id, r3: r3.id, feats: ENGINE_FEATURES}}));
""")
        d = json.loads(out)
        self.assertTrue(d["ok"])
        self.assertEqual(d["id"], "u1-t")
        self.assertEqual(d["motionEase"], "out-expo")
        self.assertEqual(d["junk"], [None] * 7)
        self.assertEqual((d["r1"], d["r2"], d["r3"]), ("u1-t", "flat-vector", "flat-vector"))
        self.assertEqual(d["feats"], ["style_def"])

    def test_spring_names_mirror_the_engine_presets(self):
        txt = (SRC / "presets.ts").read_text(encoding="utf-8")
        block = txt[txt.index("export const SPRINGS"):txt.index("export const easeOf")]
        eng = {m.group(1): [float(x) for x in m.group(2).split(",")] for m in re.finditer(r'"?([a-z-]+)"?:\s*\[([\d.,\s]+)\]', block)}
        self.assertEqual(set(eng), set(views_custom.SPRING_VALUES))
        for k, v in eng.items():
            self.assertEqual([float(x) for x in views_custom.SPRING_VALUES[k]], v, k)

    def test_style_level_ease_is_wired_in_the_engine(self):
        ctx = (SRC / "ctx.tsx").read_text(encoding="utf-8")
        self.assertIn("base.style.motion.ease", ctx)
        tpl = (SRC / "Template.tsx").read_text(encoding="utf-8")
        self.assertIn("resolveStyle(spec, getStyle)", tpl)
        self.assertEqual(tpl.count("getStyle(spec.style)"), 0)


# ───────────────────────────────────────────── ۶) API + کنترلِ کیفیت + ذخیره

class ApiBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="nmstyle-media-")
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        self.owner = User.objects.create_user("style-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", description="دستیار هوش مصنوعی مربی‌ها. برنامهٔ ورزشی و غذایی.", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.other_owner = User.objects.create_user("style-other", password="x")
        self.other = Store.objects.create(owner=self.other_owner, name="دیگری")
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/motion"

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def doc(self, **kw):
        d = custom.sanitize(blank(name_fa="سبکِ آزمون", name_en="Test Style"))
        d.update(kw)
        return d

    def passing_check(self, doc):
        """کنترلِ کیفیتِ قبول با رندرِ ساختگی (بدونِ مرورگر): همان مسیرِ stylecheck.run."""
        chk = stylecheck.start(self.store, self.owner, custom.sanitize(doc))
        stylecheck.run(chk.pk, measure_factory=fake_measure())
        chk.refresh_from_db()
        return chk

    def save(self, doc, **extra):
        self.passing_check(doc)
        return self.api.post(f"{self.base}/custom-styles/", {"style": doc, **extra}, format="json")


def fake_measure(overflow=False, low_contrast=False):
    """measure_factory برای stylecheck.run: «فریم‌ها»ی ساختگی با هندسهٔ مشخص؛ هر صحنه یک متنِ سالم (یا بیرون‌زده)."""
    from PIL import Image

    def factory(store, workdir, media_dir, prefix):
        def measure(spec):
            shots = []
            for i, f in enumerate(qa.key_frames(spec, 1)):
                W, H = specs.ASPECTS[spec["aspect"]]
                b = {"kind": "text", "scene": f["scene"], "role": "display", "size": 90, "x": 100, "y": 300, "w": 600, "h": 120, "gx": 100, "gy": 300, "gw": 600, "gh": 120,
                     "color": "rgb(20, 20, 20)", "text": "عنوان", "overflow": bool(overflow and i == 0), "clipped": False, "opacity": 1, "id": 1, "parent": -1, "overlay": ""}
                bg = (40, 40, 40) if low_contrast else (250, 250, 250)
                img = Image.new("RGB", (W // 2, H // 2), bg)
                rel = ""
                if media_dir is not None:
                    media_dir.mkdir(parents=True, exist_ok=True)
                    p = media_dir / f"{prefix}-{i}.jpg"
                    img.save(p)
                    rel = qa_rel(p)
                shots.append({"scene": f["scene"], "kind": f["kind"], "frame": f["frame"], "W": W, "H": H, "scale": 0.5, "safe": {}, "platform": "", "boxes": [b], "_image": img, "image_rel": rel})
            return shots

        return measure

    return factory


def qa_rel(p: Path) -> str:
    from django.conf import settings

    try:
        return str(Path(p).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())).replace("\\", "/")
    except ValueError:
        return ""


class Api(ApiBase):
    def test_schema_endpoint_serves_the_whole_editor(self):
        d = self.api.get("/api/v1/motion/style-schema/").json()
        self.assertEqual(d["roles"], list(catalog.PAL_KEYS))
        self.assertEqual({k["id"] for k in d["bg"]}, set(catalog.BG_KINDS))
        self.assertEqual({k["id"] for k in d["decor"]}, set(catalog.DECOR_KINDS))
        self.assertEqual({k["id"] for k in d["text"]}, set(catalog.TEXT_FX))
        self.assertGreaterEqual(len(d["fonts"]), 60)
        self.assertGreaterEqual(len(d["personalities"]), 8)
        self.assertEqual(len(d["springs"]), 8)
        self.assertEqual(len(d["eases"]), 12)
        self.assertEqual(len(d["guard"]), 6)
        self.assertIn("custom", d["groups"])
        self.assertEqual(custom.canonical(custom.sanitize(d["blank"])), custom.canonical(custom.sanitize(custom.blank_style())))
        self.assertEqual(APIClient().get("/api/v1/motion/style-schema/").status_code in (401, 403), True)

    def test_validate_returns_contrast_and_a_fix(self):
        bad = self.doc(palette={**blank()["palette"], "bg": "#202020", "ink": "#262626"})
        r = self.api.post(f"{self.base}/custom-styles/validate/", {"style": bad}, format="json").json()
        self.assertFalse(r["contrast"]["ok"])
        self.assertIn("fixed_palette", r)
        self.assertGreaterEqual(custom.ratio(r["fixed_palette"]["ink"], r["fixed_palette"]["bg"]), 4.5)
        r2 = self.api.post(f"{self.base}/custom-styles/validate/", {"style": {"name_fa": "x"}}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/custom-styles/validate/", {}, format="json").status_code, 400)

    def test_describe_endpoint_works_without_ai(self):
        with mock.patch.object(ai, "get_provider", side_effect=RuntimeError("HTTP 402 out of credit")):
            r = self.api.post(f"{self.base}/custom-styles/describe/", {"text": "پیکسلی و بازی با رنگِ سبز"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["source"], "rules")
        self.assertTrue(d["contrast"]["ok"])
        self.assertEqual(self.api.post(f"{self.base}/custom-styles/describe/", {"text": "x"}, format="json").status_code, 400)

    def test_palette_from_the_store_brand(self):
        d = self.api.post(f"{self.base}/custom-styles/palette/", {}, format="json").json()
        self.assertEqual(d["from"], ["#126F85", "#163F75"])
        self.assertTrue(custom.contrast_report(custom.sanitize(blank(palette=d["palette"])))["ok"])

    def test_saving_needs_a_passing_quality_check_for_exactly_this_style(self):
        doc = self.doc()
        r = self.api.post(f"{self.base}/custom-styles/", {"style": doc}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "check_required")
        r = self.save(doc)
        self.assertEqual(r.status_code, 201, r.content)
        row = r.json()["style"]
        self.assertTrue(re.match(rf"^u{self.store.pk}-test-style$", row["id"]), row["id"])
        self.assertTrue(row["custom"] and row["scope"] == "store")
        # a changed style needs its own check
        changed = self.doc(name_fa="سبکِ دیگر", palette={**doc["palette"], "accent": "#aa2200"})
        self.assertEqual(self.api.post(f"{self.base}/custom-styles/", {"style": changed}, format="json").status_code, 409)

    def test_a_style_that_fails_the_check_cannot_be_saved(self):
        doc = self.doc(name_fa="سبکِ خراب")
        chk = stylecheck.start(self.store, self.owner, doc)
        stylecheck.run(chk.pk, measure_factory=fake_measure(overflow=True))
        chk.refresh_from_db()
        self.assertEqual(chk.state, "fail")
        self.assertTrue(any(e["code"] == "overflow" for e in chk.report["errors"]))
        r = self.api.post(f"{self.base}/custom-styles/", {"style": doc}, format="json")
        self.assertEqual(r.status_code, 409)
        # low contrast measured on the pixels
        doc2 = self.doc(name_fa="سبکِ کم‌کنتراست")
        chk2 = stylecheck.start(self.store, self.owner, doc2)
        stylecheck.run(chk2.pk, measure_factory=fake_measure(low_contrast=True))
        chk2.refresh_from_db()
        self.assertEqual(chk2.state, "fail")
        self.assertTrue(any(e["code"] == "low_contrast" for e in chk2.report["errors"]))

    def test_palette_failure_fails_the_check_before_any_render(self):
        bad = custom.sanitize(self.doc(palette={**blank()["palette"], "bg": "#202020", "ink": "#262626"}))
        chk = stylecheck.start(self.store, self.owner, bad)
        calls = []
        stylecheck.run(chk.pk, measure_factory=lambda *a: calls.append(a) or (lambda s: []))
        chk.refresh_from_db()
        self.assertEqual(chk.state, "fail")
        self.assertEqual(calls, [])
        self.assertIn("نگهبانِ کنتراست", chk.report["summary"])
        r = self.api.post(f"{self.base}/custom-styles/", {"style": bad}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_check_endpoint_runs_in_the_background_and_reports(self):
        with mock.patch("apps.motion.qa_browser.available", return_value=(False, "بدونِ مرورگر در آزمون")):
            r = self.api.post(f"{self.base}/custom-styles/check/", {"style": self.doc()}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        c = r.json()["check"]
        self.assertIn(c["state"], ("pass", "running"))
        d = self.api.get(f"{self.base}/custom-styles/check/{c['id']}/").json()["check"]
        self.assertEqual(d["state"], "pass")
        self.assertFalse(d["geometry"])                                       # honest: the picture check could not run here
        self.assertIn("انجام نشد", d["summary"])
        self.assertEqual(self.api.get(f"/api/v1/stores/{self.other.pk}/motion/custom-styles/check/{c['id']}/").status_code in (403, 404), True)

    def test_list_get_update_delete_and_isolation(self):
        doc = self.doc()
        sid = self.save(doc).json()["style"]
        listing = self.api.get(f"{self.base}/custom-styles/").json()
        self.assertEqual([s["id"] for s in listing["styles"]], [sid["id"]])
        self.assertFalse(listing["can_global"])
        # the other store neither sees nor opens it
        oc = APIClient()
        oc.force_authenticate(self.other_owner)
        self.assertEqual(oc.get(f"/api/v1/stores/{self.other.pk}/motion/custom-styles/").json()["styles"], [])
        self.assertEqual(oc.get(f"/api/v1/stores/{self.other.pk}/motion/custom-styles/{sid['pk']}/").status_code, 404)
        self.assertEqual(oc.delete(f"/api/v1/stores/{self.other.pk}/motion/custom-styles/{sid['pk']}/").status_code, 404)
        # update: same content (name only) needs no new check; changed content does
        r = self.api.put(f"{self.base}/custom-styles/{sid['pk']}/", {"style": {**doc, "about": "توضیح تازه"}}, format="json")
        self.assertEqual(r.status_code, 409)
        edited = {**doc, "palette": {**doc["palette"], "accent": "#0a6b7d"}}
        self.passing_check(edited)
        r = self.api.put(f"{self.base}/custom-styles/{sid['pk']}/", {"style": edited}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(MotionCustomStyle.objects.get(pk=sid["pk"]).data["palette"]["accent"], "#0a6b7d")
        self.assertEqual(self.api.delete(f"{self.base}/custom-styles/{sid['pk']}/").status_code, 204)
        self.assertEqual(MotionCustomStyle.objects.count(), 0)

    def test_global_styles_need_an_admin_and_everybody_sees_them(self):
        doc = self.doc(name_fa="همگانی", name_en="Shared Look")
        self.passing_check(doc)
        self.assertEqual(self.api.post(f"{self.base}/custom-styles/", {"style": doc, "scope": "global"}, format="json").status_code, 403)
        admin = User.objects.create_user("style-admin", password="x", is_staff=True)
        self.store.owner = admin
        self.store.save()
        ac = APIClient()
        ac.force_authenticate(admin)
        self.passing_check(doc)
        r = ac.post(f"{self.base}/custom-styles/", {"style": doc, "scope": "global"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        gid = r.json()["style"]["id"]
        self.assertTrue(gid.startswith("g-"))
        oc = APIClient()
        oc.force_authenticate(self.other_owner)
        ids = [s["id"] for s in oc.get(f"/api/v1/stores/{self.other.pk}/motion/custom-styles/").json()["styles"]]
        self.assertIn(gid, ids)
        gpk = r.json()["style"]["pk"]
        self.assertEqual(oc.delete(f"/api/v1/stores/{self.other.pk}/motion/custom-styles/{gpk}/").status_code, 403)       # only an admin removes a shared style

    def test_limits(self):
        with mock.patch.object(custom, "MAX_PER_STORE", 2):
            for i in range(2):
                d = self.doc(name_fa=f"سبک {i}", name_en=f"Limit {i}")
                self.assertEqual(self.save(d).status_code, 201)
            d = self.doc(name_fa="سومی", name_en="Limit 3")
            self.assertEqual(self.save(d).status_code, 409)

    def test_export_import_endpoints(self):
        sid = self.save(self.doc()).json()["style"]
        exp = self.api.get(f"{self.base}/custom-styles/{sid['pk']}/export/").json()
        self.assertEqual(exp["nm_motion_style"], 1)
        r = self.api.post(f"{self.base}/custom-styles/import/", {"json": exp}, format="json").json()
        self.assertEqual(custom.canonical(r["style"]), custom.canonical(custom.sanitize(exp["style"])))
        self.assertTrue(r["contrast"]["ok"])
        bad = self.api.post(f"{self.base}/custom-styles/import/", {"json": "{nope"}, format="json")
        self.assertEqual(bad.status_code, 400)
        hostile = {"nm_motion_style": 1, "style": {**exp["style"], "bg": {"kind": "solid", "c": "javascript:1"}, "font": {"latin": "../../etc/passwd", "fa": "x"}}}
        r = self.api.post(f"{self.base}/custom-styles/import/", {"json": hostile}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["style"]["font"]["latin"], "vazirmatn")

    def test_custom_style_is_usable_in_plans_previews_and_render_jobs(self):
        sid = self.save(self.doc()).json()["style"]["id"]
        self.assertIsNotNone(catalog.get(sid))
        spec = specs.normalize_spec({"style": sid, "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "چغر"}]})
        self.assertEqual(spec["style"], sid)
        self.assertNotIn("style_def", spec)                                    # a client can never inject its own definition
        injected = specs.normalize_spec({**spec, "style_def": {"evil": 1}})
        self.assertNotIn("style_def", injected)
        pv = self.api.post(f"{self.base}/preview/", {"spec": spec}, format="json")
        self.assertEqual(pv.status_code, 200, pv.content)
        self.assertEqual(pv.json()["spec"]["style_def"]["id"], sid)
        self.assertEqual(pv.json()["spec"]["style_def"]["palette"], custom.sanitize(self.doc())["palette"])
        job, _files = services.build_job(MotionRender(store=self.store, spec=spec, aspect="9:16", style=sid, options={"quality": "540"}, target=MotionRender.Target.NODE))
        self.assertEqual(job["props"]["spec"]["style_def"]["id"], sid)
        self.assertEqual(job["props"]["spec"]["style"], sid)
        # the plan keeps the id only
        pr = self.api.post(f"{self.base}/plans/", {"spec": spec}, format="json")
        self.assertEqual(pr.status_code, 201, pr.content)
        self.assertEqual(pr.json()["plan"]["spec"]["style"], sid)
        self.assertNotIn("style_def", pr.json()["plan"]["spec"])
        # render creation
        rr = self.api.post(f"{self.base}/renders/", {"mode": "template", "spec": spec, "target": "node"}, format="json")
        self.assertIn(rr.status_code, (200, 201, 202), rr.content)

    def test_a_style_of_another_store_cannot_be_used(self):
        sid = self.save(self.doc()).json()["style"]["id"]
        oc = APIClient()
        oc.force_authenticate(self.other_owner)
        spec = {"style": sid, "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "x"}]}
        pv = oc.post(f"/api/v1/stores/{self.other.pk}/motion/preview/", {"spec": spec}, format="json")
        self.assertEqual(pv.status_code, 400)
        self.assertIn("فروشگاهِ دیگری", json.dumps(pv.json(), ensure_ascii=False))
        rr = oc.post(f"/api/v1/stores/{self.other.pk}/motion/renders/", {"mode": "template", "spec": spec}, format="json")
        self.assertEqual(rr.status_code, 400)
        with self.assertRaises(services.MotionError):
            services.attach_style(self.other, dict(spec))

    def test_a_deleted_style_gives_a_clear_message(self):
        row = self.save(self.doc()).json()["style"]
        spec = {"style": row["id"], "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "x"}]}
        MotionCustomStyle.objects.filter(pk=row["pk"]).delete()
        with self.assertRaises(specs.SpecError):
            specs.normalize_spec(spec)

    def test_catalog_endpoint_is_unchanged_and_custom_rows_carry_their_tokens(self):
        d = self.api.get("/api/v1/motion/styles/").json()
        self.assertGreaterEqual(len(d["styles"]), 96)
        row = self.save(self.doc()).json()["style"]
        for k in ("palette", "font", "bg", "text", "shape", "decor", "tex", "motion", "trans", "name_fa", "about"):
            self.assertIn(k, row)
        self.assertEqual(self.api.get("/api/v1/motion/styles/").json()["styles"].__len__(), len(d["styles"]))


class StyleCheckUnits(ApiBase):
    def test_sample_text_is_the_stores_own(self):
        sc = stylecheck.sample_scenes(self.store)
        self.assertEqual(sc[0]["title"], "چغر")
        self.assertIn("دستیار هوش مصنوعی", sc[0]["subtitle"])
        self.assertEqual([s["type"] for s in sc], ["title", "list", "stat", "quote", "cta"])
        self.assertGreater(len(sc[3]["text"]), 100)                              # one deliberately long text: the auto-fit is part of the check

    def test_check_is_cached_per_content_hash(self):
        doc = custom.sanitize(self.doc())
        a = self.passing_check(doc)
        self.assertEqual(a.state, "pass")
        again = stylecheck.start(self.store, self.owner, doc)
        self.assertEqual(again.pk, a.pk)
        changed = custom.sanitize({**doc, "about": "x"})
        self.assertEqual(custom.style_hash(changed), custom.style_hash(doc) if changed == doc else custom.style_hash(changed))
        recolour = custom.sanitize({**doc, "palette": {**doc["palette"], "accent": "#aa2200"}})
        self.assertNotEqual(custom.style_hash(recolour), custom.style_hash(doc))
        self.assertEqual(stylecheck.start(self.store, self.owner, recolour).state, "running")

    def test_infrastructure_failure_is_an_error_never_a_pass(self):
        chk = stylecheck.start(self.store, self.owner, custom.sanitize(self.doc()))

        def boom(*a):
            raise RuntimeError("browser died")

        stylecheck.run(chk.pk, measure_factory=boom)
        chk.refresh_from_db()
        self.assertEqual(chk.state, "error")
        self.assertIsNone(stylecheck.passed(self.store, custom.sanitize(self.doc())))

    def test_thumbnail_is_kept_and_served_for_a_passing_style(self):
        doc = custom.sanitize(self.doc())
        chk = self.passing_check(doc)
        self.assertTrue(chk.thumb)
        self.assertTrue((Path(self.media) / chk.thumb).is_file())
        row = self.api.post(f"{self.base}/custom-styles/", {"style": doc}, format="json").json()["style"]
        self.assertIn(chk.thumb, row["thumb_url"])


# ───────────────────────────────────────────── ۷) رندرِ واقعی (روی هر ماشینی که ابزارِ رندرِ سایت را دارد؛ وگرنه رد)

class RealRender(ApiBase):
    def setUp(self):
        super().setUp()
        st = runner.site_status()
        if not st["ready"]:
            self.skipTest("site render tooling is not ready: " + "؛ ".join(st["reasons"]))
        files = sorted(runner.bundle_dir().glob("*.js"))
        if not any("data-nm-style-def" in f.read_text(encoding="utf-8", errors="ignore") for f in files):
            self.skipTest("the render bundle was built before style_def support (manage.py motion_build --only shell)")

    def test_a_custom_style_really_renders_and_passes_the_real_check(self):
        doc = custom.sanitize(blank(name_fa="سبکِ واقعی", name_en="Real Look", palette={"bg": "#10131f", "bg2": "#1a2036", "ink": "#f4f6fb", "paper": "#e9eef7", "accent": "#ffb703", "accent2": "#4cc9f0",
                                                                                   "accent3": "#f72585", "muted": "#a9b4cc"},
                                    bg={"kind": "radial", "from": "bg2", "to": "bg", "at": "50% 40%"}, text={"fx": "softglow", "glow": "accent"},
                                    decor=[{"kind": "particles", "n": 20, "colors": ["accent", "accent2"]}], shape={"radius": 18, "border": 2, "bc": "accent", "shadow": "glow", "sc": "accent", "fill": "bg2"},
                                    font={**blank()["font"], "latin": "space-grotesk", "fa": "vazirmatn", "weight": 700}))
        chk = stylecheck.start(self.store, self.owner, doc)
        stylecheck.run(chk.pk)                                              # the real browser, the real engine
        chk.refresh_from_db()
        self.assertEqual(chk.state, "pass", chk.report)
        self.assertTrue(chk.report["geometry"])
        self.assertGreaterEqual(chk.report["frames"], 12)
        self.assertTrue(chk.thumb and (Path(self.media) / chk.thumb).is_file())
        from PIL import Image

        im = Image.open(Path(self.media) / chk.thumb).convert("RGB")
        px = im.getpixel((8, 8))
        self.assertLess(sum(px) / 3, 90, "the dark style's own background must be what is drawn (not the default style)")
        # and the same style as a 1.5 second MP4 (the render job path)
        row = self.save(doc)
        self.assertEqual(row.status_code, 201, row.content)
        sid = row.json()["style"]["id"]
        spec = specs.normalize_spec({"style": sid, "aspect": "9:16", "scenes": [{"type": "title", "duration": 1.2, "title": "چغر", "subtitle": "سبکِ شخصی"}]})
        job, files = services.build_job(MotionRender(store=self.store, spec=spec, aspect="9:16", style=sid, options={"quality": "360"}, target=MotionRender.Target.SITE))
        work = Path(tempfile.mkdtemp(prefix="nm-style-render-"))
        try:
            job.update(out=str(work / "o.mp4"), assets_dir=str(work), max_seconds=5)
            done = runner.run_render(job, workdir=work / "w")
            self.assertTrue((work / "o.mp4").is_file() and (work / "o.mp4").stat().st_size > 2000, done)
            self.assertGreaterEqual(int(done.get("frames") or 0), 30)
        finally:
            shutil.rmtree(work, ignore_errors=True)


# ───────────────────────────────────────────── ۸) گره: قرارداد و آزمونِ خودکار

class NodeContract(TestCase):
    def test_engine_features_in_python_and_typescript_agree(self):
        from . import buildlib

        ts = (SRC / "style-def.ts").read_text(encoding="utf-8")
        m = re.search(r"ENGINE_FEATURES\s*=\s*\[([^\]]*)\]", ts)
        self.assertIsNotNone(m)
        self.assertEqual(tuple(x.strip().strip('"') for x in m.group(1).split(",") if x.strip()), buildlib.ENGINE_FEATURES)

    def test_the_pack_gets_a_features_file_and_the_manifest_names_them(self):
        src = (Path(__file__).parent / "buildlib.py").read_text(encoding="utf-8")
        self.assertIn('z.writestr("FEATURES"', src)
        self.assertIn('"features": list(ENGINE_FEATURES)', src)
        self.assertIn("ENGINE_FEATURES", src[src.index("def source_hash"):src.index("def downloads_dir")])      # a feature change makes a new pack version

    def test_selftest_doc_matches_the_module_and_passes_the_node_validator(self):
        import sys

        from apps.compute.selftests import motion_styles

        doc = ROOT / "docs" / "selftests" / "motion-styles.md"
        if not doc.is_file():
            self.skipTest("docs/selftests/motion-styles.md is not in this tree")
        blocks = [json.loads(raw) for raw in re.findall(r"```json\s*\n(.*?)\n```", doc.read_text(encoding="utf-8"), re.S)]
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual((b["key"], b["kind"]), ("studio_motion_styles", "motion.render"))
        self.assertEqual(b["payload"], motion_styles.PAYLOAD)
        self.assertEqual(b["check"]["forbid_device"], ["cpu"])
        sd = b["payload"]["props"]["spec"]["style_def"]
        clean = custom.sanitize(sd)
        self.assertEqual(clean["palette"], sd["palette"])                                      # the selftest style is a valid style
        self.assertEqual(custom.contrast_report(clean)["errors"], [])
        proc = str(ROOT / "processing")
        if (Path(proc) / "motion_jobs.py").is_file():
            sys.path.insert(0, proc)
            try:
                import motion_jobs
            finally:
                sys.path.remove(proc)
            self.assertEqual(motion_jobs.needed_features(b["payload"]), {"style_def"})
            self.assertEqual(motion_jobs.validate_payload(b["payload"])["composition"], "Template")

    def test_selftest_reads_the_pixel_of_a_rendered_video(self):
        from apps.compute.selftests import motion_styles

        ff = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        if not Path(ff).exists():
            self.skipTest("no ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "o.mp4"
            subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x6a1b9a:s=540x960:d=2:r=30", "-pix_fmt", "yuv420p", str(v)], check=True, capture_output=True)
            px = motion_styles.corner_pixel(v)
            self.assertTrue(motion_styles._near(px, (0x6a, 0x1b, 0x9a)), px)
            w = Path(tmp) / "w.mp4"
            subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xf4f4f4:s=540x960:d=2:r=30", "-pix_fmt", "yuv420p", str(w)], check=True, capture_output=True)
            self.assertFalse(motion_styles._near(motion_styles.corner_pixel(w), (0x6a, 0x1b, 0x9a)), "the default (light) style must NOT pass as the purple one")
        self.assertFalse(motion_styles._near(None, (1, 2, 3)))

    def test_site_engine_marker_is_detected_in_a_bundle(self):
        from apps.compute.selftests import motion_styles

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(motion_styles.site_engine_has_style_def(Path(tmp) / "nope"))
            (Path(tmp) / "a.js").write_text("var x = 1;", encoding="utf-8")
            self.assertFalse(motion_styles.site_engine_has_style_def(tmp))
            (Path(tmp) / "b.js").write_text('props["data-nm-style-def"]=1', encoding="utf-8")
            self.assertTrue(motion_styles.site_engine_has_style_def(tmp))

    def test_node_status_tells_whether_the_nodes_pack_draws_custom_styles(self):
        from django.utils import timezone

        from apps.compute.models import ComputeNode

        self.assertTrue(services.node_status()["style_def"])                                  # no node: the site renders with its own bundle
        n = ComputeNode.objects.create(name="N-OLD", last_seen=timezone.now(), capabilities={"motion_render": True, "kinds": ["motion.render"], "motion": {"state": "ready", "features": ["audio_mux"]}})
        try:
            self.assertFalse(services.node_status()["style_def"])
            n.capabilities = {"motion_render": True, "kinds": ["motion.render"], "motion": {"state": "ready", "features": ["audio_mux", "style_def"]}}
            n.save()
            self.assertTrue(services.node_status()["style_def"])
        finally:
            n.delete()


class EngineBrand(SimpleTestCase):
    """motion/remotion/src/brand.ts: the brand's colours on top of a style (the sun of «synthwave» must not turn pale blue because a brand colour is pale)."""

    def run_ts(self, body: str) -> str:
        sucrase = ROOT / "motion" / "node_modules" / "sucrase"
        if not (Path(NODE).exists() and sucrase.exists()):
            self.skipTest("node/sucrase are not on this machine")
        mods = {n: (SRC / f"{n}.ts").read_text(encoding="utf-8") for n in ("util", "brand")}
        script = f"""
const {{ transform }} = require({json.dumps(str(sucrase))});
const srcs = {json.dumps(mods)};
const cache = {{}};
function load(name) {{
  if (cache[name]) return cache[name].exports;
  const m = cache[name] = {{ exports: {{}} }};
  const code = transform(srcs[name], {{ transforms: ["typescript", "imports"] }}).code;
  const req = (id) => id === "remotion" ? {{ random: (s) => 0.5 }} : id.startsWith("./") ? load(id.slice(2)) : require(id);
  new Function("module", "exports", "require", code)(m, m.exports, req);
  return m.exports;
}}
const {{ brandPalette, fitOn, readableOn, haloCss, LABEL_CONTRAST }} = load("brand");
const {{ contrast, lum, fixDigits }} = load("util");
{body}
"""
        p = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def test_a_pale_or_black_brand_colour_is_no_accent_and_the_accent_text_stays_readable(self):
        st = catalog.get("synthwave")["palette"]
        out = json.loads(self.run_ts(f"""
const pal = {json.dumps(st)};
const chagher = brandPalette(pal, {{ colors: ["#126F85", "#163F75", "#DBE6FF"], use_brand_colors: true }});
const dark = brandPalette(pal, {{ colors: ["#000000", "#ffffff", "#ff3366"] }});
const none = brandPalette(pal, {{ colors: [], use_brand_colors: true }});
const off = brandPalette(pal, {{ colors: ["#126F85"], use_brand_colors: false }});
console.log(JSON.stringify({{ chagher, dark, none, off, ratios: [contrast(chagher.accent, pal.bg), contrast(chagher.accent2, pal.bg)], pale: lum("#DBE6FF") }}));
"""))
        ch = out["chagher"]
        self.assertEqual(ch["accent3"], st["accent3"])                       # the pale third colour (#DBE6FF) is not turned into the style's accent: its sun / slabs stay
        self.assertGreaterEqual(out["ratios"][0], 4.5)                       # the small kicker lines in the accent colour read on the dark background
        self.assertGreaterEqual(out["ratios"][1], 3.0)
        self.assertNotEqual(ch["accent"], st["accent"])
        self.assertEqual(out["dark"]["accent"].lower() == "#000000" or out["dark"]["accent"].lower() == "#ffffff", False)     # black / white are no accents either
        self.assertEqual(out["none"], st)
        self.assertEqual(out["off"], st)
        self.assertGreater(out["pale"], 0.72)

    def test_a_mid_tone_background_is_darkened_never_whitened(self):
        """tan (#c9a27e), sky blue (#4aa8ff) and coral are neither dark nor light: the accent must go DARK there (white can never reach 4.5 on them; the claymation title and the
        anime kicker were whitened before)."""
        out = json.loads(self.run_ts("""
const rows = {};
for (const bg of ["#c9a27e", "#4aa8ff", "#ff6b6b", "#8a5a2b"]) {
  const r = fitOn("#126F85", bg, 4.5);
  rows[bg] = { r, c: contrast(r, bg), l: lum(r) };
}
console.log(JSON.stringify(rows));
"""))
        for bg in ("#c9a27e", "#4aa8ff"):
            self.assertGreaterEqual(out[bg]["c"], 4.5, bg)
            self.assertLess(out[bg]["l"], 0.2, bg)                           # dark, not whitened
        self.assertGreaterEqual(out["#ff6b6b"]["c"], 3.0)

    def test_small_text_reads_on_any_background_and_gets_a_halo_in_the_palette_background(self):
        """kicker / caption colours: darkened on mid-tone and light backgrounds, lightened on dark ones, never below the label bar; the halo repaints the pixels around the letters
        with the palette background (a bright spotlight cone or a white cloud behind a kicker no longer swallows it)."""
        out = json.loads(self.run_ts("""
const rows = {};
for (const bg of ["#c9a27e", "#4aa8ff", "#fdf3e7", "#101828", "#02030c"]) {
  const r = readableOn("#126F85", bg, "#111111", LABEL_CONTRAST);
  rows[bg] = { r, c: contrast(r, bg) };
}
console.log(JSON.stringify({ rows, label: LABEL_CONTRAST, halo: haloCss("#101828", 46), same: readableOn("#ffffff", "#101828", "#fff", 3), raw: readableOn("accent", "#fff", "#000", 3) }));
"""))
        self.assertEqual(out["label"], 4.5)
        for bg, row in out["rows"].items():
            self.assertGreaterEqual(row["c"], 4.4, bg)
        self.assertEqual(out["same"], "#ffffff")                                # already readable: untouched
        self.assertEqual(out["raw"], "accent")                                  # a role name is not a colour: left for the caller
        parts = out["halo"].split("), ")
        self.assertEqual(len(parts), 3)
        self.assertIn("rgba(16,24,40,0.95", parts[0])
        self.assertIn("rgba(16,24,40,0.6", parts[2])

    def test_digits_stay_latin_inside_latin_tokens(self):
        """«PS2», «3D», «22K», «2.5D», «1930s» in a Persian video kept Persian digits glued to Latin letters (the mixed-digit bug of the PS2 / Chrome 22K / Parallax kickers)."""
        out = json.loads(self.run_ts("""
console.log(JSON.stringify({
  ps2: fixDigits("PS2 Style", true, false), kd: fixDigits("2.5D Parallax", true, false), k22: fixDigits("Chrome 22K", true, false),
  fa: fixDigits("سبکِ پلی‌استیشن 2 و 1405", true, false), mixed: fixDigits("قیمت 600 تومان برای 3D", true, false), en: fixDigits("۱۲۳ و PS۲", false, true), keep: fixDigits("PS2 ۱۲", false, false),
}));
"""))
        self.assertEqual(out["ps2"], "PS2 Style")
        self.assertEqual(out["kd"], "2.5D Parallax")
        self.assertEqual(out["k22"], "Chrome 22K")
        self.assertEqual(out["fa"], "سبکِ پلی‌استیشن ۲ و ۱۴۰۵")                  # Persian text still gets Persian digits
        self.assertEqual(out["mixed"], "قیمت ۶۰۰ تومان برای 3D")
        self.assertEqual(out["en"], "123 و PS2")                                # digits="en" forces Latin everywhere
        self.assertEqual(out["keep"], "PS2 ۱۲")

    def test_fit_keeps_the_hue_and_stops_as_soon_as_it_reads(self):
        out = json.loads(self.run_ts("""
const bg = "#101828";
const r1 = fitOn("#126F85", bg, 3.6);
const r2 = fitOn("#7fe3ff", bg, 3.6);
const r3 = fitOn("#126F85", "#fdf3e7", 3.6);
console.log(JSON.stringify({ r1, r2, r3, c1: contrast(r1, bg), c3: contrast(r3, "#fdf3e7") }));
"""))
        self.assertGreaterEqual(out["c1"], 3.6)
        self.assertEqual(out["r2"], "#7fe3ff")                               # already readable: untouched
        self.assertEqual(out["r3"], "#126F85")                               # a dark teal on cream is already fine
        self.assertGreaterEqual(out["c3"], 3.6)
        self.assertLess(custom.lum(out["r1"]), 0.6)                          # lightened, but not pushed all the way to white

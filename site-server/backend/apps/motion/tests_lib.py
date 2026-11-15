"""کتابخانهٔ قطعه‌ها و ثابت‌های حرکت: فهرستِ پایتون با موتورِ Remotion یکی است، هر نمونه معتبر است، منحنی/فنر/دوربین/گذار هم‌نام‌اند، خطِ زمانِ پایتون با TS یکی است."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from . import catalog, components, motionlib, runner, specs, timeline

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "motion" / "remotion" / "src"


def ts_keys(file: str, block: str) -> set:
    """کلیدهای `export const <block> ... = { a: A, b: B }` در یک فایلِ TS."""
    text = (SRC / file).read_text(encoding="utf-8")
    m = re.search(r"export const %s[^=]*=\s*\{(.*?)\n?\};?" % re.escape(block), text, re.S)
    assert m, f"{block} not found in {file}"
    return set(re.findall(r"\b([a-z][a-z0-9_]*)\s*:", m.group(1)))


class Registry(SimpleTestCase):
    def test_python_registry_equals_the_remotion_registry(self):
        ts = ts_keys("scenes.tsx", "SCENES") | ts_keys("comp-data.tsx", "DATA_COMPONENTS") | ts_keys("comp-text.tsx", "TEXT_COMPONENTS")
        self.assertEqual(set(components.COMPONENTS), ts, "components.py and motion/remotion/src (scenes/comp-data/comp-text) must list the same ids")

    def test_overlays_equal_the_remotion_overlay_bodies(self):
        self.assertEqual(set(components.OVERLAY_IDS), ts_keys("comp-text.tsx", "OVERLAY_BODIES"))

    def test_at_least_twenty_pieces_beyond_the_nine_scene_types(self):
        extra = set(components.COMPONENTS) - set(components.CLASSIC)
        self.assertGreaterEqual(len(extra), 20)
        for needed in ("kinetic_title", "lower_third", "bar_chart", "line_chart", "donut", "counter", "progress_ring", "price_card", "comparison_table", "before_after",
                       "checklist", "steps", "icon_grid", "testimonial", "captions", "sticker", "social_cta"):
            self.assertIn(needed, components.COMPONENTS)

    def test_every_sample_validates_and_keeps_its_content(self):
        for cid, c in components.COMPONENTS.items():
            out = specs.normalize_scene(dict(c["sample"]), 0)
            self.assertEqual(out["type"], cid)
            for key in c["need"][:1]:
                self.assertTrue(out.get(key), f"{cid}: {key} lost")

    def test_every_text_field_has_a_length_cap_and_lists_have_item_caps(self):
        def walk(cid, fields):
            for n, f in fields.items():
                k = f["kind"]
                self.assertIn(k, ("str", "num", "int", "bool", "enum", "ref", "strs", "objs"), f"{cid}.{n}")
                if k == "str":
                    self.assertGreater(f["max"], 0)
                if k == "strs":
                    self.assertTrue(f["max_items"] and f["item_max"])
                if k == "objs":
                    self.assertTrue(f["max_items"])
                    walk(cid, f["fields"])
        for cid, c in components.COMPONENTS.items():
            walk(cid, c["fields"])

    def test_icon_set_is_permissive_and_recorded(self):
        self.assertGreaterEqual(len(components.ICON_NAMES), 60)
        lic = (ROOT / "motion" / "remotion" / "ICONS-LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("ISC License", lic)
        for c in components.COMPONENTS.values():
            for f in c["fields"].values():
                if f["kind"] == "objs":
                    for sub in f["fields"].values():
                        if sub["kind"] == "enum" and "dumbbell" in sub["choices"]:
                            self.assertTrue(set(sub["choices"]) <= set(components.ICON_NAMES))

    def test_emoji_set_is_vector_art_with_its_attribution_recorded(self):
        self.assertGreaterEqual(len(components.EMOJI_NAMES), 50)
        self.assertEqual(set(components.EMOJI_NAMES), set(components.EMOJI_LABELS), "every emoji has a Persian label")
        lic = (ROOT / "motion" / "remotion" / "ICONS-LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("CC-BY 4.0", lic)
        self.assertIn("Twemoji", lic)
        data = json.loads((SRC / "emoji.generated.json").read_text(encoding="utf-8"))
        self.assertIn("CC-BY", data["license"])
        for name, inner in data["emoji"].items():
            self.assertTrue(inner.startswith("<"), name)
            self.assertNotIn("<script", inner.lower(), name)
            self.assertNotIn("href=", inner.lower(), name)                    # no external references: the picture is self-contained

    def test_sticker_accepts_a_known_emoji_and_drops_an_unknown_one(self):
        ok = specs.normalize_scene({"type": "sticker", "duration": 3, "kind": "emoji", "emoji": "fire"}, 0)
        self.assertEqual((ok["kind"], ok["emoji"]), ("emoji", "fire"))
        bad = specs.normalize_scene({"type": "sticker", "duration": 3, "kind": "emoji", "emoji": "not-an-emoji", "text": "جدید"}, 0)
        self.assertNotIn("emoji", bad)

    def test_unknown_icon_is_dropped_not_rendered_broken(self):
        out = specs.normalize_scene({"type": "icon_grid", "duration": 5, "title": "t", "items": [{"icon": "evil", "label": "الف"}, {"icon": "heart", "label": "ب"}]}, 0)
        self.assertEqual(out["items"][0].get("icon"), None)
        self.assertEqual(out["items"][1]["icon"], "heart")

    def test_public_list_is_json(self):
        json.dumps(components.public_list())
        self.assertEqual({c["group"] for c in components.public_list()}, {"scene", "data", "text"})


class Presets(SimpleTestCase):
    def test_ease_and_spring_names_match_presets_ts(self):
        text = (SRC / "presets.ts").read_text(encoding="utf-8")
        eases = set(re.findall(r'^\s+"?([a-z-]+)"?:\s*(?:bz|Easing|\()', text.split("export const SPRINGS")[0], re.M))
        springs = set(re.findall(r'^\s+"?([a-z-]+)"?:\s*\[', text.split("export const SPRINGS")[1], re.M))
        self.assertEqual(set(motionlib.EASES), eases)
        self.assertEqual(set(motionlib.SPRINGS), springs)

    def test_camera_exit_transition_names_match_the_engine(self):
        text = (SRC / "presets.ts").read_text(encoding="utf-8")
        cams = set(re.findall(r'"([a-z-]+)"', re.search(r"CAMERA_MOVES = \[(.*?)\]", text, re.S).group(1)))
        exits = set(re.findall(r'"([a-z-]+)"', re.search(r"EXIT_KINDS = \[(.*?)\]", text, re.S).group(1)))
        self.assertEqual(set(motionlib.CAMERA_MOVES), cams)
        self.assertEqual(set(motionlib.EXIT_KINDS), exits)
        anim = (SRC / "anim.ts").read_text(encoding="utf-8")
        trans_block = anim.split("export function transitionCss")[1]
        cases = set(re.findall(r'case "([a-z-]+)"', trans_block))
        self.assertTrue(set(motionlib.TRANSITIONS) <= cases, set(motionlib.TRANSITIONS) - cases)
        for t in motionlib.TRANSITION_PACK:          # wipe, push, zoom, ink, glitch, iris: the owner's pack
            self.assertIn(t, motionlib.TRANSITIONS)

    def test_enter_kinds_exist_in_the_engine(self):
        anim = (SRC / "anim.ts").read_text(encoding="utf-8")
        enter_block = anim.split("export function enterCss")[1].split("export function cameraCss")[0]
        cases = set(re.findall(r'case "([a-z]+)"', enter_block))
        self.assertTrue(set(catalog.ENTER_KINDS) <= cases | {"fade"}, set(catalog.ENTER_KINDS) - cases)

    def test_platform_safe_zones(self):
        for pid in ("reels", "story", "tiktok", "shorts"):
            z = motionlib.platform_safe(pid)
            self.assertGreaterEqual(z["bottom"], 0.14)
            self.assertGreater(z["top"], 0.0)
        self.assertEqual(motionlib.platform_safe(""), {"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0})


NODE = shutil.which("node") or "/usr/local/bin/node"


class TimelineParity(SimpleTestCase):
    """computeTimeline (TS) و timeline.compute (پایتون) روی چند طرح یک جواب می‌دهند."""

    CASES = [
        {"style": "flat-vector", "fps": 30, "scenes": [{"duration": 3}, {"duration": 3}]},
        {"style": "flat-vector", "fps": 30, "transition": "cut", "scenes": [{"duration": 3}, {"duration": 2.5}, {"duration": 4}]},
        {"style": "pixel-art", "fps": 24, "scenes": [{"duration": 1}, {"duration": 7.3, "transition": "wipe"}, {"duration": 2}, {"duration": 3.33}]},
        {"style": "persian-tile", "fps": 60, "scenes": [{"duration": 4.55}, {"duration": 1.01, "transition": "iris"}, {"duration": 12}]},
        {"style": "flat-vector", "fps": 25, "scenes": [{"duration": 30}]},
    ]

    def test_python_equals_typescript(self):
        sucrase = ROOT / "motion" / "node_modules" / "sucrase"
        if not (Path(NODE).exists() and sucrase.exists()):
            self.skipTest("node/sucrase are not on this machine")
        src = (SRC / "timeline.ts").read_text(encoding="utf-8")
        js = f"""
const {{ transform }} = require({json.dumps(str(sucrase))});
const code = transform({json.dumps(src)}, {{ transforms: ["typescript", "imports"] }}).code;
const m = {{ exports: {{}} }}; new Function("module", "exports", "require", code)(m, m.exports, require);
const styles = {json.dumps({s: {"trans": {"kind": catalog.get(s)["trans"]["kind"], "frames": catalog.get(s)["trans"]["frames"]}} for s in ("flat-vector", "pixel-art", "persian-tile")})};
const cases = {json.dumps(self.CASES)};
console.log(JSON.stringify(cases.map((c) => m.exports.computeTimeline(c, styles[c.style], c.fps))));
"""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.cjs"
            f.write_text(js, encoding="utf-8")
            out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60, cwd=str(ROOT / "motion"))
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        for case, ts in zip(self.CASES, got):
            py = timeline.compute(case)
            for k in ("frames", "starts", "tfs", "kinds", "total"):
                self.assertEqual(py[k], ts[k], f"{k} differs for {case}")

    def test_total_matches_specs_total_seconds(self):
        spec = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "a"}, {"type": "cta", "duration": 3, "title": "b"}]})
        self.assertAlmostEqual(spec["total_s"], timeline.total_seconds(spec), places=2)

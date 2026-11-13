"""spec (پارامترهای ترکیب) و اسکنرِ امنیتیِ کد: اعتبارسنجی، حدها و رد کردنِ هر چیزِ خطرناک."""
from django.test import SimpleTestCase

from . import ai, catalog, safety, samples, specs


def good_spec(**kw):
    s = {"style": "flat-vector", "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "سلام", "subtitle": "دنیا"}]}
    s.update(kw)
    return s


class SpecValidation(SimpleTestCase):
    def test_every_template_of_every_style_validates(self):
        for tpl in specs.TEMPLATES:
            for st in ("flat-vector", "pixel-art", "persian-tile"):
                for asp in specs.ASPECTS:
                    out = specs.normalize_spec(specs.sample_spec(st, tpl["id"], asp))
                    self.assertTrue(out["scenes"])
                    self.assertGreater(out["total_s"], 0)

    def test_unknown_style_aspect_scene_rejected_in_persian(self):
        for bad, frag in ((good_spec(style="nope"), "سبک"), (good_spec(aspect="3:2"), "نسبت"), (good_spec(scenes=[]), "صحنه"),
                          (good_spec(scenes=[{"type": "evil"}]), "نوعِ صحنه"), ("x", "معتبر"),
                          (good_spec(scenes=[{"type": "title", "duration": 3}]), "title")):
            with self.assertRaises(specs.SpecError) as cm:
                specs.normalize_spec(bad)
            self.assertIn(frag, str(cm.exception))

    def test_limits(self):
        many = [{"type": "title", "duration": 2, "title": f"s{i}"} for i in range(specs.MAX_SCENES + 1)]
        with self.assertRaises(specs.SpecError):
            specs.normalize_spec(good_spec(scenes=many))
        long_ = [{"type": "title", "duration": 30, "title": f"s{i}"} for i in range(4)]       # ~118 s: fine on the node (<=120), too long for the site (<=60)
        with self.assertRaises(specs.SpecError):
            specs.normalize_spec(good_spec(scenes=long_), max_total=specs.MAX_TOTAL_S_SITE)
        specs.normalize_spec(good_spec(scenes=long_), max_total=specs.MAX_TOTAL_S_NODE)

    def test_text_is_clipped_cleaned_and_unknown_keys_dropped(self):
        sc = {"type": "title", "duration": 99, "title": "ا" * 500 + "‮", "evil": "<script>", "subtitle": 12}
        out = specs.normalize_spec(good_spec(scenes=[sc]))["scenes"][0]
        self.assertEqual(len(out["title"]), 140)
        self.assertNotIn("‮", out["title"])
        self.assertNotIn("evil", out)
        self.assertEqual(out["duration"], 30)
        self.assertEqual(out["subtitle"], "12")

    def test_lists_are_capped(self):
        out = specs.normalize_spec(good_spec(scenes=[{"type": "list", "duration": 5, "title": "t", "items": [f"i{i}" for i in range(20)]}]))
        self.assertEqual(len(out["scenes"][0]["items"]), 6)

    def test_image_refs_only_from_the_store(self):
        ok = good_spec(scenes=[{"type": "product", "duration": 4, "name": "p", "image": "pimg:12"}], brand={"logo": "store-logo", "colors": ["#126F85", "bad", "163F75"]})
        out = specs.normalize_spec(ok)
        self.assertEqual(out["scenes"][0]["image"], "pimg:12")
        self.assertEqual(out["brand"]["colors"], ["#126F85", "#163F75"])
        self.assertEqual(specs.asset_refs(out), ["store-logo", "pimg:12"])
        for bad in ("http://x.com/a.png", "/etc/passwd", "../x", "upload:abc", "file:///c/x.png"):
            with self.assertRaises(specs.SpecError):
                specs.normalize_spec(good_spec(scenes=[{"type": "product", "duration": 4, "name": "p", "image": bad}]))

    def test_transition_override_must_be_known(self):
        self.assertEqual(specs.normalize_spec(good_spec(transition="wipe"))["transition"], "wipe")
        with self.assertRaises(specs.SpecError):
            specs.normalize_spec(good_spec(transition="exec"))

    def test_total_accounts_for_transition_overlap(self):
        two = good_spec(style="flat-vector", scenes=[{"type": "title", "duration": 3, "title": "a"}, {"type": "cta", "duration": 3, "title": "b"}])
        t = specs.normalize_spec(two)["total_s"]
        frames = catalog.get("flat-vector")["trans"]["frames"]
        self.assertAlmostEqual(t, 6 - frames / 30, places=1)
        cut = specs.normalize_spec({**two, "transition": "cut"})["total_s"]
        self.assertEqual(cut, 6)


class RulesFallback(SimpleTestCase):
    def test_rules_scenes_make_a_valid_spec(self):
        sc = ai.rules_scenes("با چغر برنامهٔ ورزشی بساز. ثبت‌نام در یک دقیقه. خرید توکن. ساخت برنامه. همین حالا شروع کن")
        out = specs.normalize_spec(good_spec(scenes=sc))
        self.assertEqual(out["scenes"][0]["type"], "title")
        self.assertEqual(out["scenes"][-1]["type"], "cta")
        self.assertTrue(any(s["type"] == "list" for s in out["scenes"]))


GOOD = samples.HELLO


class CodeScanner(SimpleTestCase):
    def test_all_samples_pass(self):
        for s in samples.SAMPLES:
            safety.scan(s["code"])

    def test_dangerous_code_is_refused_with_a_reason(self):
        cases = [
            ('fetch("https://x.com")', "fetch"), ('const a = window.location.href', "window"), ('import fs from "fs"', "fs"),
            ('eval("1+1")', "eval"), ('const u = "https://evil.com/a.png"', "اینترنتی"), ('const u = "//evil.com/a.png"', "اینترنتی"),
            ('const x = `${fetch("a")}`', "fetch"), ('const F = (() => {}).constructor("return 1")', "constructor"),
            ('const z = <iframe src="a" />', "iframe"), ('const m = import("x")', "import"), ('document.cookie', "cookie"),
            ('new Function("a")', "Function"), ('x = require("fs")', "require"), ('const w = globalThis', "globalThis"),
            ('navigator.sendBeacon("a")', "sendBeacon"), ('new WebSocket("ws://a")', "WebSocket"), ('const w = new Worker("a.js")', "Worker"),
            ('localStorage.setItem("a","b")', "localStorage"), ('const s = <div dangerouslySetInnerHTML={{__html: "x"}} />', "HTML"),
            ('import "child_process"', "child_process"), ('export * from "fs"', "fs"), ('const x = process.env', "process"),
            ('const q = "url(http://a.com/x.png)"', "اینترنتی"),
        ]
        for snippet, frag in cases:
            with self.assertRaises(safety.UnsafeCode, msg=snippet) as cm:
                safety.scan(GOOD + "\n" + snippet)
            self.assertIn(frag, str(cm.exception), snippet)

    def test_harmless_lookalikes_are_allowed(self):
        safety.scan(GOOD + '\nconst style = { top: 10, left: 20 };\nconst label = "fetch the data (just text)";\n// fetch window eval in a comment\n')

    def test_size_and_empty(self):
        with self.assertRaises(safety.UnsafeCode):
            safety.scan("")
        with self.assertRaises(safety.UnsafeCode):
            safety.scan(GOOD + "\n// " + "x" * safety.MAX_CODE_BYTES)

    def test_template_literals_are_scanned_as_code_inside_expressions(self):
        for bad in ('const a = `x ${window.top} y`;', 'const a = `x ${`nested ${fetch("a")}`} y`;'):
            with self.assertRaises(safety.UnsafeCode):
                safety.scan(GOOD + "\n" + bad)
        safety.scan(GOOD + '\nconst a = `fetch ${1 + 1} window`;\n')


class ScaleIsExact(SimpleTestCase):
    """regression: scale 0.3333 gave a 359.964 px tall video and Remotion refused it ("height must be an integer")."""

    def test_every_quality_of_every_aspect_gives_whole_pixels(self):
        from . import runner

        for aspect, (w, h) in specs.ASPECTS.items():
            for quality, k in specs.QUALITY.items():
                for site in (False, True):
                    s = runner.scale_for((w, h), quality, site=site)
                    self.assertTrue(float(w * s).is_integer() and float(h * s).is_integer(), f"{aspect} {quality} site={site}: {w * s} x {h * s}")
                    want = min(k, runner.SITE_MAX_SHORT_SIDE / min(w, h)) if site else k
                    self.assertAlmostEqual(s, want, places=6)

    def test_site_renders_are_capped_at_1080p(self):
        from . import runner

        for aspect, (w, h) in specs.ASPECTS.items():
            s = runner.scale_for((w, h), "1080", site=True)
            self.assertLessEqual(min(w, h) * s, runner.SITE_MAX_SHORT_SIDE + 1e-9)

    def test_a_scale_that_is_not_exact_is_repaired(self):
        from . import runner

        s = runner.exact_scale((1080, 1920), 0.3333)       # 359.964 x 639.936: no neighbouring double fixes it, so the dyadic fallback is used
        self.assertTrue(float(1080 * s).is_integer() and float(1920 * s).is_integer())


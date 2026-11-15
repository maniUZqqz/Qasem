"""کنترلِ کیفیتِ قاعده‌ای: آشکارسازها روی طرح‌های «خراب»ِ عمدی (بیرون‌زدگی، هم‌پوشانی، کنتراستِ کم، صحنهٔ کوتاه، بیرون از ناحیهٔ امن)
و اینکه اصلاحِ خودکار هر کدام را رفع می‌کند و حلقه دوباره می‌سنجد. هندسه از یک «رندرِ ساختگی» می‌آید (فریم‌های واقعی: tests_e2e2.py)."""
from django.test import SimpleTestCase
from PIL import Image

from . import motionlib, qa, specs, timeline

W, H = 1080, 1920


def plan(*scenes, **kw):
    s = {"style": "flat-vector", "aspect": "9:16", "scenes": list(scenes)}
    s.update(kw)
    return specs.normalize_spec(s)


def box(id, text, x, y, w, h, *, scene=0, size=60, color="rgb(255, 255, 255)", opacity=1, parent=-1, overlay="", overflow=False, clipped=False, role="display"):
    return {"kind": "text", "scene": scene, "role": role, "size": size, "x": x, "y": y, "w": w, "h": h, "color": color, "text": text, "overflow": overflow, "clipped": clipped,
            "opacity": opacity, "id": id, "parent": parent, "overlay": overlay}


def shot(boxes, *, scene=0, kind="late", frame=60, safe=None, image=None, scale=0.5):
    return {"scene": scene, "kind": kind, "frame": frame, "W": W, "H": H, "scale": scale, "safe": safe or {"top": 0, "right": 0, "bottom": 0, "left": 0}, "boxes": boxes, "_image": image}


def codes(findings):
    return sorted({f["code"] for f in findings})


class Colour(SimpleTestCase):
    def test_wcag_ratios(self):
        self.assertAlmostEqual(qa.contrast((0, 0, 0), (255, 255, 255)), 21.0, places=1)
        self.assertAlmostEqual(qa.contrast((119, 119, 119), (255, 255, 255)), 4.48, places=1)
        self.assertEqual(qa.parse_color("rgb(10, 20, 30)")[:3], (10, 20, 30))
        self.assertEqual(qa.parse_color("#126F85")[:3], (18, 111, 133))
        self.assertEqual(qa.best_text_color((250, 250, 250))[0], "#111111")
        self.assertEqual(qa.best_text_color((10, 10, 30))[0], "#ffffff")

    def test_background_is_sampled_from_the_pixels_behind_the_text(self):
        im = Image.new("RGB", (540, 960), (30, 30, 60))
        for x in range(200, 300):
            for y in range(400, 420):
                im.putpixel((x, y), (255, 255, 255))                 # the glyphs
        bg = qa.sample_background(im, {"x": 380, "y": 780, "w": 280, "h": 100}, 0.5, (255, 255, 255))
        self.assertIsNotNone(bg)
        self.assertLess(max(abs(a - b) for a, b in zip(bg, (30, 30, 60))), 20)


class Static(SimpleTestCase):
    def test_too_short_scene_is_flagged_and_extended(self):
        p = plan({"type": "list", "duration": 1.5, "title": "سه مزیت", "items": ["برنامهٔ ورزشی شخصی", "برنامهٔ غذایی ایرانی", "خروجی PDF قابل چاپ"]})
        near = plan({"type": "title", "duration": 3, "kicker": "چغر", "title": "با چغر، چغرتر شو", "subtitle": "دستیارِ هوش مصنوعیِ مربی‌ها"})         # 9 words in 3 s: within the tolerance
        self.assertEqual([x for x in qa.static_findings(near) if x["code"] == "too_short"], [])
        f = [x for x in qa.static_findings(p) if x["code"] == "too_short"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["scene"], 0)
        self.assertTrue(f[0]["ops"])
        fixed, applied, _ = qa.apply_fixes(p, f)
        self.assertGreater(fixed["scenes"][0]["duration"], 1.5)
        self.assertEqual(len([x for x in qa.static_findings(fixed) if x["code"] == "too_short"]), 0)

    def test_reading_time_is_about_a_third_of_a_second_per_persian_word(self):
        need = qa.reading_needed({"type": "quote", "duration": 3, "text": " ".join(["کلمه"] * 20)})
        self.assertAlmostEqual(need, motionlib.ENTRANCE_S + 20 * motionlib.READ_S_PER_WORD, delta=0.9)
        self.assertGreaterEqual(motionlib.READ_S_PER_WORD, 0.3)

    def test_narration_longer_than_the_scene_extends_it(self):
        p = plan({"type": "title", "duration": 2, "title": "سلام", "cues": [{"w": "سلام", "s": 0.2, "e": 4.0}]})
        f = [x for x in qa.static_findings(p) if x["code"] == "speech_longer"]
        self.assertEqual(len(f), 1)
        fixed, _, _ = qa.apply_fixes(p, f)
        self.assertGreaterEqual(fixed["scenes"][0]["duration"], 4.4)

    def test_crowded_scene_is_split_in_two(self):
        items = [" ".join(["واژه"] * 8) for _ in range(6)]
        p = plan({"type": "checklist", "duration": 10, "title": "همه چیز", "items": items})
        f = [x for x in qa.static_findings(p) if x["code"] == "crowded"]
        self.assertEqual(len(f), 1)
        fixed, applied, _ = qa.apply_fixes(p, f)
        self.assertEqual(len(fixed["scenes"]), 2)
        self.assertEqual(sum(len(s["items"]) for s in fixed["scenes"]), 6)
        self.assertEqual(len([x for x in qa.static_findings(fixed) if x["code"] == "crowded"]), 0)

    def test_pale_accent_on_the_background_gets_a_readable_colour(self):
        p = plan({"type": "title", "duration": 4, "title": "سلام", "tokens": {"accent": "#fdfdfd", "bg": "#ffffff"}})
        f = [x for x in qa.static_findings(p) if x["code"] == "accent_contrast"]
        self.assertEqual(len(f), 1)
        fixed, _, _ = qa.apply_fixes(p, f)
        self.assertNotEqual(fixed["scenes"][0]["tokens"]["accent"], "#fdfdfd")

    def test_missing_platform_is_only_a_hint(self):
        f = [x for x in qa.static_findings(plan({"type": "title", "duration": 4, "title": "سلام"})) if x["code"] == "platform_missing"]
        self.assertEqual(len(f), 1)
        self.assertFalse(f[0]["auto"])
        self.assertEqual(f[0]["severity"], "info")

    def test_a_long_scene_with_no_motion_gets_a_slow_camera_move(self):
        p = plan({"type": "checklist", "duration": 8, "title": "چه دارد؟", "items": ["الف", "ب", "ج"]})
        f = [x for x in qa.static_findings(p) if x["code"] == "static_scene"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["ops"][0]["value"]["move"], "drift")
        fixed, applied, _ = qa.apply_fixes(p, f)
        self.assertEqual(fixed["scenes"][0]["camera"]["move"], "drift")
        self.assertEqual([x for x in qa.static_findings(fixed) if x["code"] == "static_scene"], [])
        short = plan({"type": "checklist", "duration": 4, "title": "چه دارد؟", "items": ["الف", "ب", "ج"]})
        self.assertEqual([x for x in qa.static_findings(short) if x["code"] == "static_scene"], [])
        moving = plan({"type": "title", "duration": 8, "title": "سلام دنیا", "camera": {"move": "push-in", "amount": 0.4}})
        self.assertEqual([x for x in qa.static_findings(moving) if x["code"] == "static_scene"], [])
        headline = plan({"type": "title", "duration": 7, "title": "سلام دنیا"})
        self.assertEqual([x for x in qa.static_findings(headline) if x["code"] == "static_scene"][0]["ops"][0]["value"]["move"], "push-in")

    def test_a_scene_stretched_for_reading_time_is_not_left_frozen(self):
        cards = [{"icon": "zap", "title": "سریع", "text": "پیش‌نویسِ برنامه در کمتر از یک دقیقه"}, {"icon": "target", "title": "اختصاصی", "text": "برنامهٔ ورزشی و غذاییِ هر ورزشکار"},
                 {"icon": "clipboard-list", "title": "خروجیِ PDF", "text": "برندشده و قابل‌چاپ"}]
        p = plan({"type": "feature_cards", "duration": 5, "title": "دستیار هوش مصنوعیِ مربی‌ها", "cards": cards})
        codes_found = [x["code"] for x in qa.static_findings(p)]
        self.assertIn("too_short", codes_found)
        self.assertIn("static_scene", codes_found, "the scene is stretched to ~9 s: it also gets a slow camera move in the same pass")
        fixed, applied, _ = qa.apply_fixes(p, qa.static_findings(p))
        self.assertGreater(fixed["scenes"][0]["duration"], 8)
        self.assertEqual(fixed["scenes"][0]["camera"]["move"], "drift")

    def test_a_clean_plan_has_no_findings_worth_fixing(self):
        p = plan({"type": "title", "duration": 4, "title": "سلام دنیا"}, {"type": "cta", "duration": 4, "title": "شروع کنید", "button": "ثبت‌نام"}, platform="reels")
        self.assertEqual([f for f in qa.static_findings(p) if f["severity"] in ("error", "warn")], [])


class Geometry(SimpleTestCase):
    def setUp(self):
        self.p = plan({"type": "title", "duration": 5, "title": "سلام دنیا", "subtitle": "یک جمله"})

    def find(self, boxes, **kw):
        return qa.geometry_findings(self.p, [shot(boxes, **kw)])

    def test_overflow_and_clipping_are_errors_with_an_automatic_fix(self):
        out = self.find([box(0, "متنِ خیلی بلند", -40, 800, 1200, 100)])
        self.assertIn("overflow", codes(out))
        f = next(x for x in out if x["code"] == "overflow")
        self.assertEqual(f["severity"], "error")
        self.assertEqual(f["ops"][0]["path"], "scenes/0/tokens/font_scale")
        self.assertLess(f["ops"][0]["value"], 1.0)
        self.assertIn("overflow", codes(self.find([box(0, "بریده", 100, 800, 500, 100, clipped=True)])))
        self.assertIn("overflow", codes(self.find([box(0, "درونِ کادر", 100, 800, 500, 100, overflow=True)])))
        self.assertEqual(codes(self.find([box(0, "سالم", 100, 800, 500, 100)])), [])

    def test_overlap_is_found_but_a_child_inside_its_parent_is_not(self):
        out = self.find([box(0, "تیتر", 100, 800, 600, 120), box(1, "زیرتیتر", 120, 830, 560, 110)])
        self.assertIn("overlap", codes(out))
        out = self.find([box(0, "کارت", 100, 800, 600, 220), box(1, "درونِ کارت", 120, 830, 560, 110, parent=0)])
        self.assertNotIn("overlap", codes(out))
        out = self.find([box(0, "بالا", 100, 400, 600, 120), box(1, "پایین", 100, 900, 600, 120)])
        self.assertNotIn("overlap", codes(out))

    def test_a_faded_out_element_is_not_judged(self):
        out = self.find([box(0, "نیمه‌شفاف", -300, 800, 1200, 100, opacity=0.2)])
        self.assertEqual(codes(out), [])

    def test_safe_zone_violation_of_an_overlay_moves_the_overlay(self):
        p = plan({"type": "title", "duration": 5, "title": "سلام", "overlays": [{"type": "lower_third", "name": "نام", "at": 1, "anchor": "lower"}]}, platform="reels")
        sh = shot([box(0, "نام", 100, 1600, 500, 100, overlay="lower_third")], safe={"top": 270, "right": 108, "bottom": 422, "left": 65})
        out = qa.geometry_findings(p, [sh])
        f = next(x for x in out if x["code"] == "safe_zone")
        self.assertEqual(f["scene"], 0)
        self.assertIn("overlays/0", f["ops"][0]["path"])
        fixed, applied, _ = qa.apply_fixes(p, [f])
        self.assertTrue(applied)
        self.assertNotEqual(fixed["scenes"][0]["overlays"][0].get("dy"), None)

    def test_a_text_outside_the_safe_area_that_is_not_too_wide_is_not_shrunk(self):
        safe = {"top": 270, "right": 108, "bottom": 422, "left": 65}
        out = qa.geometry_findings(self.p, [shot([box(0, "کنارِ قاب", 20, 700, 300, 120)], safe=safe)])
        f = next(x for x in out if x["code"] == "safe_zone")
        self.assertEqual(f["ops"], [])                                    # a layout matter of the component: shrinking would only make the text small
        out = qa.geometry_findings(self.p, [shot([box(0, "پهن", 20, 700, 1040, 120)], safe=safe)])
        self.assertTrue(next(x for x in out if x["code"] == "safe_zone")["ops"])

    def test_text_inside_the_safe_area_passes(self):
        sh = shot([box(0, "امن", 120, 700, 700, 120)], safe={"top": 270, "right": 108, "bottom": 422, "left": 65})
        self.assertEqual(codes(qa.geometry_findings(self.p, [sh])), [])

    def test_tiny_text_is_flagged(self):
        out = self.find([box(0, "ریز", 100, 800, 300, 20, size=24)])
        self.assertIn("small_text", codes(out))
        self.assertEqual(next(x for x in out if x["code"] == "small_text")["severity"], "error")
        near = self.find([box(0, "کمی ریز", 100, 800, 300, 40, size=34)])                      # 1.8 % of the height: borderline = a hint, never a fix
        self.assertEqual([x["severity"] for x in near if x["code"] == "small_text"], ["info"])
        self.assertEqual(codes(self.find([box(0, "درشت", 100, 800, 600, 80, size=64)])), [])

    def test_low_contrast_is_measured_on_the_pixels_and_fixed_with_a_readable_colour(self):
        bg = (240, 240, 235)
        im = Image.new("RGB", (540, 960), bg)
        out = qa.geometry_findings(self.p, [shot([box(0, "کم‌رنگ", 100, 800, 600, 100, color="rgb(235, 235, 230)")], image=im)])
        f = next(x for x in out if x["code"] == "low_contrast")
        self.assertEqual(f["ops"][0]["value"], "#111111")
        self.assertLess(f["ratio"], 1.5)
        ok = qa.geometry_findings(self.p, [shot([box(0, "خوانا", 100, 800, 600, 100, color="rgb(20, 20, 20)")], image=im)])
        self.assertNotIn("low_contrast", codes(ok))
        dark = Image.new("RGB", (540, 960), (12, 20, 40))
        out = qa.geometry_findings(self.p, [shot([box(0, "تیره", 100, 800, 600, 100, color="rgb(30, 36, 60)")], image=dark)])
        self.assertEqual(next(x for x in out if x["code"] == "low_contrast")["ops"][0]["value"], "#ffffff")


class FakeRenderer:
    """رندرِ ساختگی که هندسه را از طرح می‌سازد: پهنای متن با font_scale بزرگ/کوچک می‌شود، پس حلقهٔ اصلاح باید همگرا شود."""

    def __init__(self, chars=40):
        self.chars = chars
        self.calls = 0

    def __call__(self, spec):
        self.calls += 1
        shots = []
        for k in qa.key_frames(spec):
            sc = spec["scenes"][k["scene"]]
            fs = float((sc.get("tokens") or {}).get("font_scale") or 1.0)
            w = self.chars * 30 * fs
            x = (W - w) / 2
            im = Image.new("RGB", (540, 960), (20, 30, 60))
            shots.append(shot([box(0, "متنِ بلند", x, 800, w, 100, scene=k["scene"], overflow=(x < 0))], scene=k["scene"], kind=k["kind"], frame=k["frame"], image=im))
        return shots


class Loop(SimpleTestCase):
    def test_overflow_converges_in_three_rounds_and_is_rechecked(self):
        p = plan({"type": "title", "duration": 5, "title": "سلام دنیا", "subtitle": "یک جمله"}, platform="reels")
        fake = FakeRenderer(chars=45)                           # 1350 px at scale 1 ⇒ overflow
        rep = qa.run_loop(p, measure=fake)
        self.assertEqual(rep["remaining"], [])
        self.assertTrue(rep["ok"])
        self.assertGreaterEqual(rep["fixed"], 2)
        self.assertEqual(len(rep["rounds"]), 3)
        fs = rep["spec"]["scenes"][0]["tokens"]["font_scale"]
        self.assertLess(fs, 0.8)
        self.assertGreaterEqual(fs, 0.6)
        self.assertTrue(all("findings" in r and "applied" in r for r in rep["rounds"]))

    def test_an_unfixable_problem_is_reported_not_looped_forever(self):
        p = plan({"type": "title", "duration": 5, "title": "سلام"}, platform="reels")
        fake = FakeRenderer(chars=400)                           # even at 0.6 it overflows
        rep = qa.run_loop(p, measure=fake)
        self.assertFalse(rep["ok"])
        self.assertTrue(any(f["code"] == "overflow" for f in rep["remaining"]))
        self.assertLessEqual(fake.calls, 5)

    def test_runs_without_a_browser_with_only_the_rules_that_need_none(self):
        p = plan({"type": "list", "duration": 1.2, "title": "فهرست", "items": ["یک جملهٔ بلند برای خواندن", "جملهٔ دوم هم بلند است", "سومی"]}, platform="reels")
        rep = qa.run_loop(p, measure=None)
        self.assertFalse(rep["geometry"])
        self.assertGreaterEqual(rep["fixed"], 1)
        self.assertGreater(rep["spec"]["scenes"][0]["duration"], 1.2)
        self.assertIn("بررسیِ هندسیِ کادر انجام نشد", qa.summary_fa(rep))

    def test_a_failing_browser_degrades_to_the_static_rules(self):
        def boom(spec):
            raise RuntimeError("chrome is gone")

        rep = qa.run_loop(plan({"type": "title", "duration": 4, "title": "سلام"}, platform="reels"), measure=boom)
        self.assertFalse(rep["geometry"])
        self.assertIn("chrome is gone", rep["geometry_error"])

    def test_every_finding_with_a_fix_names_a_valid_patch(self):
        from . import patch

        p = plan({"type": "list", "duration": 1.2, "title": "فهرست", "items": ["الف ب ج د", "ه و ز ح", "ط ی ک ل"]}, platform="reels")
        for f in qa.static_findings(p):
            if f["ops"]:
                patch.apply_patch(p, f["ops"])

    def test_loop_report_is_json_serialisable(self):
        import json

        rep = qa.run_loop(plan({"type": "title", "duration": 5, "title": "سلام"}, platform="reels"), measure=FakeRenderer(chars=45))
        json.dumps({k: v for k, v in rep.items() if k != "spec"})


class KeyFrames(SimpleTestCase):
    def test_two_frames_per_scene_inside_the_scene_and_outside_the_transitions(self):
        p = plan({"type": "title", "duration": 4, "title": "الف"}, {"type": "list", "duration": 6, "title": "ب", "items": ["یک", "دو", "سه"]}, {"type": "cta", "duration": 4, "title": "ج"})
        t = timeline.compute(p)
        keys = qa.key_frames(p)
        self.assertEqual(len(keys), 6)
        for k in keys:
            i = k["scene"]
            lo = t["starts"][i] + (t["tfs"][i - 1] if i else 0)
            hi = t["starts"][i] + t["frames"][i] - (t["tfs"][i] if i < 2 else 0)
            self.assertTrue(lo <= k["frame"] < hi, (k, lo, hi))
            self.assertLess(k["frame"], t["total"])
        by = {(k["scene"], k["kind"]): k["frame"] for k in keys}
        for i in range(3):
            self.assertLess(by[(i, "enter")], by[(i, "late")])


class AccentAndStacking(SimpleTestCase):
    def test_a_low_contrast_accent_word_is_fixed_in_the_accent_colour(self):
        p = plan({"type": "stat", "duration": 4, "value": "1300", "suffix": "+", "label": "حرکت"}, brand={"colors": ["#126F85", "#163F75"], "use_brand_colors": True})
        dark = Image.new("RGB", (540, 960), (30, 60, 80))
        out = qa.geometry_findings(p, [shot([box(0, "+", 100, 800, 80, 100, color="rgb(18, 111, 133)", size=120)], image=dark)])
        f = next(x for x in out if x["code"] == "low_contrast")
        self.assertEqual(f["ops"][0]["path"], "scenes/0/tokens/accent")
        out = qa.geometry_findings(p, [shot([box(0, "متن", 100, 800, 300, 100, color="rgb(40, 70, 90)", size=80)], image=dark)])
        self.assertEqual(next(x for x in out if x["code"] == "low_contrast")["ops"][0]["path"], "scenes/0/tokens/text")

    def test_layers_stacked_on_purpose_are_not_an_overlap(self):
        p = plan({"type": "before_after", "duration": 6, "before": "الف", "after": "ب"})
        a = box(0, "روشِ قبلی", 100, 800, 600, 120)
        b = box(1, "روشِ تازه", 110, 810, 600, 120)
        a["excl"] = b["excl"] = "before-after"
        self.assertNotIn("overlap", codes(qa.geometry_findings(p, [shot([a, b])])))
        del a["excl"], b["excl"]
        self.assertIn("overlap", codes(qa.geometry_findings(p, [shot([a, b])])))


class MixedBackdrop(SimpleTestCase):
    """متنِ عادی در یک صحنه یک رنگ دارد؛ وقتی پشتِ بعضی برچسب‌ها روشن و پشتِ بعضی تیره است (لکه‌های متحرکِ سبک)، هیچ رنگِ واحدی همه را نجات نمی‌دهد:
    اصلاحِ درست «آرام‌کردنِ تزئین» است، نه سفیدکردنِ همه‌چیز (که برچسب‌های روی زمینهٔ روشن را ناخوانا می‌کرد)."""

    def setUp(self):
        self.p = plan({"type": "icon_grid", "duration": 6, "title": "امکانات", "items": [{"icon": "dumbbell", "label": "تمرین"}, {"icon": "salad", "label": "تغذیه"}]})
        im = Image.new("RGB", (540, 960), (245, 232, 215))                  # a light page ...
        for x in range(270, 540):                                           # ... with a dark blob on its right half
            for y in range(380, 520):
                im.putpixel((x, y), (40, 52, 96))
        self.im = im
        self.light = box(0, "تغذیه", 100, 800, 300, 100, color="rgb(40, 52, 96)", size=70)
        self.dark = box(1, "تمرین", 640, 800, 300, 100, color="rgb(40, 60, 110)", size=70)

    def test_a_scene_with_both_light_and_dark_backdrops_is_calmed_not_recoloured(self):
        out = qa.geometry_findings(self.p, [shot([self.light, self.dark], image=self.im)])
        low = [f for f in out if f["code"] == "low_contrast"]
        self.assertTrue(low)
        for f in low:
            self.assertEqual(f["ops"], [{"op": "set", "path": "scenes/0/tokens/calm", "value": True}])

    def test_the_fix_is_applied_and_survives_normalisation(self):
        out = qa.geometry_findings(self.p, [shot([self.light, self.dark], image=self.im)])
        fixed, applied, _unresolved = qa.apply_fixes(self.p, out)
        self.assertTrue(applied)
        self.assertIs(fixed["scenes"][0]["tokens"]["calm"], True)
        self.assertIs(specs.normalize_spec(fixed)["scenes"][0]["tokens"]["calm"], True)

    def test_a_scene_whose_texts_all_sit_on_the_dark_side_gets_one_readable_colour(self):
        dark_only = Image.new("RGB", (540, 960), (20, 30, 60))
        a = box(0, "تمرین", 100, 800, 300, 100, color="rgb(40, 52, 96)", size=70)
        b = box(1, "تغذیه", 600, 800, 300, 100, color="rgb(40, 52, 96)", size=70)
        out = qa.geometry_findings(self.p, [shot([a, b], image=dark_only)])
        ops = {f["ops"][0]["path"] + "=" + str(f["ops"][0]["value"]) for f in out if f["code"] == "low_contrast"}
        self.assertEqual(ops, {"scenes/0/tokens/text=#ffffff"})

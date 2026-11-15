"""ویرایشِ تکه‌ای: عملیاتِ patch، اتمی‌بودن، و قاعده‌های فارسیِ «بدونِ هوش مصنوعی» («تیتر بزرگ‌تر شود»، «رنگِ صحنهٔ دوم گرم‌تر»…)."""
from django.test import SimpleTestCase

from . import patch, qa, specs


def base():
    return specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "platform": "reels", "scenes": [
        {"type": "kinetic_title", "duration": 4, "text": "با چغر، چغر تر شو"},
        {"type": "checklist", "duration": 6, "title": "چه دارد؟", "items": ["برنامهٔ ورزشی", "برنامهٔ غذایی", "خروجی PDF", "ویرایش", "کتابخانه", "اسکن"]},
        {"type": "cta", "duration": 4, "title": "همین حالا شروع کنید", "button": "ثبت‌نام"}]})


class Ops(SimpleTestCase):
    def test_only_the_asked_scene_and_field_change(self):
        a = base()
        b = patch.apply_patch(a, [{"op": "scale", "path": "scenes/0/tokens/font_scale", "factor": 1.2, "default": 1, "min": 0.6, "max": 1.6}])
        self.assertEqual(b["scenes"][0]["tokens"], {"font_scale": 1.2})
        self.assertEqual(b["scenes"][1], a["scenes"][1])
        self.assertEqual(b["scenes"][2], a["scenes"][2])
        self.assertEqual(patch.diff_summary(a, b), ["صحنهٔ 1: tokens"])

    def test_scale_is_clamped(self):
        a = patch.apply_patch(base(), [{"op": "set", "path": "scenes/0/tokens/font_scale", "value": 1.5}])
        b = patch.apply_patch(a, [{"op": "scale", "path": "scenes/0/tokens/font_scale", "factor": 2, "max": 1.6}])
        self.assertEqual(b["scenes"][0]["tokens"]["font_scale"], 1.6)

    def test_set_remove_shift(self):
        a = base()
        b = patch.apply_patch(a, [{"op": "set", "path": "scenes/1/camera", "value": {"move": "push-in", "amount": 0.5}}, {"op": "shift", "path": "scenes/2/duration", "by": 2}])
        self.assertEqual(b["scenes"][1]["camera"]["move"], "push-in")
        self.assertEqual(b["scenes"][2]["duration"], 6)
        c = patch.apply_patch(b, [{"op": "remove", "path": "scenes/1/camera"}])
        self.assertNotIn("camera", c["scenes"][1])

    def test_structural_ops(self):
        a = base()
        self.assertEqual([s["type"] for s in patch.apply_patch(a, {"op": "move_scene", "from": 2, "to": 0})["scenes"]], ["cta", "kinetic_title", "checklist"])
        self.assertEqual(len(patch.apply_patch(a, {"op": "duplicate_scene", "index": 1})["scenes"]), 4)
        self.assertEqual(len(patch.apply_patch(a, {"op": "remove_scene", "index": 1})["scenes"]), 2)
        split = patch.apply_patch(a, {"op": "split_scene", "index": 1})["scenes"]
        self.assertEqual([len(s["items"]) for s in split[1:3]], [3, 3])
        chart = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "scenes": [{"type": "bar_chart", "duration": 6, "bars": [{"label": "الف", "value": 1}, {"label": "ب", "value": 2}, {"label": "ج", "value": 3}]}]})
        with self.assertRaises(patch.PatchError):                 # a chart is never cut in halves
            patch.apply_patch(chart, {"op": "split_scene", "index": 0})
        added = patch.apply_patch(a, {"op": "add_scene", "at": 1, "scene": {"type": "stat", "duration": 4, "value": "1300", "label": "حرکت"}})
        self.assertEqual(added["scenes"][1]["type"], "stat")

    def test_the_whole_patch_is_atomic(self):
        a = base()
        with self.assertRaises(patch.PatchError):
            patch.apply_patch(a, [{"op": "set", "path": "scenes/0/duration", "value": 9}, {"op": "set", "path": "scenes/8/duration", "value": 9}])
        with self.assertRaises(patch.PatchError):
            patch.apply_patch(a, [{"op": "set", "path": "scenes/0/duration", "value": 9}, {"op": "remove_scene", "index": 9}])
        self.assertEqual(a["scenes"][0]["duration"], 4)

    def test_invalid_results_are_refused_with_a_persian_reason(self):
        a = base()
        for bad in ({"op": "set", "path": "style", "value": "nope"}, {"op": "set", "path": "scenes/0/type", "value": "evil"}, {"op": "set", "path": "scenes/1/items", "value": "نه فهرست"},
                    {"op": "set", "path": "../etc", "value": 1}, {"op": "set", "path": "scenes/0/duration", "value": "abc"}):
            with self.assertRaises(patch.PatchError) as cm:
                patch.apply_patch(a, [bad])
            self.assertTrue(str(cm.exception))

    def test_a_noop_is_reported(self):
        with self.assertRaises(patch.PatchError) as cm:
            patch.apply_patch(base(), [{"op": "set", "path": "scenes/0/zzz", "value": 1}])
        self.assertIn("عوض نکرد", str(cm.exception))

    def test_too_many_ops_and_unknown_paths(self):
        with self.assertRaises(patch.PatchError):
            patch.apply_patch(base(), [{"op": "set", "path": "scenes/0/duration", "value": 5}] * (patch.MAX_OPS + 1))
        with self.assertRaises(patch.PatchError):
            patch.apply_patch(base(), [{"op": "set", "path": "secret/x", "value": 1}])

    def test_the_input_is_not_mutated(self):
        a = base()
        import copy

        snap = copy.deepcopy(a)
        patch.apply_patch(a, [{"op": "set", "path": "scenes/0/duration", "value": 9}])
        self.assertEqual(a, snap)


class PersianRules(SimpleTestCase):
    def run_rule(self, text, plan=None):
        plan = plan or base()
        res = patch.rules_patch(text, plan)
        out = patch.apply_patch(plan, res["ops"]) if res["ops"] else plan
        return res, out

    def test_bigger_title(self):
        res, out = self.run_rule("تیتر بزرگ‌تر شود")
        self.assertEqual(len(res["ops"]), 1)                       # «تیتر» = تیترِ ویدیو = صحنهٔ اول؛ بقیه دست‌نخورده
        self.assertGreater(out["scenes"][0]["tokens"]["font_scale"], 1.0)
        self.assertNotIn("tokens", out["scenes"][1])
        self.assertTrue(all(o["op"] == "scale" for o in res["ops"]))
        self.assertIn("بزرگ‌تر", res["say"])

    def test_bigger_for_one_scene_only(self):
        res, out = self.run_rule("متنِ صحنهٔ دوم بزرگ‌تر شود")
        self.assertEqual(len(res["ops"]), 1)
        self.assertGreater(out["scenes"][1]["tokens"]["font_scale"], 1.0)
        self.assertNotIn("tokens", out["scenes"][0])
        res, out = self.run_rule("صحنه ۳ کوچک‌تر")
        self.assertLess(out["scenes"][2]["tokens"]["font_scale"], 1.0)

    def test_warmer_colour_of_the_second_scene(self):
        res, out = self.run_rule("رنگِ صحنهٔ دوم گرم‌تر")
        acc = out["scenes"][1]["tokens"]["accent"]
        self.assertTrue(acc.startswith("#"))
        r, g, b = (int(acc[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(r, b)                                   # a warm colour: more red than blue
        self.assertNotIn("tokens", out["scenes"][0])
        res, out = self.run_rule("رنگ صحنه دوم سردتر")
        acc = out["scenes"][1]["tokens"]["accent"]
        r, g, b = (int(acc[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(b, r)

    def test_named_colours(self):
        res, out = self.run_rule("رنگِ تیتر صحنهٔ اول قرمز")
        self.assertEqual(out["scenes"][0]["tokens"]["text"], "#e63946")
        res, out = self.run_rule("رنگِ زمینهٔ صحنهٔ سوم مشکی")
        self.assertEqual(out["scenes"][2]["tokens"]["bg"], "#111111")

    def test_duration_phrases(self):
        res, out = self.run_rule("صحنهٔ سوم طولانی‌تر باشد")
        self.assertEqual(out["scenes"][2]["duration"], 5.5)
        res, out = self.run_rule("صحنه اول کوتاه‌تر")
        self.assertEqual(out["scenes"][0]["duration"], 3)

    def test_structure_phrases(self):
        res, out = self.run_rule("صحنهٔ آخر را حذف کن")
        self.assertEqual(len(out["scenes"]), 2)
        res, out = self.run_rule("صحنهٔ اول را تکرار کن")
        self.assertEqual(len(out["scenes"]), 4)

    def test_switches(self):
        res, out = self.run_rule("زیرنویس اضافه کن")
        self.assertTrue(out["captions"]["on"])
        res, out = self.run_rule("گوینده اضافه کن")
        self.assertTrue(out["audio"]["voice"]["on"])
        res, out = self.run_rule("موسیقی زمینه بگذار")
        self.assertTrue(out["audio"]["music"]["on"])
        res, out = self.run_rule("برای تیک‌تاک باشد")
        self.assertEqual(out["platform"], "tiktok")
        res, out = self.run_rule("دوربین نزدیک‌تر شود")
        self.assertEqual(out["scenes"][0]["camera"]["move"], "push-in")

    def test_style_by_persian_name(self):
        from . import catalog

        st = next(s for s in catalog.STYLES if s["name_fa"])
        res, out = self.run_rule(f"سبک {st['name_fa']} را بگذار")
        self.assertEqual(out["style"], st["id"])

    def test_gibberish_gets_a_helpful_answer(self):
        res = patch.rules_patch("بلبل زبان", base())
        self.assertEqual(res["ops"], [])
        self.assertIn("نفهمیدم", res["say"])

    def test_the_rules_never_return_more_than_the_op_limit(self):
        res = patch.rules_patch("همهٔ صحنه‌ها بزرگ‌تر شوند", base())
        self.assertLessEqual(len(res["ops"]), patch.MAX_OPS)
        self.assertEqual(len(res["ops"]), 3)
        self.assertTrue(qa is not None)

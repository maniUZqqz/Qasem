"""نقدِ بصری: ۳ تا ۶ فریم ⇒ مدلِ بینا (ساختگی) ⇒ patch ⇒ فریم‌های تازه، تا ۳ دور؛ مدل نبود ⇒ «منتظر» و خودکار دوباره؛ هر patch یک نسخهٔ برگشت‌پذیر."""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from PIL import Image

from apps.stores.models import Store

from . import critique, plans, qa, specs, tasks
from .models import MotionPlan, MotionPlanRev

User = get_user_model()


def base():
    return {"style": "flat-vector", "aspect": "9:16", "platform": "reels", "scenes": [
        {"type": "kinetic_title", "duration": 4, "text": "با چغر، چغر تر شو"},
        {"type": "checklist", "duration": 6, "title": "چه دارد؟", "items": ["برنامهٔ ورزشی", "برنامهٔ غذایی", "خروجی PDF"]},
        {"type": "steps", "duration": 7, "title": "چهار قدم", "steps": [{"title": "الف"}, {"title": "ب"}, {"title": "ج"}]},
        {"type": "cta", "duration": 4, "title": "همین حالا شروع کنید", "button": "ثبت‌نام"}]}


def fake_measure(spec):
    out = []
    for k in critique.pick_frames(spec):
        out.append({"scene": k["scene"], "kind": k["kind"], "frame": k["frame"], "W": 1080, "H": 1920, "scale": 0.5, "safe": {}, "boxes": [],
                    "_image": Image.new("RGB", (540, 960), (250, 240, 230)), "image_rel": f"generated/motion/1/qa/x-s{k['scene']}.jpg"})
    return out


class Provider:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def generate(self, prompt, **kw):
        self.calls.append((prompt, kw))
        r = self.replies.pop(0) if self.replies else self.calls and '{"verdict":"ok","issues":[],"ops":[]}'
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


class Critique(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("crit-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")
        self.plan = plans.create(self.store, self.owner, base())

    def test_frames_are_three_to_six_scenes_with_the_first_and_the_last(self):
        picks = critique.pick_frames(specs.normalize_spec(base()))
        scenes = sorted({p["scene"] for p in picks})
        self.assertTrue(3 <= len(scenes) <= critique.MAX_FRAMES)
        self.assertIn(0, scenes)
        self.assertIn(3, scenes)
        self.assertTrue(all(p["kind"] == "late" for p in picks))

    def test_the_model_sees_the_images_and_the_schema_and_its_patch_becomes_a_revision(self):
        fix = {"verdict": "fix", "issues": [{"scene": 1, "problem": "متنِ فهرست ریز است", "severity": "medium"}],
               "ops": [{"op": "scale", "path": "scenes/1/tokens/font_scale", "factor": 0.9, "default": 1}]}
        prov = Provider(fix, {"verdict": "ok", "issues": [], "ops": []})
        state = critique.run(self.plan, provider=prov, measure=fake_measure)
        self.assertEqual(state["state"], "done")
        self.assertEqual(len(state["rounds"]), 2)
        first = state["rounds"][0]
        self.assertEqual(first["verdict"], "fix")
        self.assertEqual(first["issues"][0]["problem"], "متنِ فهرست ریز است")
        self.assertTrue(first["before"] and first["after"])
        self.assertTrue(first["before"][0]["image_rel"])
        prompt, kw = prov.calls[0]
        self.assertEqual(len(kw["images"]), len(first["before"]))
        self.assertIn("json_schema", kw)
        self.assertIn("PLAN", prompt)
        plan = MotionPlan.objects.get(pk=self.plan.pk)
        self.assertEqual(plan.spec["scenes"][1]["tokens"]["font_scale"], 0.9)
        self.assertEqual(MotionPlanRev.objects.filter(plan=plan).last().source, "critique")
        plan = plans.step(plan, -1)                                          # a critique is undoable like any edit
        self.assertNotIn("tokens", plan.spec["scenes"][1])

    def test_at_most_three_rounds(self):
        fix = {"verdict": "fix", "issues": [], "ops": [{"op": "scale", "path": "scenes/0/tokens/font_scale", "factor": 0.9, "default": 1}]}
        prov = Provider(fix, fix, fix, fix, fix)
        state = critique.run(self.plan, provider=prov, measure=fake_measure)
        self.assertEqual(len(state["rounds"]), critique.MAX_ROUNDS)
        self.assertEqual(len(prov.calls), critique.MAX_ROUNDS)

    def test_invalid_patches_are_rejected_one_by_one_and_never_break_the_plan(self):
        bad = {"verdict": "fix", "issues": [{"scene": 0, "problem": "x"}], "ops": [{"op": "set", "path": "scenes/9/duration", "value": 4}, {"op": "evil"},
                                                                                     {"op": "set", "path": "scenes/0/tokens/accent", "value": "#e63946"}]}
        state = critique.run(self.plan, provider=Provider(bad, {"verdict": "ok"}), measure=fake_measure)
        r = state["rounds"][0]
        self.assertEqual(len(r["rejected"]), 2)
        self.assertEqual(len(r["applied"]), 1)
        self.assertEqual(MotionPlan.objects.get(pk=self.plan.pk).spec["scenes"][0]["tokens"]["accent"], "#e63946")

    def test_nothing_applicable_ends_the_critique_with_the_issues_reported(self):
        state = critique.run(self.plan, provider=Provider({"verdict": "fix", "issues": [{"scene": 0, "problem": "ریز"}], "ops": [{"op": "evil"}]}), measure=fake_measure)
        self.assertEqual(state["state"], "done")
        self.assertEqual(MotionPlan.objects.get(pk=self.plan.pk).cursor, 1)

    def test_a_model_that_is_not_there_makes_the_critique_wait_and_it_retries_by_itself(self):
        class Gone:
            def availability(self):
                return False, "سرورِ پردازش خاموش است"

        state = critique.run(self.plan, provider=Gone(), measure=fake_measure)
        self.assertEqual(state["state"], "waiting")
        self.assertIn("منتظرِ مدلِ بینایی", state["message"])
        self.assertEqual(state["attempts"], 1)
        # the node comes on: the periodic task picks the waiting critique up and finishes it
        prov = Provider({"verdict": "ok", "issues": [], "ops": []})
        with mock.patch.object(critique.ai, "get_provider", return_value=prov), mock.patch.object(critique.qa_browser, "available", return_value=(True, "")), \
                mock.patch.object(critique.qa_browser, "make_measure", return_value=fake_measure):
            tasks.critique_task(self.plan.pk)
        plan = MotionPlan.objects.get(pk=self.plan.pk)
        self.assertEqual(plan.critique["state"], "done")
        self.assertEqual(len(plan.critique["rounds"]), 1)

    def test_a_failing_call_in_round_one_waits_a_failing_call_later_keeps_what_was_done(self):
        state = critique.run(self.plan, provider=Provider(RuntimeError("HTTP 402")), measure=fake_measure)
        self.assertEqual(state["state"], "waiting")
        fix = {"verdict": "fix", "issues": [], "ops": [{"op": "scale", "path": "scenes/0/tokens/font_scale", "factor": 0.9, "default": 1}]}
        plan2 = plans.create(self.store, self.owner, base())
        state = critique.run(plan2, provider=Provider(fix, RuntimeError("node went off")), measure=fake_measure)
        self.assertEqual(state["state"], "done")
        self.assertEqual(len(state["rounds"]), 1)

    def test_without_the_render_tool_the_critique_says_so(self):
        with mock.patch.object(critique.qa_browser, "available", return_value=(False, "مرورگر نیست")):
            state = critique.run(self.plan, provider=Provider({"verdict": "ok"}))
        self.assertEqual(state["state"], "unavailable")
        self.assertIn("مرورگر نیست", state["message"])

    def test_the_request_endpoint_state_is_waiting_until_the_task_runs(self):
        state = critique.request(self.plan)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(MotionPlan.objects.get(pk=self.plan.pk).critique["state"], "waiting")

    def test_the_critique_state_is_public_with_image_urls(self):
        plan = MotionPlan.objects.get(pk=self.plan.pk)
        plan.critique = {"state": "done", "rounds": [{"n": 1, "verdict": "ok", "issues": [], "ops": [], "applied": [], "rejected": [],
                                                      "before": [{"scene": 0, "frame": 10, "image_rel": "generated/motion/1/qa/a.jpg"}], "after": []}]}
        plan.save()
        d = plans.plan_dict(plan)
        self.assertTrue(d["critique"]["rounds"][0]["before"][0]["image_url"].endswith("generated/motion/1/qa/a.jpg"))
        self.assertTrue(qa is not None)

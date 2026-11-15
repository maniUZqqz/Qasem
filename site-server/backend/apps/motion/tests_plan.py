"""«طرحِ صحنه» نسخهٔ ۲: شمای نسخه‌دار و اعتبارسنجی، تاریخچه با برگشت/جلوتر، API ِ طرح‌ها، ویرایشِ تکه‌ای و چت، رندر از روی طرح."""
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import ai, catalog, components, patch, plans, specs
from .models import MotionPlan, MotionPlanRev, MotionRender

User = get_user_model()


def base(**kw):
    s = {"style": "flat-vector", "aspect": "9:16", "scenes": [
        {"type": "kinetic_title", "duration": 4, "text": "با چغر، چغر تر شو"},
        {"type": "checklist", "duration": 6, "title": "چه دارد؟", "items": ["برنامهٔ ورزشی", "برنامهٔ غذایی", "خروجی PDF"]},
        {"type": "cta", "duration": 4, "title": "همین حالا شروع کنید", "button": "ثبت‌نام"}]}
    s.update(kw)
    return s


class SchemaV2(SimpleTestCase):
    def test_version_is_two_and_v1_plans_upgrade_unchanged(self):
        v1 = {"version": 1, "style": "flat-vector", "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "سلام"}]}
        out = specs.upgrade(v1)
        self.assertEqual(out["version"], 2)
        self.assertEqual(out["scenes"][0]["title"], "سلام")
        with self.assertRaises(specs.SpecError):
            specs.normalize_spec({**v1, "version": 3})

    def test_scene_level_tokens_are_validated(self):
        sc = {"type": "title", "duration": 4, "title": "سلام", "enter": "slam", "exit": "fade", "ease": "out-soft", "spring": "bouncy", "emphasis": ["سلام", " "],
              "camera": {"move": "push-in", "amount": 5}, "transition": "iris", "tokens": {"accent": "#E63946", "text": "bad", "font_scale": 9, "align": "start"},
              "narration": "سلام به شما", "cues": [{"w": "سلام", "s": 0.2, "e": 0.6}, {"w": "x", "s": 3, "e": 1}], "sfx": [{"at": 1, "kind": "pop"}, {"at": 1, "kind": "evil"}]}
        notes: list = []
        out = specs.normalize_spec(base(scenes=[sc]), notes=notes)["scenes"][0]
        self.assertEqual((out["enter"], out["exit"], out["ease"], out["spring"], out["transition"]), ("slam", "fade", "out-soft", "bouncy", "iris"))
        self.assertEqual(out["emphasis"], ["سلام"])
        self.assertEqual(out["camera"], {"move": "push-in", "amount": 1.0})
        self.assertEqual(out["tokens"], {"accent": "#e63946", "font_scale": 1.6, "align": "start"})
        self.assertEqual(out["cues"], [{"w": "سلام", "s": 0.2, "e": 0.6}])
        self.assertEqual([e["kind"] for e in out["sfx"]], ["pop"])
        self.assertTrue(any("text" in n for n in notes))

    def test_unknown_names_are_dropped_with_a_persian_note(self):
        notes: list = []
        out = specs.normalize_spec(base(scenes=[{"type": "title", "duration": 3, "title": "a", "ease": "nope", "transition": "evil", "enter": "x"}]), notes=notes)
        sc = out["scenes"][0]
        self.assertNotIn("ease", sc)
        self.assertNotIn("transition", sc)
        self.assertGreaterEqual(len(notes), 3)

    def test_overlays_only_for_overlay_components(self):
        sc = {"type": "title", "duration": 5, "title": "سلام", "overlays": [{"type": "lower_third", "name": "مربی", "at": 1, "anchor": "lower"}, {"type": "sticker", "text": "جدید", "kind": "burst"}]}
        out = specs.normalize_spec(base(scenes=[sc]))["scenes"][0]
        self.assertEqual([o["type"] for o in out["overlays"]], ["lower_third", "sticker"])
        with self.assertRaises(specs.SpecError) as cm:
            specs.normalize_spec(base(scenes=[{**sc, "overlays": [{"type": "bar_chart", "bars": []}]}]))
        self.assertIn("رو", str(cm.exception))
        with self.assertRaises(specs.SpecError):
            specs.normalize_spec(base(scenes=[{**sc, "overlays": [{"type": "lower_third"}]}]))        # «name» ندارد

    def test_platform_fills_the_safe_zone_and_audio_is_cleaned(self):
        out = specs.normalize_spec(base(platform="reels", captions={"on": True, "position": "center"},
                                        audio={"voice": {"on": True, "voice_id": "piper:mana", "speed": 5}, "music": {"on": True, "ref": "evil", "level_db": -2}, "sfx": 1, "beat_sync": 0}))
        self.assertEqual(out["safe"]["bottom"], 0.22)
        self.assertEqual(out["captions"], {"on": True, "position": "center"})
        self.assertEqual(out["audio"]["voice"], {"on": True, "voice_id": "piper:mana", "speed": 1.25})
        self.assertEqual(out["audio"]["music"], {"on": True, "ref": "auto", "level_db": -12.0})
        self.assertTrue(out["audio"]["sfx"] and out["audio"]["beat_sync"] is False)
        self.assertNotIn("platform", specs.normalize_spec(base(platform="nope")))

    def test_every_component_is_a_valid_scene_type_in_every_aspect(self):
        for a in specs.ASPECTS:
            for cid, c in components.COMPONENTS.items():
                specs.normalize_spec({"style": "flat-vector", "aspect": a, "scenes": [dict(c["sample"])]})

    def test_missing_needed_content_is_refused_in_persian(self):
        for bad in ({"type": "bar_chart", "duration": 5}, {"type": "steps", "duration": 5, "title": "x"}, {"type": "price_card", "duration": 5}):
            with self.assertRaises(specs.SpecError) as cm:
                specs.normalize_spec(base(scenes=[bad]))
            self.assertIn("ندارد", str(cm.exception))

    def test_objects_accept_plain_strings_and_cap_lists(self):
        out = specs.normalize_scene({"type": "steps", "duration": 6, "title": "t", "steps": ["الف", "ب", "ج", "د", "ه", "و", "ز"]}, 0)
        self.assertEqual(len(out["steps"]), 5)
        self.assertEqual(out["steps"][0], {"title": "الف"})
        out = specs.normalize_scene({"type": "bar_chart", "duration": 6, "bars": [{"label": "الف", "value": "۴۰"}, {"label": "ب", "value": "x"}]}, 0)
        self.assertEqual(out["bars"][0]["value"], 40.0)

    def test_json_schema_for_the_model_is_valid(self):
        from . import promptkit

        sch = promptkit.json_schema(["title", "bar_chart", "cta"])
        self.assertEqual(sch["properties"]["scenes"]["items"]["properties"]["type"]["enum"], ["title", "bar_chart", "cta"])
        self.assertIn("bars", sch["properties"]["scenes"]["items"]["properties"])


class History(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("plan-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")

    def test_create_commit_undo_redo(self):
        plan = plans.create(self.store, self.owner, base())
        self.assertEqual((plan.cursor, MotionPlanRev.objects.filter(plan=plan).count()), (1, 1))
        plan, summary = plans.apply_ops(plan, [{"op": "set", "path": "scenes/0/duration", "value": 5}], label="مدت")
        plan, _ = plans.apply_ops(plan, [{"op": "set", "path": "scenes/1/duration", "value": 8}])
        self.assertEqual(plan.cursor, 3)
        self.assertEqual(plan.spec["scenes"][1]["duration"], 8)
        plan = plans.step(plan, -1)
        self.assertEqual(plan.spec["scenes"][1]["duration"], 6)
        self.assertTrue(plans.can_redo(plan) and plans.can_undo(plan))
        plan = plans.step(plan, 1)
        self.assertEqual(plan.spec["scenes"][1]["duration"], 8)
        plan = plans.step(plan, -1)
        plan = plans.step(plan, -1)
        self.assertFalse(plans.can_undo(plan))
        with self.assertRaises(plans.PlanError):
            plans.step(plan, -1)

    def test_editing_after_undo_drops_the_forward_branch(self):
        plan = plans.create(self.store, self.owner, base())
        plan, _ = plans.apply_ops(plan, [{"op": "set", "path": "scenes/0/duration", "value": 5}])
        plan, _ = plans.apply_ops(plan, [{"op": "set", "path": "scenes/0/duration", "value": 6}])
        plan = plans.step(plan, -1)
        plan, _ = plans.apply_ops(plan, [{"op": "set", "path": "scenes/2/duration", "value": 7}])
        self.assertFalse(plans.can_redo(plan))
        self.assertEqual([r["n"] for r in plans.history(plan)], [1, 2, 3])

    def test_a_noop_does_not_make_a_revision(self):
        plan = plans.create(self.store, self.owner, base())
        same = plans.commit(plan, plan.spec)
        self.assertEqual(MotionPlanRev.objects.filter(plan=plan).count(), 1)
        self.assertEqual(same.cursor, 1)

    def test_user_typing_is_coalesced_but_other_sources_are_not(self):
        plan = plans.create(self.store, self.owner, base())
        plan = plans.commit(plan, {**plan.spec, "intensity": 1.1}, source="user")
        n = MotionPlanRev.objects.filter(plan=plan).count()
        for k in (1.2, 1.3, 1.4):
            plan = plans.commit(plan, {**plan.spec, "intensity": k}, source="user", coalesce=True)
        self.assertEqual(MotionPlanRev.objects.filter(plan=plan).count(), n)
        self.assertEqual(plan.spec["intensity"], 1.4)
        plan, _ = plans.apply_ops(plan, [{"op": "set", "path": "intensity", "value": 0.9}])
        self.assertEqual(MotionPlanRev.objects.filter(plan=plan).count(), n + 1)

    def test_history_is_capped(self):
        plan = plans.create(self.store, self.owner, base())
        for i in range(plans.MAX_REVS + 8):
            plan, _ = plans.apply_ops(plan, [{"op": "set", "path": "scenes/0/duration", "value": 3 + (i % 20) / 4}])
        self.assertLessEqual(MotionPlanRev.objects.filter(plan=plan).count(), plans.MAX_REVS)

    def test_a_bad_patch_changes_nothing(self):
        plan = plans.create(self.store, self.owner, base())
        before = plan.spec
        for bad in ([{"op": "set", "path": "scenes/9/duration", "value": 5}], [{"op": "evil"}], [{"op": "remove_scene", "index": 7}], []):
            with self.assertRaises(plans.PlanError):
                plans.apply_ops(plan, bad)
        plan.refresh_from_db()
        self.assertEqual(plan.spec, before)
        self.assertEqual(MotionPlanRev.objects.filter(plan=plan).count(), 1)


class PlanApi(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="nmmotion-plan-")
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        self.owner = User.objects.create_user("plan-api", password="x")
        self.other = User.objects.create_user("plan-other", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.b = f"/api/v1/stores/{self.store.pk}/motion"

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def make(self):
        r = self.api.post(f"{self.b}/plans/", {"spec": base(), "title": "تیزر"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["plan"]

    def test_library_endpoint(self):
        r = self.api.get("/api/v1/motion/library/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertGreaterEqual(len(d["components"]), 29)
        self.assertIn("ink", d["transition_pack"])
        self.assertTrue(any(p["id"] == "reels" for p in d["platforms"]))
        self.assertIn("promo", {t["id"] for t in d["templates"]})

    def test_crud_patch_undo_redo(self):
        plan = self.make()
        pid = plan["id"]
        self.assertEqual(plan["rev"], 1)
        r = self.api.post(f"{self.b}/plans/{pid}/patch/", {"ops": [{"op": "scale", "path": "scenes/0/tokens/font_scale", "factor": 1.2, "default": 1}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["plan"]["spec"]["scenes"][0]["tokens"]["font_scale"], 1.2)
        self.assertTrue(r.json()["changes"])
        r = self.api.post(f"{self.b}/plans/{pid}/undo/", {}, format="json")
        self.assertNotIn("tokens", r.json()["plan"]["spec"]["scenes"][0])
        r = self.api.post(f"{self.b}/plans/{pid}/redo/", {}, format="json")
        self.assertIn("tokens", r.json()["plan"]["spec"]["scenes"][0])
        r = self.api.put(f"{self.b}/plans/{pid}/", {"spec": {**r.json()["plan"]["spec"], "intensity": 1.3}, "label": "شدت"}, format="json")
        self.assertEqual(r.json()["plan"]["spec"]["intensity"], 1.3)
        got = self.api.get(f"{self.b}/plans/{pid}/").json()["plan"]
        self.assertGreaterEqual(len(got["history"]), 3)
        bad = self.api.post(f"{self.b}/plans/{pid}/patch/", {"ops": [{"op": "set", "path": "scenes/5/duration", "value": 4}]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("message", bad.json()["error"])
        self.assertEqual(self.api.delete(f"{self.b}/plans/{pid}/").status_code, 204)

    def test_other_users_cannot_touch_it(self):
        plan = self.make()
        o = APIClient()
        o.force_authenticate(self.other)
        self.assertIn(o.get(f"{self.b}/plans/{plan['id']}/").status_code, (403, 404))
        self.assertIn(o.post(f"{self.b}/plans/{plan['id']}/undo/", {}, format="json").status_code, (403, 404))

    def test_chat_edit_uses_rules_when_ai_is_out(self):
        plan = self.make()
        r = self.api.post(f"{self.b}/plans/{plan['id']}/chat/", {"text": "تیتر بزرگ‌تر شود"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d["applied"])
        self.assertEqual(d["source"], "rules")
        self.assertGreater(d["plan"]["spec"]["scenes"][0]["tokens"]["font_scale"], 1.0)
        self.assertNotIn("tokens", d["plan"]["spec"]["scenes"][2])
        r = self.api.post(f"{self.b}/plans/{plan['id']}/chat/", {"text": "بلبل زبان"}, format="json")
        self.assertFalse(r.json()["applied"])
        self.assertIn("نفهمیدم", r.json()["say"])

    def test_chat_edit_uses_the_model_patch_when_it_is_valid(self):
        plan = self.make()

        class Fake:
            def generate(self, prompt, **kw):
                assert kw.get("json_schema"), "the patch schema must be passed"
                return '{"say": "تیتر بزرگ‌تر شد.", "ops": [{"op": "scale", "path": "scenes/0/tokens/font_scale", "factor": 1.25, "default": 1}]}'

        with mock.patch.object(ai, "get_provider", return_value=Fake()):
            r = self.api.post(f"{self.b}/plans/{plan['id']}/chat/", {"text": "تیتر بزرگ‌تر شود"}, format="json")
        d = r.json()
        self.assertEqual(d["source"], "ai")
        self.assertEqual(d["plan"]["spec"]["scenes"][0]["tokens"]["font_scale"], 1.25)

    def test_chat_edit_falls_back_when_the_model_patch_is_invalid(self):
        plan = self.make()

        class Bad:
            def generate(self, prompt, **kw):
                return '{"say": "x", "ops": [{"op": "set", "path": "scenes/9/zzz", "value": 1}]}'

        with mock.patch.object(ai, "get_provider", return_value=Bad()):
            r = self.api.post(f"{self.b}/plans/{plan['id']}/chat/", {"text": "تیتر بزرگ‌تر شود"}, format="json")
        self.assertEqual(r.json()["source"], "rules")
        self.assertTrue(r.json()["applied"])

    def test_render_from_the_plan_links_the_render_to_it(self):
        plan = self.make()
        with mock.patch("apps.motion.tasks.dispatch") as disp:
            r = self.api.post(f"{self.b}/plans/{plan['id']}/render/", {"quality": "540", "target": "site"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        row = MotionRender.objects.get(pk=r.json()["render"]["id"])
        self.assertEqual(row.plan_id, plan["id"])
        self.assertEqual(row.options["quality"], "540")
        self.assertTrue(row.options["qa"])
        self.assertEqual(r.json()["render"]["plan_id"], plan["id"])
        disp.assert_called_once()

    def test_qa_action_runs_and_saves_the_report_and_a_revision(self):
        plan = self.make()
        bad = {**base(), "scenes": [{"type": "list", "duration": 1.2, "title": "فهرستِ پُرکلمه", "items": ["یک جملهٔ نسبتاً بلند برای خواندن", "یک جملهٔ بلندتر برای خواندنِ بیشتر", "سومی هم کمی بلند"]}]}
        self.api.put(f"{self.b}/plans/{plan['id']}/", {"spec": bad}, format="json")
        r = self.api.post(f"{self.b}/plans/{plan['id']}/qa/", {"apply": True, "geometry": False}, format="json")
        self.assertEqual(r.status_code, 202)
        got = self.api.get(f"{self.b}/plans/{plan['id']}/").json()["plan"]
        self.assertEqual(got["qa"]["state"], "done")
        self.assertGreaterEqual(got["qa"]["fixed"], 1)
        self.assertGreater(got["spec"]["scenes"][0]["duration"], 1.2)
        self.assertEqual(got["history"][-1]["source"], "qa")

    def test_prompt_and_rules_routes_keep_working(self):
        r = self.api.post(f"{self.b}/ai/", {"idea": "معرفیِ چغر. سه مزیت. دعوت به ثبت‌نام", "style": "flat-vector", "aspect": "9:16"}, format="json")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["source"], "rules")
        self.assertEqual(d["spec"]["version"], 2)
        self.assertEqual(d["spec"]["platform"], "reels")
        self.assertIn("ai_unavailable" if False else "message", d)
        self.assertTrue(catalog.get(d["spec"]["style"]))
        self.assertTrue(patch.MAX_OPS)

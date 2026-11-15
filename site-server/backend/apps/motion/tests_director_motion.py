"""ابزارِ «motion» ِ کارگردانِ ویدیو: ساختِ صحنه از متنِ ویرایش، رندر، نشستن روی تایم‌لاین به‌صورتِ کلیپ؛ و پلِ استودیوی موشن (رندرِ ساختگی)."""
import json

from django.test import SimpleTestCase, TestCase

from services.editing.director import projectops as ops
from services.editing.director.runner import apply_steps
from services.editing.director.spec import Ctx
from services.editing.director.tools import TOOLS
from services.tests_director import ASSETS, fake_ctx, main_ids, run_tool, with_clip

from . import director_bridge as bridge
from . import specs

MOTION_ASSETS = {
    "video:90": {"ref": "video:90", "title": "موشن", "kind": "video", "duration": 4.0, "has_audio": False, "width": 1080, "height": 1920},
}


def motion_ctx(**over):
    calls = []

    def make_motion(req):
        calls.append(req)
        return {"ref": "video:90", "duration": 4.0}

    kw = {"make_motion": make_motion, "describe": lambda ref: {**ASSETS, **MOTION_ASSETS}.get(ref)}
    kw.update(over)
    ctx = fake_ctx(**kw)
    ctx._calls = calls
    return ctx


class Tool(SimpleTestCase):
    def test_the_tool_is_in_the_catalogue_with_a_model_friendly_entry(self):
        t = TOOLS["motion"]
        self.assertEqual(t.group, "text")
        entry = t.for_model()
        self.assertEqual(set(entry["params"]["kind"]["choices"]), set(bridge.KINDS))
        self.assertIn("title_card", t.does)
        self.assertIn("Use only the texts", t.does)

    def test_a_title_card_is_rendered_and_put_at_the_end_of_the_timeline(self):
        p = with_clip("video:1")
        ctx = motion_ctx()
        new, res = run_tool(p, "motion", {"kind": "title_card", "text": "با چغر، چغر تر شو", "duration": 4}, ctx)
        self.assertTrue(res["ok"], res)
        self.assertEqual(ctx._calls[0]["kind"], "title_card")
        self.assertEqual(ctx._calls[0]["aspect"], "9:16")
        main = sorted(ops.main_track(new)["clips"], key=lambda c: c["at"])
        self.assertEqual(len(main), 2)
        self.assertEqual(main[1]["ref"], "video:90")
        self.assertAlmostEqual(main[1]["at"], main[0]["at"] + ops.clip_length(main[0]), delta=0.05)
        self.assertIn("موشن", res["message"])

    def test_lower_third_goes_on_the_overlay_track_with_the_screen_blend(self):
        p = with_clip("video:1")
        new, res = run_tool(p, "motion", {"kind": "lower_third", "text": "مربی نمونه", "text2": "مربی", "track": "overlay", "at": 1.0}, motion_ctx())
        self.assertTrue(res["ok"], res)
        overlay = [c for t in new["tracks"] for c in t["clips"] if c.get("ref") == "video:90"]
        self.assertEqual(len(overlay), 1)
        self.assertEqual(overlay[0].get("blend"), "screen")
        self.assertEqual(overlay[0]["at"], 1.0)
        self.assertEqual(len(main_ids(new)), 1)

    def test_aspect_follows_the_project_frame(self):
        p = ops.new_project("wide")
        p, r = run_tool(p, "add_clip", {"ref": "video:1", "track": "main", "id": "a"})
        ctx = motion_ctx()
        run_tool(p, "motion", {"kind": "cta", "text": "همین حالا", "text2": "ثبت‌نام"}, ctx)
        self.assertEqual(ctx._calls[0]["aspect"], "16:9")

    def test_without_a_motion_studio_the_step_fails_in_persian_not_the_plan(self):
        p = with_clip("video:1")
        new, res = run_tool(p, "motion", {"kind": "title_card", "text": "سلام"}, fake_ctx())
        self.assertFalse(res["ok"])
        self.assertIn("در دسترس نیست", res["message"])
        self.assertEqual(len(main_ids(new)), 1)

    def test_a_step_that_waits_for_the_node_says_so_so_the_director_fills_it_later(self):
        from services.editing.director.spec import StepError

        def waiting(req):
            raise StepError(bridge.WAITING)

        p = with_clip("video:1")
        new, res = run_tool(p, "motion", {"kind": "stat", "value": "1300", "label": "حرکت"}, motion_ctx(make_motion=waiting))
        self.assertFalse(res["ok"])
        self.assertTrue(res["message"].startswith("در صف"))
        from apps.content.tasks_director import NODE_STEPS

        self.assertIn("motion", NODE_STEPS)

    def test_the_plan_may_mix_motion_with_other_tools(self):
        p = with_clip("video:1")
        new, results = apply_steps(p, [{"tool": "motion", "params": {"kind": "stat", "value": "50", "label": "توکن"}},
                                       {"tool": "add_title", "params": {"text": "سلام"}}], motion_ctx(), platform="reels")
        self.assertTrue(all(r["ok"] for r in results), results)


class Bridge(SimpleTestCase):
    def test_every_kind_builds_a_valid_plan_with_the_given_texts(self):
        cases = [
            ({"kind": "title_card", "text": "با چغر، چغر تر شو"}, "kinetic_title", "با چغر، چغر تر شو"),
            ({"kind": "title_card", "text": "یک عنوانِ بلندتر که هفت کلمه را رد می‌کند و ادامه دارد", "text2": "زیرعنوان"}, "title", "زیرعنوان"),
            ({"kind": "stat", "value": "1300", "label": "حرکت با نامِ فارسی"}, "stat", "حرکت با نامِ فارسی"),
            ({"kind": "list", "text": "چه دارد؟", "items": "برنامهٔ ورزشی\nبرنامهٔ غذایی\nخروجی PDF"}, "checklist", "برنامهٔ غذایی"),
            ({"kind": "cta", "text": "همین حالا شروع کنید", "text2": "ثبت‌نام"}, "cta", "ثبت‌نام"),
            ({"kind": "lower_third", "text": "نامِ مربی", "text2": "مربی"}, "lower_third", "نامِ مربی"),
            ({"kind": "captions", "text": "این جمله کلمه به کلمه زیرنویس می‌شود"}, "captions", "زیرنویس"),
        ]
        for req, typ, needle in cases:
            for aspect in specs.ASPECTS:
                spec = bridge.build_spec({**req, "aspect": aspect, "duration": 4}, {"colors": ["#126F85", "#163F75"]})
                self.assertEqual(spec["scenes"][0]["type"], typ, req)
                self.assertIn(needle, json.dumps(spec["scenes"][0], ensure_ascii=False))
                self.assertEqual(spec["aspect"], aspect)

    def test_nothing_is_invented_and_empty_requests_are_refused(self):
        for bad in ({"kind": "title_card"}, {"kind": "stat"}, {"kind": "list", "text": "x"}, {"kind": "cta"}, {"kind": "lower_third"}, {"kind": "captions"}, {"kind": "evil", "text": "x"}):
            with self.assertRaises(bridge.MotionBridgeError):
                bridge.build_spec(bad, {})

    def test_overlay_clips_are_bare_black_and_white_text(self):
        spec = bridge.build_spec({"kind": "lower_third", "text": "نام", "track": "overlay"}, {"logo": "store-logo", "colors": []})
        self.assertTrue(spec["bare"])
        self.assertFalse(spec["brand"]["show_logo"])
        self.assertEqual(spec["scenes"][0]["tokens"]["text"], "#ffffff")
        plain = bridge.build_spec({"kind": "stat", "value": "5", "label": "x"}, {"logo": "store-logo"})
        self.assertNotIn("bare", plain)

    def test_aspect_of_a_frame(self):
        self.assertEqual(bridge.aspect_of(1080, 1920), "9:16")
        self.assertEqual(bridge.aspect_of(1920, 1080), "16:9")
        self.assertEqual(bridge.aspect_of(1080, 1080), "1:1")
        self.assertEqual(bridge.aspect_of(1080, 1350), "4:5")


class MakeClip(TestCase):
    """make_clip با رندرِ ساختگی: ردیفِ ویدیو در رسانهٔ فروشگاه ساخته و برگردانده می‌شود."""

    def test_a_site_render_stand_in_produces_a_video_ref(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        from django.contrib.auth import get_user_model
        from django.test import override_settings

        from apps.stores.models import Store

        from . import services

        ffmpeg = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        if not Path(ffmpeg).exists():
            self.skipTest("ffmpeg missing")
        media = tempfile.mkdtemp(prefix="nm-bridge-")
        with override_settings(MEDIA_ROOT=media):
            owner = get_user_model().objects.create_user("bridge-owner", password="x")
            store = Store.objects.create(owner=owner, name="چغر", colors={"primary": "#126F85", "secondary": "#163F75"})

            def fake_render(render):
                mp4 = Path(media) / "fake.mp4"
                subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x126F85:s=540x960:d=4:r=30", "-pix_fmt", "yuv420p", str(mp4)], check=True)
                services.finalize(render, mp4)

            res = bridge.make_clip(store, owner, {"kind": "title_card", "text": "سلام چغر", "duration": 4, "aspect": "9:16"}, render_fn=fake_render)
            self.assertTrue(res["ref"].startswith("video:"))
            self.assertGreater(res["duration"], 3)
            from .models import MotionRender

            r = MotionRender.objects.get(pk=res["render_id"])
            self.assertEqual(r.state, "READY")
            self.assertTrue(r.qa)                                    # the rule-based quality check ran before the render
            shutil.rmtree(media, ignore_errors=True)

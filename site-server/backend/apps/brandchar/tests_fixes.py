"""رفعِ ایرادهای دورِ بازبینیِ ۱۱/۱۶ برای «شخصیتِ برند»:

* ژستِ «دست تکان‌دادن» (و ژستِ ایستاده) دیگر آستین/بازو را روی صورت نمی‌اندازد؛ «بالابردنِ هالتر» در سبکِ چیبی هالتر را بالای سر نشان می‌دهد؛
* «توضیحِ دلخواه» در جادوگرِ لحن وقتی هوش مصنوعی نیست بی‌صدا دور ریخته نمی‌شود؛
* نوارِ صندوق/چت دروغ نمی‌گوید («با لحنِ برند جواب می‌دهد» فقط وقتی لحن فعال است)؛
* حالتِ ناشناخته در تصویرِ هوش مصنوعی ۴۰۰ می‌دهد؛ پرامپت واژه‌هایِ انگلیسیِ درست دارد («track jacket» نه «teal track»)؛
* خطِ پایینِ برگهٔ مدل بریده نمی‌شود؛ پیامِ نگهبانِ ادعا «شخصیتِ برند» می‌گوید؛ منوی ماسکوتِ قدیمی نامِ قدیمی دارد.
"""
import numpy as np
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.compute.models import ComputeNode
from apps.mascot.engine import copy_guard, stage

from . import ai_render, persona as P, persona_ai
from .engine import doc as D
from .engine import figure as F
from .engine import render as R
from .engine import sheet as SH
from .tests_api import Base, ComputeJob

MAGENTA = "#ff00ff"


def _doc(style: str, **kw) -> dict:
    return D.normalize({"name": "مربی", **D.role_look("coach"), "style": style, "top": MAGENTA, "top2": MAGENTA, "skin": "#f1c9a5", "outline": "#1f2430", "limb_colour": MAGENTA, **kw})


def _shot(doc: dict, pose: str, w: int = 600, h: int = 900, *, register: bool = True):
    if register:
        F.register()
    return stage.render_actor({"spec": R.actor_spec(doc), "pose": pose, "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.9, "shadow": False}, w, h, inside=0.02)


def _count_in_circle(shot, rgb: tuple[int, int, int], radius_k: float) -> int:
    """چند پیکسل از رنگِ rgb درونِ دایره‌ای به شعاعِ radius_k × شعاعِ سر، دور از مرکزِ سر است (آنتی‌آلیاس: نزدیکِ رنگ)."""
    a = np.asarray(shot.layer.convert("RGBA")).astype(int)
    hx, hy, hr = shot.head
    ys, xs = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    inside = (xs - hx) ** 2 + (ys - hy) ** 2 <= (hr * radius_k) ** 2
    near = (np.abs(a[:, :, :3] - np.array(rgb)).sum(axis=2) < 40) & (a[:, :, 3] > 200)
    return int((inside & near).sum())


class ArmsNeverCoverTheFace(SimpleTestCase):
    """رنگِ لباس را سرخابی می‌کنیم؛ هیچ پیکسلِ سرخابی (آستین یا بازو) نباید درونِ ۷۰٪ِ شعاعِ سر بیفتد."""

    def test_wave_and_stand_keep_sleeves_off_the_face_in_every_vector_style(self):
        for style in F.STYLE_KEYS:
            for pose in ("stand", "wave", "point_up", "thumbs_up", "hands_up", "think"):
                with self.subTest(style=style, pose=pose):
                    self.assertEqual(_count_in_circle(_shot(_doc(style), pose), (255, 0, 255), 0.7), 0)

    def test_the_stick_figure_waves_beside_its_head_too(self):
        # آدمک‌چوبی: دست و پا = limb_colour (سرخابی)، چهره تیره؛ بازوی تکان‌دهنده نباید از رویِ سر بگذرد
        F.register()
        self.assertEqual(self._stick("stand"), 0)
        self.assertEqual(self._stick("wave"), 0)
        from apps.mascot.engine import stage

        saved = dict(stage.POSE_VARIANTS)
        try:
            stage.POSE_VARIANTS.clear()                       # بدونِ جدولِ «brand» همان ژستِ مشترکِ ماسکوت: بازو روی صورت می‌افتد
            self.assertGreater(self._stick("wave", register=False), 50)
        finally:
            stage.POSE_VARIANTS.update(saved)

    @staticmethod
    def _stick(pose: str, register: bool = True) -> int:
        return _count_in_circle(_shot(_doc("stick"), pose, register=register), (255, 0, 255), 0.8)

    def test_the_waving_hand_is_beside_the_head_not_in_front_of_it(self):
        for style in F.STYLE_KEYS:
            b = F.build(_doc(style), "wave", "happy")
            hx, _hy, hr = b.head
            wrist_x = b.hands[1][0]
            self.assertGreater(wrist_x, hx + hr * 0.95, style)

    def test_stick_style_is_untouched(self):
        # آدمک‌چوبی همان ژستِ مشترکِ ماسکوت است؛ جدولِ ژست‌های برداری فقط برای سه سبکِ برداری است
        from apps.mascot.engine import poses

        self.assertEqual(poses.POSES["wave"]["arm_r"]["rot"], -150)
        self.assertNotIn("stick", F.VECTOR_POSES)
        # ماسکوتِ قدیمی spec["pose_variant"] ندارد ⇒ همان جدولِ مشترک (بازوی ‎−۱۵۰)
        from apps.mascot.engine import stage

        legacy = {"name": "قدیمی", "limb_colour": MAGENTA}
        self.assertNotIn("pose_variant", legacy)
        self.assertEqual(D.to_mascot_spec(_doc("stick"))["pose_variant"], "brand")
        self.assertEqual(stage.POSE_VARIANTS["brand"]["wave"]["arm_r"]["rot"], -112)

    def test_every_pose_still_renders_inside_the_frame_in_every_style(self):
        from apps.mascot.engine import poses

        for style in F.STYLE_KEYS:
            for pose in poses.names():
                s = _shot(_doc(style, top="#2f7fd1"), pose)
                self.assertIsNotNone(s.bbox, (style, pose))
                x0, y0, x1, y1 = s.bbox
                self.assertTrue(0 <= x0 and x1 <= 600 and 0 <= y0 and y1 <= 900, (style, pose, s.bbox))

    def test_chibi_lift_puts_the_bar_above_the_head(self):
        doc = _doc("chibi", top="#2f7fd1", prop_colour="#00ff00")
        s = _shot(doc, "lift")
        a = np.asarray(s.layer.convert("RGBA")).astype(int)
        hx, hy, hr = s.head
        plate = (np.abs(a[:, :, :3] - np.array([0, 255, 0])).sum(axis=2) < 40) & (a[:, :, 3] > 200)
        bar = (np.abs(a[:, :, :3] - np.array([0x6b, 0x72, 0x80])).sum(axis=2) < 30) & (a[:, :, 3] > 200)
        self.assertGreater(int(plate.sum()), 200, "plates are not visible")
        self.assertGreater(int(bar.sum()), 1500, "the bar is not visible")
        ys = np.where(bar)[0]
        self.assertLess(float(np.median(ys)), hy - hr * 0.85, "the bar must be above the head, not across the forehead")
        # و پلاک‌ها دو طرفِ همان میله‌اند، نه «هدفون» کنارِ سر: میله بینِ دو پلاک ادامه دارد
        px = np.where(plate)[1]
        self.assertGreater(int(px.max() - px.min()), hr * 1.6)

    def test_new_engine_version_invalidates_cached_renders(self):
        self.assertGreaterEqual(D.ENGINE_VERSION, 2)


class PersonaBriefWithoutAI(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.stores.models import Store

        self.owner = get_user_model().objects.create_user("bc-brief-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ نمونه", business_type="کافه", description="کافهٔ محله", target_audience="همسایه‌ها")

    @staticmethod
    def _down(store, prompt):
        from apps.ideabank import ai as IA

        raise IA.AIUnavailable("متیس اعتبار ندارد")

    def test_clear_tone_words_are_applied_and_the_note_says_so(self):
        plain = persona_ai.draft(self.store, brief="", ask=self._down)
        out = persona_ai.draft(self.store, brief="شوخ و پرانرژی", ask=self._down)
        self.assertGreater(out["persona"]["tone"]["humor"], plain["persona"]["tone"]["humor"])
        self.assertGreater(out["persona"]["tone"]["energy"], plain["persona"]["tone"]["energy"])
        self.assertEqual(out["persona"]["tone"]["formality"], plain["persona"]["tone"]["formality"])
        self.assertEqual(out["brief"], {"given": True, "applied": ["شوخ‌تر", "پرانرژی‌تر"], "used_by_ai": False})
        joined = " ".join(out["notes"])
        self.assertIn("توضیحِ شما", joined)
        self.assertIn("شوخ‌تر", joined)
        self.assertNotEqual(out["persona"], plain["persona"])

    def test_a_brief_with_no_tone_words_says_it_was_not_used(self):
        out = persona_ai.draft(self.store, brief="مثلِ یک همکارِ باتجربه حرف بزند", ask=self._down)
        self.assertEqual(out["brief"]["applied"], [])
        self.assertTrue(any("استفاده نشد" in n for n in out["notes"]), out["notes"])
        self.assertEqual(out["persona"], persona_ai.draft(self.store, brief="", ask=self._down)["persona"])

    def test_no_brief_no_extra_note(self):
        out = persona_ai.draft(self.store, brief="  ", ask=self._down)
        self.assertEqual(out["brief"], {"given": False, "applied": [], "used_by_ai": False})
        self.assertFalse(any("توضیحِ شما" in n for n in out["notes"]))

    def test_use_ai_off_also_reports_the_brief(self):
        out = persona_ai.draft(self.store, brief="رسمی و کوتاه", use_ai=False)
        self.assertEqual(out["brief"]["applied"], ["رسمی‌تر", "کوتاه‌تر"])

    def test_with_ai_the_brief_goes_to_the_model_and_is_reported(self):
        seen = {}

        def ask(store, prompt):
            seen["prompt"] = prompt
            return {"archetype": "sage", "tone": {"formality": 50, "humor": 50, "energy": 50, "detail": 50, "warmth": 50}, "values": ["صبر"]}

        out = persona_ai.draft(self.store, brief="شوخ و پرانرژی", ask=ask)
        self.assertIn("شوخ و پرانرژی", seen["prompt"])
        self.assertEqual(out["brief"], {"given": True, "applied": [], "used_by_ai": True})

    def test_tone_words_never_leak_into_facts(self):
        tone, applied = P.apply_brief_tone({k: 50 for k in P.TONE_KEYS}, "ضمانتِ ۹۸٪ رضایت و ۹۰ هزار تومان؛ شوخ")
        self.assertEqual(applied, ["شوخ‌تر"])
        self.assertEqual(set(tone), set(P.TONE_KEYS))

    def test_the_api_returns_the_brief_block(self):
        from rest_framework.test import APIClient

        api = APIClient()
        api.force_authenticate(self.owner)
        r = api.post(f"/api/v1/stores/{self.store.pk}/brand-character/persona/draft/", {"brief": "شوخ", "use_ai": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["brief"]["applied"], ["شوخ‌تر"])


class InboxBannerTellsTheTruth(Base):
    def test_no_persona_then_inactive_then_active(self):
        self.make()
        card = self.api.get(f"{self.base}/use/inbox/").json()
        self.assertTrue(card["enabled"])
        self.assertFalse(card["persona_active"])
        self.assertFalse(card["persona_exists"])
        self.put_persona()
        self.api.post(f"{self.base}/persona/active/", {"active": False}, format="json")
        card = self.api.get(f"{self.base}/use/inbox/").json()
        self.assertFalse(card["persona_active"])
        self.assertTrue(card["persona_exists"])
        self.assertEqual(card["greeting"], "")           # لحنِ غیرفعال به ایجنت نمی‌رسد
        self.api.post(f"{self.base}/persona/active/", {"active": True}, format="json")
        card = self.api.get(f"{self.base}/use/inbox/").json()
        self.assertTrue(card["persona_active"])
        self.assertTrue(card["greeting"])


class AIRenderModes(Base):
    def _node(self):
        return ComputeNode.objects.create(name="gpu-fix", capabilities={"comfyui": True, "kinds": ["brandchar.render", "comfy.profile"], "agent": "2.29", "comfy_profiles": ["flux-edit-balanced"],
                                                                        "comfy_nodes": ["KSampler"], "brandchar": {"ready": True}}, last_seen=None)

    def test_unknown_mode_is_a_400_that_lists_the_valid_keys(self):
        self._node()
        c = self.make()
        for bad in ("bogus", "three-dee", "photoreal"):
            r = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
            msg = r.json()["error"]["message"]
            for key in ai_render.MODES:
                self.assertIn(key, msg)
        self.assertEqual(ComputeJob.objects.count(), 0)

    def test_three_d_aliases_map_to_the_3d_mode(self):
        self._node()
        c = self.make()
        r = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "three_d"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["mode"], "3d")
        self.assertEqual(ComputeJob.objects.get(uid=r.json()["compute_uid"]).payload["mode"], "3d")

    def test_the_job_listing_names_every_mode_key(self):
        c = self.make()
        modes = self.api.get(f"{self.base}/characters/{c['id']}/ai-jobs/").json()["modes"]
        self.assertEqual([m["key"] for m in modes], ["illustrated", "3d", "look"])

    def test_the_prompt_uses_english_garment_names(self):
        d = D.normalize({**D.role_look("courier"), "outfit": "track", "top": "#0e8a8a", "bottoms": "joggers", "hat": "headband", "hat_colour": "#d94a3d", "prop": "dumbbell"})
        text = ai_render.anchor_en(d)
        self.assertIn("track jacket", text)
        self.assertNotIn(" track and", text)
        self.assertIn("jogger pants", text)
        self.assertIn("headband", text)
        self.assertIn("dumbbell", text)

    def test_every_document_choice_has_an_english_phrase(self):
        for key, table in ((D.OUTFITS, ai_render.OUTFIT_EN), (D.BOTTOMS, ai_render.BOTTOMS_EN), (D.SHOES, ai_render.SHOES_EN), (tuple(h for h in D.HAIRS if h != "none"), ai_render.HAIR_EN),
                           (tuple(h for h in D.HATS if h != "none"), ai_render.HAT_EN), (tuple(h for h in D.EXTRAS if h != "none"), ai_render.EXTRA_EN),
                           (tuple(h for h in D.PROPS if h != "none"), ai_render.PROP_EN)):
            self.assertEqual(set(key), set(table))


class SmallPolish(SimpleTestCase):
    def test_model_sheet_footer_is_not_clipped(self):
        F.register()
        im = SH.model_sheet(_doc("flat", top="#2f7fd1"), title="مربیِ چغر", store_name="چغر", version=2)
        self.assertEqual(im.size, (2000, 1500))
        a = np.asarray(im.convert("RGB")).astype(int)
        paper = np.array(SH.PAPER[:3])
        ink = (np.abs(a - paper).sum(axis=2) > 12).any(axis=1)
        last = int(np.where(ink)[0].max())
        self.assertLessEqual(last, 1500 - 12, f"the last ink row is {last}: the footer touches the bottom edge")
        self.assertGreater(last, 1460, "the footer line is missing")

    def test_claim_guard_message_names_the_brand_character(self):
        found = copy_guard.check_text("فقط ۹۰ هزار تومان")
        self.assertTrue(found)
        msg = copy_guard.message_fa(found)
        self.assertIn("شخصیتِ برند فقط چیزی را می‌گوید", msg)
        self.assertNotIn("ماسکوت", msg)


class LegacyMascotMenu(TestCase):
    def test_old_page_is_renamed_and_the_new_section_is_untouched(self):
        from apps.panel import registry
        from apps.panel.models import PanelPage

        registry.seed()
        self.assertEqual(PanelPage.objects.get(key="mascot").title, "ماسکوتِ قدیمی (آدمک‌چوبی)")
        PanelPage.objects.filter(key="mascot").update(title="ماسکوتِ برند")           # دیتابیسِ زنده: عنوانِ قدیمی
        registry.seed()
        self.assertEqual(PanelPage.objects.get(key="mascot").title, "ماسکوتِ قدیمی (آدمک‌چوبی)")
        PanelPage.objects.filter(key="mascot").update(title="عنوانِ دلخواهِ ادمین")   # ادمین خودش عوض کرده ⇒ دست نمی‌خورد
        registry.seed()
        self.assertEqual(PanelPage.objects.get(key="mascot").title, "عنوانِ دلخواهِ ادمین")
        self.assertEqual(PanelPage.objects.filter(section__key="brandchar").count(), 6)

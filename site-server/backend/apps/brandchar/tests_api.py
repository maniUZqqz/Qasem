"""API ِ شخصیتِ برند: نمای کلی، شخصیتِ گفتار، شخصیتِ دیداری (ساخت، ویرایش، لایه‌ها، قفل و نسخه)، پیش‌نمایش، رندرِ کَش‌دار (۴ اندازه × ۳ سبک)، استیکر، برگه (PNG/PDF)، SVG،
بسته‌یِ خروجی، بررسیِ ثبات، خلقِ هوشمند، قالب‌های پست/استوری، کاربردها (موشن، تامنیل، سایت، کارگردان، صندوق پیام)، تصویرِ هوش مصنوعی (صفِ ماندگار)، دسترسی."""
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.compute import services as C
from apps.compute.models import ComputeJob, ComputeNode
from apps.photoedit.models import PhotoAsset
from apps.stores.models import Membership, Store

from . import persona as P
from . import ai_render, templates
from .engine import doc as D
from .models import BrandCharacter, CharacterAIJob, SiteBinding, UsageEvent

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmbc-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmbc-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("bc-api-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", target_audience="مربی‌های باشگاه", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/brand-character"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def make(self, **kw):
        r = self.api.post(f"{self.base}/characters/", {"role": "coach", "use_logo": False, **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def put_persona(self, data=None):
        r = self.api.put(f"{self.base}/persona/", {"data": data or P.CHAGHER, "source": "facts"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()


class OverviewTests(Base):
    def test_overview_has_everything_the_pages_need(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(b["characters"], [])
        self.assertEqual(len(b["options"]["styles"]), 4)
        self.assertEqual(len(b["options"]["poses"]), 29)
        self.assertEqual(len(b["options"]["expressions"]), 8)
        self.assertEqual(len(b["options"]["sizes"]), 4)
        self.assertEqual(len(b["options"]["backgrounds"]), 17)
        self.assertEqual(len(b["options"]["choices"]["hair"]), 10)
        self.assertEqual({o["key"] for o in b["options"]["choices"]["outfit"]}, set(D.OUTFITS))
        self.assertEqual(b["store"]["colors"], ["#126f85", "#163f75"])
        self.assertTrue(b["has_facts"])
        self.assertFalse(b["persona"]["exists"])
        self.assertEqual({s["key"] for s in b["usage"]["surfaces"]}, {"motion", "thumbnail", "post_template", "inbox", "site_hero", "director", "ai_render", "export"})
        self.assertEqual(len(b["usage"]["injection"]), 7)

    def test_roles_and_access(self):
        c = self.make()
        viewer = User.objects.create_user("bc-v", password="x")
        Membership.objects.create(store=self.store, user=viewer, role="VIEWER")
        marketer = User.objects.create_user("bc-m", password="x")
        Membership.objects.create(store=self.store, user=marketer, role="MARKETING")
        support = User.objects.create_user("bc-s", password="x")
        Membership.objects.create(store=self.store, user=support, role="SUPPORT")
        stranger = User.objects.create_user("bc-x", password="x")
        cl = APIClient()
        cl.force_authenticate(viewer)
        self.assertEqual(cl.get(f"{self.base}/").status_code, 200)
        self.assertEqual(cl.post(f"{self.base}/characters/", {"role": "cook"}, format="json").status_code, 403)
        self.assertEqual(cl.put(f"{self.base}/persona/", {"data": {"name": "x"}}, format="json").status_code, 403)
        self.assertEqual(cl.post(f"{self.base}/characters/{c['id']}/lock/").status_code, 403)
        cl.force_authenticate(marketer)
        self.assertEqual(cl.post(f"{self.base}/characters/", {"role": "cook", "use_logo": False}, format="json").status_code, 201)
        cl.force_authenticate(support)
        self.assertEqual(cl.get(f"{self.base}/").status_code, 403)
        self.assertEqual(cl.get(f"{self.base}/use/inbox/").status_code, 200)              # پشتیبانی آواتارِ صندوق را می‌بیند
        cl.force_authenticate(stranger)
        self.assertIn(cl.get(f"{self.base}/").status_code, (403, 404))
        self.assertEqual(self.api.get(f"/api/v1/stores/{self.store.pk}/brand-character/characters/99999/").status_code, 404)


class PersonaApiTests(Base):
    def test_get_empty_then_put_lock_versions_restore(self):
        r = self.api.get(f"{self.base}/persona/").json()
        self.assertFalse(r["exists"])
        self.assertEqual(len(r["archetypes"]), 12)
        self.assertEqual(len(r["sliders"]), 5)
        self.assertEqual(len(r["emoji_policies"]), 4)
        pub = self.put_persona()
        self.assertTrue(pub["exists"])
        self.assertEqual(pub["data"]["archetype"], "sage")
        self.assertEqual(self.api.post(f"{self.base}/persona/lock/", {}, format="json").json()["version"], 1)
        r = self.api.put(f"{self.base}/persona/", {"data": {"name": "x"}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("قفل", r.json()["error"]["message"])
        self.api.post(f"{self.base}/persona/unlock/", {}, format="json")
        self.api.put(f"{self.base}/persona/", {"data": {"name": "نامِ دوم", "archetype": "hero"}}, format="json")
        self.api.post(f"{self.base}/persona/lock/", {}, format="json")
        self.assertEqual([v["version"] for v in self.api.get(f"{self.base}/persona/versions/").json()["items"]], [2, 1])
        self.api.post(f"{self.base}/persona/unlock/", {}, format="json")
        r = self.api.post(f"{self.base}/persona/restore/", {"version": 1}, format="json").json()
        self.assertEqual(r["data"]["name"], "مربیِ چغر")
        self.assertEqual(self.api.post(f"{self.base}/persona/restore/", {"version": "x"}, format="json").status_code, 400)

    def test_voice_choices_come_from_the_audio_studio_and_a_voice_can_be_saved(self):
        r = self.api.get(f"{self.base}/persona/").json()
        ids = {v["id"] for v in r["voices"]}
        self.assertIn("fa-IR-FaridNeural", ids)
        self.assertIn("fa-IR-DilaraNeural", ids)
        self.assertTrue(all(v["name"] for v in r["voices"]))
        data = {**P.CHAGHER, "voice": {"voice_id": "fa-IR-DilaraNeural", "speed": 1.2, "gender": "female"}}
        pub = self.api.put(f"{self.base}/persona/", {"data": data}, format="json").json()
        self.assertEqual(pub["data"]["voice"], {"voice_id": "fa-IR-DilaraNeural", "speed": 1.2, "gender": "female"})

    def test_draft_wizard_returns_sources_and_works_without_ai(self):
        r = self.api.post(f"{self.base}/persona/draft/", {"use_ai": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(b["origin"], "facts")
        self.assertFalse(b["ai"]["used"])
        self.assertTrue(b["ai"]["reason"])
        self.assertGreaterEqual(len(b["sources"]), 5)
        self.assertEqual(b["persona"]["tagline"], "با چغر چغر تر شو")
        self.assertEqual(b["score"]["missing"], [])
        self.assertIsNone(BrandPersona_row(self.store))                 # پیش‌نویس ذخیره نمی‌شود

    def test_prompt_preview_and_switch(self):
        self.put_persona()
        r = self.api.get(f"{self.base}/persona/prompt/?kind=sales").json()
        self.assertIn("BRAND PERSONA", r["text"])
        self.assertLessEqual(r["chars"], r["limit"])
        self.api.post(f"{self.base}/persona/active/", {"active": False}, format="json")
        self.assertFalse(self.api.get(f"{self.base}/persona/").json()["active"])
        self.assertFalse(self.api.get(f"{self.base}/usage/").json()["persona_active"])


def BrandPersona_row(store):
    from .models import BrandPersona

    return BrandPersona.objects.filter(store=store).first()


class CharacterCrudTests(Base):
    def test_create_each_role_and_style_with_brand_colours(self):
        c = self.make(role="coach", style="chibi", name="مربی")
        self.assertEqual(c["style"], "chibi")
        self.assertEqual(c["doc"]["top"], "#126f85")
        self.assertEqual(c["doc"]["bottom"].lower(), c["doc"]["bottom"])
        self.assertTrue(c["is_primary"])
        for role in ("shopkeeper", "cook", "courier", "advisor"):
            d = self.make(role=role, style="sticker")
            self.assertEqual(d["role"], role)
            self.assertFalse(d["is_primary"])

    def test_limit_of_characters(self):
        for _ in range(8):
            self.make()
        r = self.api.post(f"{self.base}/characters/", {"role": "coach", "use_logo": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("حداکثر", r.json()["error"]["message"])

    def test_patch_doc_merges_and_layers_are_cleaned(self):
        c = self.make()
        layer = {"id": "a", "shape": "ellipse", "anchor": "head", "box": {"cx": 0, "cy": -40, "w": 30, "h": 30}, "fill": "#ff00ff", "link": "b"}
        r = self.api.patch(f"{self.base}/characters/{c['id']}/", {"doc": {"hair": "curly", "outfit": "hoodie", "layers": [layer, {"shape": "zzz"}], "top": "#112233"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()["doc"]
        self.assertEqual((d["hair"], d["outfit"], d["top"]), ("curly", "hoodie", "#112233"))
        self.assertEqual(len(d["layers"]), 1)
        self.assertEqual(d["layers"][0]["anchor"], "head")
        self.assertEqual(d["skin"], c["doc"]["skin"])                    # ادغام، نه جایگزینی

    def test_lock_blocks_edits_versions_restore_and_primary(self):
        a = self.make(name="الف")
        b = self.make(name="ب")
        self.api.patch(f"{self.base}/characters/{a['id']}/", {"doc": {"hair": "long"}}, format="json")
        r = self.api.post(f"{self.base}/characters/{a['id']}/lock/", {}, format="json").json()
        self.assertEqual((r["version"], r["locked"]), (1, True))
        r = self.api.patch(f"{self.base}/characters/{a['id']}/", {"doc": {"hair": "none"}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("قفل", r.json()["error"]["message"])
        self.api.post(f"{self.base}/characters/{a['id']}/unlock/", {}, format="json")
        self.api.patch(f"{self.base}/characters/{a['id']}/", {"doc": {"hair": "none"}}, format="json")
        self.api.post(f"{self.base}/characters/{a['id']}/lock/", {}, format="json")
        self.assertEqual([v["version"] for v in self.api.get(f"{self.base}/characters/{a['id']}/versions/").json()["items"]], [2, 1])
        self.api.post(f"{self.base}/characters/{a['id']}/unlock/", {}, format="json")
        r = self.api.post(f"{self.base}/characters/{a['id']}/restore/", {"version": 1}, format="json").json()
        self.assertEqual(r["doc"]["hair"], "long")
        self.api.post(f"{self.base}/characters/{b['id']}/primary/", {}, format="json")
        got = {c["id"]: c["is_primary"] for c in self.api.get(f"{self.base}/characters/").json()["items"]}
        self.assertEqual(got, {a["id"]: False, b["id"]: True})
        self.api.delete(f"{self.base}/characters/{b['id']}/")
        self.assertTrue(self.api.get(f"{self.base}/characters/{a['id']}/").json()["is_primary"])

    def test_role_change_rebuilds_the_look_and_from_mascot_imports(self):
        c = self.make(role="coach")
        r = self.api.patch(f"{self.base}/characters/{c['id']}/", {"role": "cook"}, format="json").json()
        self.assertEqual(r["doc"]["extra"], "apron")
        from apps.mascot.models import Mascot
        from apps.mascot.engine import brand as B

        m = Mascot.objects.create(store=self.store, name="ماسکوتِ قدیمی", role="advisor", spec=B.spec_from_brand("advisor", ["#126f85", "#163f75"], "x"))
        r = self.api.post(f"{self.base}/characters/", {"from_mascot": m.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["doc"]["extra"], "glasses")
        self.assertEqual(r.json()["mascot"], m.pk)

    def test_publish_to_the_old_mascot_page(self):
        c = self.make()
        mid = self.api.post(f"{self.base}/characters/{c['id']}/publish-mascot/", {}, format="json").json()["mascot"]
        from apps.mascot.models import Mascot

        self.assertEqual(Mascot.objects.get(pk=mid).spec["hat"], c["doc"]["hat"])
        self.assertEqual(self.api.post(f"{self.base}/characters/{c['id']}/publish-mascot/", {}, format="json").json()["mascot"], mid)


class RenderTests(Base):
    def test_preview_with_unsaved_doc_has_qa_and_claims(self):
        c = self.make(style="flat")
        r = self.api.post(f"{self.base}/characters/{c['id']}/preview/", {"pose": "wave", "doc": {"hair": "bun", "outfit": "hoodie"}, "bubble": {"text": "فقط ۹۹ هزار تومان", "kind": "say"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertTrue(b["image"].startswith("data:image/jpeg;base64,"))
        self.assertTrue(b["qa"]["ok"], b["qa"])
        self.assertEqual(b["claims"][0]["code"], "price")
        self.assertEqual(self.api.get(f"{self.base}/characters/{c['id']}/").json()["doc"]["hair"], c["doc"]["hair"])    # ذخیره نشد

    def test_render_every_size_for_every_style_is_cached_and_registered(self):
        for style in ("flat", "chibi", "sticker", "stick"):
            c = self.make(style=style)
            for size, (w, h) in {"ig_portrait": (1080, 1350), "ig_square": (1080, 1080), "story": (1080, 1920), "wide": (1920, 1080)}.items():
                body = {"pose": "thumbs_up", "expression": "happy", "background": "brand", "size": size, "bubble": {"text": "سلام!", "kind": "say"}}
                r = self.api.post(f"{self.base}/characters/{c['id']}/render/", body, format="json")
                self.assertEqual(r.status_code, 201, (style, size, r.content))
                self.assertEqual((r.json()["width"], r.json()["height"]), (w, h))
                self.assertTrue(r.json()["qa"]["ok"], (style, size, r.json()["qa"]))
            again = self.api.post(f"{self.base}/characters/{c['id']}/render/", body, format="json")
            self.assertEqual(again.status_code, 200)
            self.assertTrue(again.json()["cached"])
        self.assertEqual(PhotoAsset.objects.filter(store=self.store, source_ref__startswith="brandchar:").count(), 16)

    def test_claims_block_the_render_unless_confirmed(self):
        c = self.make()
        body = {"pose": "stand", "caption": {"text": "۵۰٪ تخفیف", "position": "top"}}
        r = self.api.post(f"{self.base}/characters/{c['id']}/render/", body, format="json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "claims")
        ok = self.api.post(f"{self.base}/characters/{c['id']}/render/", {**body, "allow_claims": True}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertTrue(ok.json()["params"]["claims_confirmed"])

    def test_sticker_is_transparent_in_full_and_bust(self):
        c = self.make(style="chibi")
        for crop in ("full", "bust"):
            r = self.api.post(f"{self.base}/characters/{c['id']}/sticker/", {"pose": "wave", "crop": crop}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            a = PhotoAsset.objects.get(pk=r.json()["asset"]["id"])
            self.assertTrue(a.has_alpha)
        self.assertEqual(self.api.post(f"{self.base}/characters/{c['id']}/sticker/", {"pose": "nope"}, format="json").status_code, 400)

    def test_sheet_pdf_svg_and_downloads(self):
        self.put_persona()
        c = self.make(style="flat")
        r = self.api.post(f"{self.base}/characters/{c['id']}/sheet/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["width"], r.json()["height"]), (2000, 1500))
        dl = self.api.get(r.json()["urls"]["download"])
        self.assertEqual(dl.status_code, 200)
        self.assertTrue(b"".join(dl.streaming_content).startswith(b"\x89PNG"))
        p = self.api.post(f"{self.base}/characters/{c['id']}/sheet-pdf/", {}, format="json")
        self.assertEqual(p.status_code, 201, p.content)
        pdf = self.api.get(p.json()["urls"]["download"])
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        s = self.api.post(f"{self.base}/characters/{c['id']}/svg-file/", {"pose": "wave", "background": "#ffffff"}, format="json")
        self.assertEqual(s.status_code, 201, s.content)
        svg = self.api.get(s.json()["urls"]["download"])
        self.assertEqual(svg["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", svg.content)
        self.assertFalse(s.json()["params"]["embedded"])
        live = self.api.post(f"{self.base}/characters/{c['id']}/svg/", {"pose": "stand", "doc": {"hat": "cap"}}, format="json").json()
        self.assertIn("<svg", live["svg"])
        self.assertEqual(set(live["anchors"]), {"world", "head", "body", "hand"})
        items = self.api.get(f"{self.base}/characters/{c['id']}/renders/?kind=pdf").json()["items"]
        self.assertEqual(len(items), 1)

    def test_export_zip_has_every_deliverable(self):
        self.put_persona()
        c = self.make(style="sticker")
        r = self.api.post(f"{self.base}/characters/{c['id']}/export/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(z.namelist())
        for need in ("model-sheet.png", "model-sheet.pdf", "character.json", "palette.json", "persona.json", "README-fa.txt"):
            self.assertIn(need, names)
        self.assertEqual(len([n for n in names if n.startswith("svg/")]), 8)
        self.assertEqual(len([n for n in names if n.startswith("sticker-png/")]), 8)
        im = Image.open(io.BytesIO(z.read("sticker-png/wave.png")))
        self.assertEqual(im.mode, "RGBA")
        self.assertIn("export", {e.surface for e in UsageEvent.objects.filter(store=self.store)})

    def test_check_runs_all_poses_and_sizes(self):
        c = self.make(style="chibi")
        r = self.api.post(f"{self.base}/characters/{c['id']}/check/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertTrue(b["ok"], b["failed"])
        self.assertEqual(b["total"], 29 * 4 + 5)
        self.assertEqual(self.api.get(f"{self.base}/characters/{c['id']}/").json()["check"]["ok"], True)

    def test_works_with_no_network_no_node_no_ai(self):
        import socket
        from unittest import mock

        def deny(*a, **k):
            raise AssertionError("network used")

        c = self.make()
        with mock.patch.object(socket.socket, "connect", deny), mock.patch.object(C, "enqueue", deny), mock.patch.object(C, "enqueue_durable", deny):
            self.assertEqual(self.api.post(f"{self.base}/characters/{c['id']}/render/", {"pose": "stand"}, format="json").status_code, 201)
            self.assertEqual(self.api.post(f"{self.base}/characters/{c['id']}/sheet/", {}, format="json").status_code, 201)
        self.assertEqual(ComputeJob.objects.count(), 0)


class ConceptTests(Base):
    def test_persian_description_becomes_four_concepts_with_previews(self):
        r = self.api.post(f"{self.base}/concepts/", {"description": "مربیِ خندانِ موبلند با هدبندِ فیروزه‌ای و دمبل، لباس قرمز"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        b = r.json()
        self.assertEqual(b["source"], "rule")
        self.assertIn("هوش مصنوعی", b["note"])
        self.assertEqual(len(b["options"]), 4)
        self.assertEqual([o["doc"]["style"] for o in b["options"]][:2], ["flat", "chibi"])
        for o in b["options"]:
            self.assertEqual(o["doc"]["hair"], "long")
            self.assertEqual(o["doc"]["hat"], "headband")
            self.assertEqual(o["doc"]["prop"], "dumbbell")
            self.assertEqual(o["doc"]["top"], "#d94a3d")
            self.assertTrue(o["preview"].startswith("data:image/png;base64,"))
        self.assertGreaterEqual(len({o["doc"]["style"] for o in b["options"]}), 3)

    def test_too_short_description_is_refused_in_persian(self):
        r = self.api.post(f"{self.base}/concepts/", {"description": "ab"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_choose_makes_a_character_and_its_model_sheet(self):
        cid = self.api.post(f"{self.base}/concepts/", {"description": "فروشندهٔ عینکی با کلاه"}, format="json").json()["id"]
        r = self.api.post(f"{self.base}/concepts/{cid}/choose/", {"index": 1, "name": "فروشندهٔ ما"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        b = r.json()
        self.assertEqual(b["character"]["name"], "فروشندهٔ ما")
        self.assertEqual(b["character"]["style"], "chibi")
        self.assertEqual(b["character"]["doc"]["extra"], "glasses")
        self.assertEqual(b["sheet"]["kind"], "sheet")
        self.assertEqual(b["character"]["concept"]["description"], "فروشندهٔ عینکی با کلاه")
        self.assertEqual(self.api.get(f"{self.base}/concepts/").json()["items"][0]["chosen"], 1)

    def test_ai_answer_is_clamped_to_the_library(self):
        from . import concepts

        def ask(store, prompt):
            self.assertIn("Persian description", prompt)
            return {"concepts": [{"title": "الف", "why": "چون", "traits": {"hair": "dragon", "outfit": "suit", "style": "chibi", "top": "#abcdef", "skin": "nonsense", "layers": [1]}}] * 2}

        out = concepts.generate(self.store, "مشاور", ask=ask, n=4)
        self.assertEqual(out["source"], "ai")
        self.assertEqual(len(out["options"]), 4)                              # با قاعده‌محور کامل شد
        d = out["options"][0]["doc"]
        self.assertEqual((d["outfit"], d["style"], d["top"]), ("suit", "chibi", "#abcdef"))
        self.assertNotEqual(d["hair"], "dragon")
        self.assertEqual(d["skin"], D.DEFAULTS["skin"])
        self.assertEqual(d["layers"], [])

    def test_ai_402_falls_back_with_a_reason(self):
        from . import concepts

        def boom(store, prompt):
            raise RuntimeError("HTTP 402")

        out = concepts.generate(self.store, "مربی", ask=boom)
        self.assertEqual(out["source"], "rule")
        self.assertIn("402", out["note"])
        self.assertEqual(len(out["options"]), 4)


class TemplateAndUsageTests(Base):
    databases = {"default", "studio"}

    def test_ten_templates_each_render_with_persona_text(self):
        self.put_persona()
        c = self.make(style="flat")
        lst = self.api.get(f"{self.base}/templates/").json()
        self.assertEqual(len(lst["items"]), 10)
        by = {t["id"]: t for t in lst["items"]}
        self.assertEqual(by["slogan"]["caption"], "با چغر چغر تر شو")
        self.assertEqual(by["greet"]["bubble"], P.CHAGHER["greeting"])
        sizes = {t["size"] for t in lst["items"]}
        self.assertEqual(sizes, {"ig_portrait", "ig_square", "story", "wide"})
        for tid, t in by.items():
            r = self.api.post(f"{self.base}/templates/{tid}/render/", {}, format="json")
            self.assertEqual(r.status_code, 201, (tid, r.content))
            self.assertEqual((r.json()["width"], r.json()["height"]), (t["w"], t["h"]))
            self.assertEqual(r.json()["kind"], "template")
        self.assertEqual(self.api.post(f"{self.base}/templates/nope/render/", {}, format="json").status_code, 404)
        self.assertEqual(UsageEvent.objects.filter(store=self.store, surface="post_template").count(), 10)
        self.assertEqual(c["id"], lst["character"])

    def test_template_without_a_persona_uses_clean_generic_lines_and_hides_the_slogan(self):
        self.make()
        lst = self.api.get(f"{self.base}/templates/").json()["items"]
        self.assertEqual(len(lst), 8)
        self.assertFalse({"slogan", "wide_cover"} & {t["id"] for t in lst})
        from apps.mascot.engine import copy_guard

        for t in lst:
            self.assertEqual(copy_guard.check_text(t["bubble"] + " " + t["caption"]), [])

    def test_user_text_with_a_claim_is_refused_in_a_template(self):
        self.make()
        r = self.api.post(f"{self.base}/templates/tip/render/", {"bubble_text": "فقط ۱۰۰ هزار تومان"}, format="json")
        self.assertEqual(r.status_code, 422)

    def test_motion_scene_has_poses_text_and_valid_refs(self):
        self.put_persona()
        c = self.make()
        r = self.api.post(f"{self.base}/use/motion/", {"action": "point", "text": "این را ببین", "enter": "left", "side": "right"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        s = r.json()
        self.assertEqual(s["type"], "brand_character")
        self.assertEqual((s["action"], s["text"], s["bubble"]), ("point", "این را ببین", True))
        for key in ("image_a", "image_b"):
            self.assertRegex(s[key], r"^photo:\d+$")
            self.assertTrue(PhotoAsset.objects.get(pk=int(s[key].split(":")[1])).has_alpha)
        self.assertEqual(s["name"], "مربیِ چغر")
        self.assertEqual(c["id"], BrandCharacter.objects.get(store=self.store).pk)

    def test_motion_component_is_registered_and_its_sample_validates(self):
        from apps.motion import components, specs

        comp = components.COMPONENTS["brand_character"]
        self.assertTrue(comp["overlay"])
        spec = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "lang": "fa", "fps": 30, "scenes": [comp["sample"]]})
        self.assertEqual(spec["scenes"][0]["type"], "brand_character")

    def test_thumbnail_subject_is_a_transparent_bust_and_links_the_maker(self):
        self.put_persona()
        self.make()
        r = self.api.post(f"{self.base}/use/thumbnail/", {"pose": "thumbs_up"}, format="json").json()
        self.assertTrue(PhotoAsset.objects.get(pk=r["asset"]).has_alpha)
        self.assertIn(f"/stores/{self.store.pk}/thumbnails?subject={r['asset']}", r["open"])
        self.assertEqual(r["title"], "با چغر چغر تر شو")

    def test_site_hero_binds_the_project_and_returns_block_props(self):
        self.put_persona()
        self.make()
        r = self.api.post(f"{self.base}/use/site-hero/", {"project_slug": "chagher-site"}, format="json").json()
        self.assertIn(".png", r["image"])
        self.assertEqual(r["title"], "با چغر چغر تر شو")
        self.assertFalse(r["bound"])                                         # سایت‌ساز ابزارِ کارکنان است
        self.assertFalse(SiteBinding.objects.filter(project_slug="chagher-site").exists())
        User.objects.filter(pk=self.owner.pk).update(is_staff=True)
        self.owner.refresh_from_db()
        self.api.force_authenticate(self.owner)
        r = self.api.post(f"{self.base}/use/site-hero/", {"project_slug": "chagher-site"}, format="json").json()
        self.assertTrue(r["bound"])
        self.assertEqual(SiteBinding.objects.get(project_slug="chagher-site").store, self.store)

    def test_site_hero_imports_the_picture_into_the_project_media_and_the_block_renders_it(self):
        from apps.projects.models import Project

        self.put_persona()
        self.make()
        User.objects.filter(pk=self.owner.pk).update(is_staff=True)
        self.owner.refresh_from_db()
        self.api.force_authenticate(self.owner)
        (self.media / "ws").mkdir(exist_ok=True)
        with override_settings(WORKSPACES_ROOT=self.media / "ws"):
            project = Project.objects.create(name="سایتِ چغر", slug="chagher-site2")
            r = self.api.post(f"{self.base}/use/site-hero/", {"project_slug": project.slug}, format="json").json()
        self.assertRegex(r["image"], r"^m:\d+$")
        from apps.projects.builder import catalog as BC

        self.assertIn("brand_hero", BC.BLOCKS)

    def test_site_builder_brand_hero_block_exists_and_renders_the_character(self):
        from apps.projects.builder import catalog

        self.assertIn("brand_hero", catalog.BLOCKS)
        keys = {f["key"] for f in catalog.BLOCKS["brand_hero"]["fields"]}
        self.assertTrue({"title", "subtitle", "image", "bubble", "btn1"} <= keys)
        from apps.projects.builder import clean, render as BR

        b = clean.new_block("brand_hero")
        b["props"].update({"image": "/media/brand-character.png", "title": "تیترِ آزمون", "bubble": "سلام از شخصیتِ برند!", "side": "start"})
        html = BR.render_doc(clean.clean_doc({"version": 1, "blocks": [b]}), BR.Ctx(canvas=False)).html
        self.assertIn('class="nb-bubble">سلام از شخصیتِ برند!', html)
        self.assertIn('<img src="/media/brand-character.png"', html)
        self.assertIn("nb-hero-split is-start", html)
        self.assertIn("تیترِ آزمون", html)

    def test_director_overlay_has_five_transparent_stickers(self):
        self.make()
        r = self.api.post(f"{self.base}/use/director/", {}, format="json").json()
        self.assertEqual([i["key"] for i in r["items"]], ["intro", "point", "explain", "ok", "outro"])
        for i in r["items"]:
            self.assertTrue(PhotoAsset.objects.get(pk=i["asset"]).has_alpha)

    def test_inbox_card_has_avatar_and_the_persona_greeting(self):
        self.assertFalse(self.api.get(f"{self.base}/use/inbox/").json()["enabled"])
        self.put_persona()
        self.make()
        r = self.api.get(f"{self.base}/use/inbox/").json()
        self.assertTrue(r["enabled"])
        self.assertEqual(r["greeting"], P.CHAGHER["greeting"])
        self.assertEqual(r["signoff"], P.CHAGHER["signoff"])
        self.assertTrue(r["avatar"])

    def test_every_usage_surface_is_counted_and_listed(self):
        self.put_persona()
        self.make()
        self.api.post(f"{self.base}/use/motion/", {}, format="json")
        self.api.post(f"{self.base}/use/thumbnail/", {}, format="json")
        self.api.post(f"{self.base}/use/director/", {}, format="json")
        self.api.post(f"{self.base}/templates/tip/render/", {}, format="json")
        u = self.api.get(f"{self.base}/usage/").json()
        counts = {s["key"]: s["count"] for s in u["surfaces"]}
        for k in ("motion", "thumbnail", "director", "post_template"):
            self.assertGreaterEqual(counts[k], 1, k)
        self.assertGreaterEqual(len(u["recent"]), 4)
        self.assertTrue(all(i["active"] for i in u["injection"]))

    def test_use_without_a_character_is_a_clear_persian_error(self):
        r = self.api.post(f"{self.base}/use/motion/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("شخصیتِ دیداری", r.json()["error"]["message"])


class AIRenderTests(Base):
    def _node(self, online=False, ready=True):
        caps = {"comfyui": True, "kinds": ["brandchar.render", "comfy.profile"], "agent": "2.27", "comfy_profiles": ["flux-edit-balanced", "flux-product-balanced"],
                "comfy_nodes": ["KSampler", "ApplyPulidFlux"], "brandchar": {"ready": ready}}
        n = ComputeNode.objects.create(name="gpu-bc", capabilities=caps, last_seen=timezone.now() if online else None)
        return n

    def test_no_registered_node_is_a_clear_persian_error_and_nothing_is_queued(self):
        c = self.make()
        r = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "illustrated"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("سرورِ پردازش", r.json()["error"]["message"])
        self.assertEqual(ComputeJob.objects.count(), 0)

    def test_node_off_job_waits_in_the_durable_queue_with_a_persian_status(self):
        self._node(online=False)
        c = self.make()
        r = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "3d", "pose": "wave", "extra": "پس‌زمینهٔ ساده"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        b = r.json()
        self.assertEqual(b["state"], "queued")
        self.assertIn("خاموش", b["message"])
        job = ComputeJob.objects.get(uid=b["compute_uid"])
        self.assertEqual(job.kind, "brandchar.render")
        self.assertEqual(job.state, ComputeJob.State.QUEUED)
        self.assertEqual(job.payload["mode"], "3d")
        self.assertIn("3D", job.payload["prompt"])
        self.assertIn("reference.png", job.inputs)
        self.assertEqual(job.payload["denoise"], ai_render.MODES["3d"]["denoise"])
        jobs = self.api.get(f"{self.base}/characters/{c['id']}/ai-jobs/").json()
        self.assertEqual(jobs["items"][0]["state"], "queued")
        self.assertFalse(jobs["node"]["online"])
        self.assertTrue(jobs["node"]["known"])
        self.assertEqual(jobs["node"]["identity_tools"], ["pulid"])
        self.assertEqual(jobs["node"]["profiles"], ["flux-edit-balanced", "flux-product-balanced"])

    def test_the_kind_is_routed_only_to_nodes_that_advertise_it_and_waits_when_not_ready(self):
        old = ComputeNode.objects.create(name="old", capabilities={"comfyui": True, "kinds": ["comfy.profile"], "agent": "2.26"}, last_seen=timezone.now())
        job = ComputeJob(kind="brandchar.render", payload={})
        self.assertTrue(C.kind_unsupported(old, job))
        self.assertTrue(C.job_blocked(old, job))
        ok = self._node(online=True, ready=True)
        self.assertFalse(C.job_blocked(ok, job))
        waiting = ComputeNode.objects.create(name="noflux", capabilities={"comfyui": True, "kinds": ["brandchar.render"], "agent": "2.27", "brandchar": {"ready": False}}, last_seen=timezone.now())
        self.assertTrue(C.job_blocked(waiting, job))
        self.assertEqual(C.capability_for("brandchar.render"), "comfyui")

    def test_finished_job_becomes_an_asset_a_sticker_and_a_consistency_check(self):
        self._node(online=True)
        c = self.make(style="flat")
        row = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "illustrated"}, format="json").json()
        job = ComputeJob.objects.get(uid=row["compute_uid"])
        # گره «آزاد کرد»: یک تصویرِ نقاشی‌شده با رنگ‌های شخصیت روی زمینهٔ ساده
        from .engine import render as R
        from . import selftest

        doc = selftest.chagher_doc("flat")
        fake, _ = R.sticker(doc, pose="stand", expression="happy", height_px=900)
        bg = Image.new("RGB", (1024, 1024), (236, 238, 242))
        fake.thumbnail((900, 940))
        bg.paste(fake, ((1024 - fake.width) // 2, 40), fake)
        path = C.output_path(job, "image_00001_.png")
        bg.save(path)
        job.state = ComputeJob.State.COMPLETED
        job.result = {"outputs": [{"name": "image_00001_.png", "path": "outputs/image_00001_.png", "size": path.stat().st_size, "media": "image"}], "meta": {}}
        job.save()
        jobs = self.api.get(f"{self.base}/characters/{c['id']}/ai-jobs/").json()["items"]
        self.assertEqual(jobs[0]["state"], "done", jobs[0])
        self.assertTrue(jobs[0]["asset"]["url"])
        self.assertTrue(PhotoAsset.objects.get(pk=jobs[0]["sticker"]["id"]).has_alpha)
        chk = jobs[0]["check"]
        self.assertIsNotNone(chk["palette_score"])
        self.assertGreaterEqual(chk["silhouette"], 0.4)
        self.assertTrue(chk["ok"], chk)
        again = self.api.get(f"{self.base}/characters/{c['id']}/ai-jobs/").json()["items"]
        self.assertEqual(again[0]["state"], "done")
        self.assertEqual(PhotoAsset.objects.filter(source_ref__startswith="brandchar:").count(), 2)

    def test_a_drifting_ai_image_is_flagged(self):
        from . import selftest

        doc = selftest.chagher_doc("flat")
        wrong = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
        from PIL import ImageDraw

        ImageDraw.Draw(wrong).ellipse((40, 40, 360, 460), fill=(240, 30, 120, 255))
        res = ai_render.consistency(doc, wrong, None)
        self.assertFalse(res["ok"])
        self.assertTrue(res["notes"])

    def test_failed_job_shows_the_error(self):
        self._node(online=True)
        c = self.make()
        row = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "illustrated"}, format="json").json()
        ComputeJob.objects.filter(uid=row["compute_uid"]).update(state=ComputeJob.State.FAILED, error="ComfyUI execution error: out of memory")
        jobs = self.api.get(f"{self.base}/characters/{c['id']}/ai-jobs/").json()["items"]
        self.assertEqual(jobs[0]["state"], "failed")
        self.assertIn("out of memory", jobs[0]["error"])

    def test_look_mode_uses_the_looks_library_and_refuses_unknown_looks(self):
        self._node(online=False)
        c = self.make()
        from apps.looks import library

        key = next(iter(library.STYLES))
        r = self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "look", "look": key}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["look"], key)
        self.assertTrue(r.json()["look_fa"])
        self.assertEqual(self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "look", "look": "nope"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/characters/{c['id']}/ai-render/", {"mode": "look"}, format="json").status_code, 400)

    def test_the_prompt_carries_the_identity_of_the_locked_character_only(self):
        c = self.make()
        p = ai_render.build_prompt(c["doc"], "illustrated")
        self.assertIn("cartoon", p["positive"])
        self.assertIn(c["doc"]["hair"], p["positive"])
        self.assertIn("real person", p["negative"])

    def test_key_background_makes_the_plain_background_transparent_but_keeps_the_body(self):
        from PIL import ImageDraw

        im = Image.new("RGB", (200, 200), (236, 238, 242))
        ImageDraw.Draw(im).ellipse((50, 30, 150, 190), fill=(236, 238, 242))        # بدنِ هم‌رنگِ زمینه، ولی بسته به لبه‌ها وصل نیست
        ImageDraw.Draw(im).rectangle((60, 40, 140, 180), fill=(18, 111, 133))
        out = ai_render.key_background(im)
        self.assertEqual(out.getpixel((5, 5))[3], 0)
        self.assertEqual(out.getpixel((100, 100))[3], 255)


class DirectorToolTests(Base):
    """ابزارِ «شخصیتِ برند» در کارگردانِ ویدیو: ثبت شده، با شخصیتِ اصلی کار می‌کند، بدونِ شخصیت پیامِ فارسیِ روشن می‌دهد."""

    def _ctx(self):
        from services.editing.director.spec import Ctx

        def describe(ref):
            a = PhotoAsset.objects.filter(pk=int(ref.split(":")[1]), store=self.store).first()
            return {"ref": ref, "title": a.title, "kind": "image", "width": a.width, "height": a.height, "has_audio": False, "duration": 0.0, "source": "photo"}

        return Ctx(describe=describe, store=self.store)

    def test_tool_is_registered_with_persian_title_and_params(self):
        from services.editing.director import tools

        t = tools.TOOLS["brand_character"]
        self.assertEqual(t.title, "شخصیتِ برند")
        self.assertEqual({p.name for p in t.params}, {"action", "corner", "size", "at", "duration"})
        self.assertIn("brand_character", {x["tool"] for x in tools.catalogue_for_ui()})

    def test_the_tool_pins_a_transparent_sticker_of_the_primary_character(self):
        from services.editing.director import projectops as ops
        from services.editing.director.runner import apply_steps

        self.make()
        p = ops.new_project("reel")
        new, res = apply_steps(p, [{"tool": "brand_character", "params": {"action": "ok", "corner": "bl", "size": 0.3, "at": 0, "duration": "3"}}], self._ctx(), platform="reels")
        self.assertTrue(res[0]["ok"], res[0])
        clips = [c for t in new["tracks"] for c in t["clips"] if str(c.get("ref", "")).startswith("photo:")]
        self.assertEqual(len(clips), 1)
        a = PhotoAsset.objects.get(pk=int(clips[0]["ref"].split(":")[1]))
        self.assertTrue(a.has_alpha)
        self.assertAlmostEqual(clips[0]["width"], 0.3, places=2)
        self.assertEqual(UsageEvent.objects.filter(store=self.store, surface="director").count(), 1)

    def test_without_a_character_the_step_fails_with_a_clear_message(self):
        from services.editing.director import projectops as ops
        from services.editing.director.runner import apply_steps

        new, res = apply_steps(ops.new_project("reel"), [{"tool": "brand_character", "params": {}}], self._ctx(), platform="reels")
        self.assertFalse(res[0]["ok"])
        self.assertIn("شخصیتِ برندی ساخته نشده", res[0]["message"])

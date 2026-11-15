"""ماسکوت ⇄ بقیهٔ NM: تامنیل‌ساز (استیکرِ شفاف = سوژهٔ آماده، بدونِ حذفِ پس‌زمینه)، کتابخانهٔ ادیتورِ عکس، استودیوی موشن (``photo:<id>``)، آزمونِ خودکارِ سرورِ پردازش،
فرمان‌های manage.py و ثبتِ صفحه در پنل."""
import io
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

import numpy as np
from django.core.management import CommandError, call_command
from PIL import Image

from apps.photoedit.models import PhotoAsset

from . import selftest
from .engine import brand as B
from .tests_api import MascotApiBase


class ThumbnailSubjectTests(MascotApiBase):
    def sticker(self, mid, **kw):
        r = self.api.post(f"{self.base}/{mid}/sticker/", {"pose": "thumbs_up", "crop": "bust", **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_the_sticker_is_a_ready_subject_and_no_matting_job_is_made(self):
        from apps.compute.models import ComputeJob
        from apps.photoedit import matting_nodes as mn
        from apps.thumbs import cutout

        m = self.create()
        st = self.sticker(m["id"])
        asset = PhotoAsset.objects.get(pk=st["asset"]["id"])
        img, is_cut, note = None, None, None
        with mock.patch.object(cutout.matting, "available", return_value=True), \
                mock.patch.object(cutout.matting, "alpha", side_effect=AssertionError("the sticker must not be matted")) as alpha, \
                mock.patch.object(mn, "request", side_effect=AssertionError("no node cutout job")):
            img, is_cut, note = cutout.ensure(self.store, asset, allow_site=True)
            self.assertEqual((is_cut, note), (True, ""))
            self.assertEqual(alpha.call_count, 0)
            base = f"/api/v1/stores/{self.store.pk}/thumbnails"
            spec = {"format": "youtube", "style": "face_text", "content": {"title": "با چغر، *چغر‌تر* شو"}, "subject": {"asset": asset.pk, "mode": "cutout"}}
            r = self.api.post(f"{base}/preview/", {"spec": spec}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertTrue(any(l["kind"] == "subject" for l in r.json()["layers"]), r.json()["layers"])
            made = self.api.post(f"{base}/render/", {"spec": spec, "variants": 1}, format="json")
            self.assertEqual(made.status_code, 201, made.content)
            self.assertEqual(alpha.call_count, 0)
        self.assertEqual(ComputeJob.objects.count(), 0)
        self.assertEqual(made.json()["items"][0]["state"], "READY")

    def test_control_an_opaque_photo_would_be_matted(self):
        """نمونهٔ شاهد: همین مسیر برای یک عکسِ معمولی، برش می‌خواهد؛ پس «بدونِ برش» بودنِ استیکر واقعاً از شفافیتش است."""
        from apps.thumbs import cutout

        m = self.create()
        shot = self.render(m["id"], size="ig_square").json()
        noisy = Image.fromarray(np.random.default_rng(3).integers(0, 255, (400, 400, 3), dtype=np.uint8), "RGB")
        buf = io.BytesIO()
        noisy.save(buf, "PNG")
        from apps.photoedit import services as photo

        opaque = photo._asset_from_bytes(self.store, self.owner, buf.getvalue(), title="عکس")
        with mock.patch.object(cutout.matting, "available", return_value=True), mock.patch.object(cutout.matting, "alpha", return_value=None) as alpha:
            cutout.ensure(self.store, opaque, allow_site=True)
        self.assertEqual(alpha.call_count, 1)
        self.assertFalse(PhotoAsset.objects.get(pk=shot["asset"]["id"]).has_alpha)

    def test_the_thumbnail_library_can_include_the_sticker_that_was_just_made(self):
        from apps.thumbs import services as thumbs

        m = self.create()
        st = self.sticker(m["id"])
        from apps.photoedit import services as photo

        buf = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(buf, "PNG")
        newer = photo._asset_from_bytes(self.store, self.owner, buf.getvalue(), title="جدیدتر")
        base = f"/api/v1/stores/{self.store.pk}/thumbnails/library/"
        self.assertEqual({a["id"] for a in thumbs.library(self.store, limit=1)}, {newer.pk})
        got = thumbs.library(self.store, limit=1, include_id=st["asset"]["id"])
        self.assertEqual({a["id"] for a in got}, {newer.pk, st["asset"]["id"]})
        r = self.api.get(base + f"?include={st['asset']['id']}")
        self.assertIn(st["asset"]["id"], [a["id"] for a in r.json()["assets"]])
        self.assertEqual(len(self.api.get(base + "?include=abc").json()["assets"]), 2)

    def test_the_mascot_is_reachable_from_the_photo_library_and_motion_refs(self):
        from apps.motion import assets as motion_assets

        m = self.create()
        st = self.sticker(m["id"])
        shot = self.render(m["id"], size="ig_square").json()
        lib = self.api.get(f"/api/v1/stores/{self.store.pk}/thumbnails/library/").json()["assets"]
        self.assertEqual({a["id"] for a in lib}, {st["asset"]["id"], shot["asset"]["id"]})
        data, ext = motion_assets.load(self.store, f"photo:{st['asset']['id']}")
        self.assertEqual(ext, ".png")
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.mode, "RGBA")                                              # موشن هم شفافیت را نگه می‌دارد
        data2, ext2 = motion_assets.load(self.store, f"photo:{shot['asset']['id']}")
        self.assertIn(ext2, (".jpg", ".png"))


class SelfTestWiringTests(MascotApiBase):
    def test_the_node_acceptance_registry_has_the_cpu_test_and_it_passes_with_no_node(self):
        from apps.compute.selftests import REGISTRY, Verdict, load_all

        load_all(force=True)
        t = REGISTRY.get("mascot_render")
        self.assertIsNotNone(t)
        self.assertIsNone(t.build)
        self.assertIsNotNone(t.virtual)
        self.assertEqual((t.group, t.optional), ("system", True))
        v = t.virtual(mock.Mock())
        self.assertIsInstance(v, Verdict)
        self.assertTrue(v.ok, v.detail)
        self.assertIn("29", v.detail)
        self.assertEqual(v.device, "cpu")

    def test_the_selftest_command(self):
        out = StringIO()
        call_command("mascot_selftest", poses="stand,thumbs_up,lift", stdout=out)
        self.assertIn('"ok": true', out.getvalue())
        with self.assertRaises(CommandError):
            call_command("mascot_selftest", poses="nope")

    def test_a_failing_check_is_reported_not_hidden(self):
        """پالتِ spec A و شخصیتِ spec B (کلاه بنفش به‌جای فیروزه‌ای) ⇒ رد با یادداشتِ فارسی."""
        from .engine import compose, qa
        from .engine import spec as S

        good = B.spec_from_brand("coach", selftest.CHAGHER_COLOURS, "x")
        shot = compose.figure_layer({"spec": {**good, "hat_colour": "#8a4fd1", "prop_colour": "#8a4fd1"}, "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9}, 400, 500)
        res = qa.check_figure(shot.layer, S.palette(good))
        self.assertFalse(res["ok"])
        self.assertTrue(any("دیده نمی‌شود" in qa.note_fa(n) for n in res["notes"]))


class DemoCommandTests(MascotApiBase):
    def setUp(self):
        super().setUp()
        self.out = Path(tempfile.mkdtemp(prefix="nmmascot-demo-"))

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)
        super().tearDown()

    def test_writes_the_contact_sheet_without_touching_the_db(self):
        from .models import Mascot, MascotRender

        out = StringIO()
        call_command("mascot_demo", store=self.store.pk, out=str(self.out), stdout=out)
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(names, ["contact-sheet.jpg", "model-sheet.png", "poses.jpg", "shots", "sizes.jpg", "sticker-bust.png", "sticker.png", "thumbnail-with-mascot.jpg"])
        self.assertEqual(sorted(p.name for p in (self.out / "shots").iterdir()), ["ig_portrait.png", "ig_square.png", "story.png", "wide.png"])
        self.assertEqual(Image.open(self.out / "shots" / "story.png").size, (1080, 1920))
        self.assertEqual(Image.open(self.out / "thumbnail-with-mascot.jpg").size[0] > 600, True)
        with Image.open(self.out / "sticker.png") as st:
            self.assertEqual(st.getchannel("A").getpixel((0, 0)), 0)
        text = out.getvalue()
        self.assertIn("#126f85", text)
        self.assertIn("با چغر چغر تر شو", text)                                              # جملهٔ تأییدشدهٔ برند
        self.assertEqual((Mascot.objects.count(), MascotRender.objects.count(), PhotoAsset.objects.count()), (0, 0, 0))

    def test_bad_arguments_and_claims_are_refused(self):
        with self.assertRaises(CommandError):
            call_command("mascot_demo", store=99999, out=str(self.out))
        with self.assertRaises(CommandError):
            call_command("mascot_demo", store=self.store.pk, out=str(self.out), role="pirate")
        with self.assertRaises(CommandError):
            call_command("mascot_demo", store=self.store.pk, out=str(self.out), text="فقط ۵۰۰ هزار تومان")


class PanelRegistryTests(MascotApiBase):
    def test_page_is_registered_in_the_panel_in_the_content_section(self):
        from apps.panel import registry

        keys = {p[0]: (sec[0], p[2]) for sec in registry.SECTIONS for p in sec[4]}
        self.assertEqual(keys["mascot"], ("content", "/stores/:id/mascot"))
        feats = {f[0] for sec in registry.SECTIONS for p in sec[4] for f in p[4]}
        self.assertTrue({"mascot.sticker", "mascot.check"} <= feats)
        ts = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "panel" / "registry.ts")
        if ts.is_file():                                                                         # ثبتِ فرانت با بک‌اند یکی است
            self.assertIn('key: "mascot", section: "content"', ts.read_text(encoding="utf-8"))

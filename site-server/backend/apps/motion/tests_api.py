"""API ِ استودیوی موشن + مسیرِ سرورِ پردازش (بی GPU: گرهٔ ساختگی کار را از صف می‌گیرد، ویدیو می‌فرستد، سایت آن را در رسانهٔ فروشگاه می‌گذارد)."""
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.compute import queue as compute_queue
from apps.compute import services as CS
from apps.compute.models import ComputeJob, ComputeNode
from apps.stores.models import Store

from . import ai, catalog, runner, selftest, services, specs
from .models import MotionAsset, MotionRender

User = get_user_model()
FFMPEG = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"


def png_bytes(w=300, h=200, color=(200, 30, 60, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def make_mp4(path: Path, w=540, h=960, seconds=3):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x126F85:s={w}x{h}:d={seconds}:r=30", "-pix_fmt", "yuv420p", str(path)],
                   check=True, capture_output=True)


def spec(**kw):
    s = {"style": "flat-vector", "aspect": "9:16", "lang": "fa", "scenes": [{"type": "title", "duration": 3, "title": "با چغر، چغرتر شو", "subtitle": "دستیارِ هوش مصنوعیِ مربی‌ها"}]}
    s.update(kw)
    return s


class Base(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="nmmotion-media-")
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        self.owner = User.objects.create_user("motion-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", description="دستیار هوش مصنوعی مربی‌ها", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/motion"
        self.made_jobs: list[ComputeJob] = []

    def tearDown(self):
        self.ov.disable()
        for j in ComputeJob.objects.filter(kind=services.KIND):
            shutil.rmtree(CS.data_root() / j.dir_rel, ignore_errors=True)
        shutil.rmtree(self.media, ignore_errors=True)

    def node(self, **caps):
        base = {"motion_render": True, "kinds": ["motion.render"], "motion": {"state": "ready"}}   # caps["kinds"]: the site hands a node only kinds it advertises
        base.update(caps)
        return ComputeNode.objects.create(name="DESKTOP-FAKE", last_seen=timezone.now(), capabilities=base)

    def post_render(self, **body):
        body.setdefault("mode", "template")
        body.setdefault("spec", spec())
        return self.api.post(f"{self.base}/renders/", body, format="json")


class Catalog(Base):
    def test_styles_endpoint(self):
        r = self.api.get("/api/v1/motion/styles/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertGreaterEqual(len(d["styles"]), 60)
        self.assertEqual({a["id"] for a in d["aspects"]}, {"9:16", "1:1", "4:5", "16:9"})
        self.assertEqual({t["id"] for t in d["templates"]} >= {"title", "list", "quote", "stat", "compare", "product", "logo", "app", "explainer"}, True)
        self.assertTrue(all("group_label" in s for s in d["styles"]))

    def test_anonymous_cannot_read_store_endpoints(self):
        r = APIClient().get(f"{self.base}/")
        self.assertIn(r.status_code, (401, 403))

    def test_other_users_store_is_not_visible(self):
        other = User.objects.create_user("intruder", password="x")
        c = APIClient()
        c.force_authenticate(other)
        self.assertIn(c.get(f"{self.base}/").status_code, (403, 404))

    def test_overview(self):
        d = self.api.get(f"{self.base}/").json()
        self.assertEqual(d["brand"]["name"], "چغر")
        self.assertEqual(d["brand"]["colors"], ["#126F85", "#163F75"])
        self.assertEqual(d["node"]["state"], "none")
        self.assertEqual(d["limits"]["max_total_site"], 60)
        self.assertEqual(len(d["code"]["samples"]), 3)
        self.assertIn("remotion", d["code"]["allowed_imports"])
        self.assertTrue(d["sample_spec"]["scenes"])

    def test_player_page_is_sandbox_safe(self):
        r = self.client.get("/api/v1/motion/player/")
        self.assertEqual(r.status_code, 200)
        csp = r["Content-Security-Policy"]
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("default-src 'none'", csp)
        self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn('<html lang="fa" dir="ltr">', r.content.decode("utf-8"))   # an RTL document throws the Remotion Player stage off-screen (black preview)
        self.assertEqual(self.client.get("/api/v1/motion/player/fonts/..%2Fx.woff2").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/motion/player/fonts/evil.txt").status_code, 404)
        font = self.client.get("/api/v1/motion/player/fonts/vazirmatn-arabic-700-normal.woff2")
        if font.status_code == 200:
            self.assertEqual(font["Access-Control-Allow-Origin"], "*")


class Assets(Base):
    def test_upload_preview_and_delete(self):
        up = self.api.post(f"{self.base}/assets/", {"file": io.BytesIO(png_bytes(3000, 2000))}, format="multipart")
        self.assertEqual(up.status_code, 400)                      # a BytesIO has no name/extension: refused
        from django.core.files.uploadedfile import SimpleUploadedFile

        f = SimpleUploadedFile("logo.png", png_bytes(3000, 2000), content_type="image/png")
        up = self.api.post(f"{self.base}/assets/", {"file": f}, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        a = up.json()["assets"][0]
        self.assertEqual(a["ref"], f"upload:{a['id']}")
        self.assertLessEqual(max(a["width"], a["height"]), 1400)
        self.assertTrue(a["alpha"])
        s = spec(brand={"logo": a["ref"]}, scenes=[{"type": "logo", "duration": 3, "tagline": "شعار"}])
        pv = self.api.post(f"{self.base}/preview/", {"spec": s}, format="json")
        self.assertEqual(pv.status_code, 200, pv.content)
        out = pv.json()["spec"]
        self.assertEqual(out["brand"]["logo"], "asset:a1")
        self.assertTrue(out["assets"]["a1"].startswith("data:image/png;base64,"))
        self.assertEqual(self.api.get(f"{self.base}/assets/").json()["assets"][0]["id"], a["id"])
        self.assertEqual(self.api.delete(f"{self.base}/assets/{a['id']}/").status_code, 204)
        self.assertFalse(MotionAsset.objects.exists())

    def test_text_files_are_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.api.post(f"{self.base}/assets/", {"file": SimpleUploadedFile("a.png", b"not an image")}, format="multipart")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"{self.base}/assets/", {"file": SimpleUploadedFile("a.exe", b"MZ")}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_another_stores_asset_is_not_resolvable(self):
        other = Store.objects.create(owner=self.owner, name="دیگر")
        a = MotionAsset.objects.create(store=other, path="motion/assets/x/y.png")
        s = spec(brand={"logo": f"upload:{a.pk}"})
        r = self.api.post(f"{self.base}/preview/", {"spec": s}, format="json")
        self.assertEqual(r.status_code, 400)


class AIModes(Base):
    def test_ai_unavailable_degrades_to_a_rules_draft_with_a_persian_message(self):
        r = self.api.post(f"{self.base}/ai/", {"idea": "معرفی چغر. ثبت‌نام در یک دقیقه. خرید توکن. ساخت برنامه. همین حالا شروع کن", "style": "pixel-art"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["source"], "rules")
        self.assertIn("در دسترس نیست", d["message"])
        self.assertTrue(d["spec"]["scenes"])
        self.assertEqual(d["spec"]["style"], "pixel-art")

    def test_ai_writes_a_validated_script(self):
        class Fake:
            def generate(self, prompt, system=None, **kw):
                return "```json\n" + json.dumps({"title": "x", "scenes": [{"type": "title", "duration": 3, "title": "سلام"}, {"type": "evil", "duration": 3},
                                                                           {"type": "cta", "duration": 3, "title": "شروع", "button": "برو"}]}) + "\n```"

        with mock.patch.object(ai, "get_provider", return_value=Fake()):
            d = self.api.post(f"{self.base}/ai/", {"idea": "یک ایده", "style": "flat-vector"}, format="json").json()
        # the invalid scene type makes the whole AI answer unusable -> the safe rules draft, never a broken spec
        self.assertEqual(d["source"], "rules")

        class Good(Fake):
            def generate(self, prompt, system=None, **kw):
                return json.dumps({"title": "t", "scenes": [{"type": "title", "duration": 3, "title": "سلام"}, {"type": "cta", "duration": 3, "title": "شروع", "button": "برو"}]})

        with mock.patch.object(ai, "get_provider", return_value=Good()):
            d = self.api.post(f"{self.base}/ai/", {"idea": "یک ایده", "style": "flat-vector"}, format="json").json()
        self.assertEqual(d["source"], "ai")
        self.assertEqual([s["type"] for s in d["spec"]["scenes"]], ["title", "cta"])

    def test_ai_needs_an_idea_and_a_style(self):
        self.assertEqual(self.api.post(f"{self.base}/ai/", {"idea": "", "style": "flat-vector"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/ai/", {"idea": "ایده", "style": "nope"}, format="json").status_code, 400)

    def test_ai_code_unavailable_message_and_safety_warning(self):
        r = self.api.post(f"{self.base}/ai-code/", {"idea": "یک ویدیوی ساده"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("در دسترس نیست", r.json()["error"]["message"])

        class Evil:
            def generate(self, prompt, system=None, **kw):
                return 'import {AbsoluteFill} from "remotion";\nexport const config={};\nexport default function V(){ fetch("http://x.com"); return <AbsoluteFill/>; }'

        with mock.patch.object(ai, "get_provider", return_value=Evil()):
            d = self.api.post(f"{self.base}/ai-code/", {"idea": "ایده"}, format="json").json()
        self.assertIn("قاعده‌های امنیتی", d["warning"])

    def test_code_check_refuses_unsafe_code_in_persian(self):
        bad = self.api.post(f"{self.base}/code/check/", {"code": 'import x from "fs";'}, format="json").json()
        self.assertFalse(bad["ok"])
        self.assertIn("مجاز نیست", bad["error"])


class RenderApiSite(Base):
    """هیچ گره‌ای ثبت نیست ⇒ رندرِ سایت (محدود)."""

    def fake_site_render(self, render, on_wait=None):
        render.refresh_from_db()
        render.state, render.progress = MotionRender.State.READY, 1.0
        render.save()
        return render

    def test_no_node_means_site_render(self):
        with mock.patch.object(services, "render_on_site", side_effect=self.fake_site_render) as m:
            r = self.post_render()
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()["render"]
        self.assertEqual(d["target"], "site")
        self.assertEqual(d["state"], "READY")
        self.assertEqual(m.call_count, 1)
        self.assertTrue(d["title"])

    def test_invalid_spec_and_too_long_for_site(self):
        self.assertEqual(self.post_render(spec=spec(style="nope")).status_code, 400)
        long_ = spec(scenes=[{"type": "title", "duration": 30, "title": f"s{i}"} for i in range(3)])
        r = self.post_render(spec=long_)
        self.assertEqual(r.status_code, 400)
        self.assertIn("حداکثر", r.json()["error"]["message"])

    def test_unsafe_code_is_refused_at_creation(self):
        r = self.post_render(mode="code", spec=None, code='fetch("http://x")')
        self.assertEqual(r.status_code, 400)
        self.assertIn("مجاز نیست", r.json()["error"]["message"])

    def test_history_detail_cancel_delete(self):
        with mock.patch.object(services, "render_on_site", lambda r, on_wait=None: r):
            rid = self.post_render().json()["render"]["id"]
        self.assertEqual(len(self.api.get(f"{self.base}/renders/").json()["renders"]), 1)
        d = self.api.get(f"{self.base}/renders/{rid}/?full=1").json()["render"]
        self.assertEqual(d["spec"]["style"], "flat-vector")
        c = self.api.post(f"{self.base}/renders/{rid}/cancel/", {}, format="json").json()["render"]
        self.assertEqual(c["state"], "CANCELLED")
        self.assertEqual(self.api.post(f"{self.base}/renders/{rid}/nope/", {}, format="json").status_code, 400)
        self.assertEqual(self.api.delete(f"{self.base}/renders/{rid}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/renders/{rid}/").status_code, 404)

    def test_too_many_active_renders(self):
        for _ in range(6):
            MotionRender.objects.create(store=self.store, spec=spec(), style="flat-vector", state=MotionRender.State.RENDERING)
        r = self.post_render()
        self.assertEqual(r.status_code, 429)


class RenderApiNode(Base):
    """گرهٔ پردازش ثبت است ⇒ رندر روی گره (صفِ ماندگار)؛ گرهٔ ساختگی کار را می‌گیرد و ویدیو می‌فرستد."""

    def test_full_round_trip_through_the_compute_queue(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        node = self.node()
        up = self.api.post(f"{self.base}/assets/", {"file": SimpleUploadedFile("logo.png", png_bytes())}, format="multipart").json()["assets"][0]
        s = spec(brand={"logo": up["ref"], "colors": ["#126F85", "#163F75"]})
        r = self.post_render(spec=s, quality="540")
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()["render"]
        self.assertEqual(d["target"], "node")
        self.assertEqual(d["state"], "QUEUED")
        job = ComputeJob.objects.get(uid=d["job_uid"])
        self.assertEqual(job.kind, "motion.render")
        self.assertEqual(job.payload["composition"], "Template")
        self.assertEqual(job.payload["scale"], 0.5)
        self.assertEqual(job.payload["props"]["spec"]["assets"], {"a1": "@file:a1.png"})
        self.assertEqual(job.payload["props"]["spec"]["brand"]["logo"], "asset:a1")
        self.assertEqual(sorted(job.inputs), ["a1.png"])
        self.assertEqual(job.category, "render")

        # the node claims it
        got = CS.claim(node)
        self.assertEqual(got.pk, job.pk)
        CS.progress(got, {"progress": 0.4, "message": "در حال رندر روی کارتِ گرافیک — فریمِ ۳۶ از ۹۰"})
        d = self.api.get(f"{self.base}/renders/{d['id']}/").json()["render"]
        self.assertEqual(d["state"], "RENDERING")
        self.assertAlmostEqual(d["progress"], 0.4, places=2)
        self.assertIn("کارتِ گرافیک", d["message"])

        # ... renders, uploads out.mp4, finishes
        make_mp4(CS.output_path(got, "out.mp4"))
        CS.finish(got, node, True, meta={"seconds": 9.5, "gl": "angle"})
        d = self.api.get(f"{self.base}/renders/{d['id']}/").json()["render"]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual((d["width"], d["height"]), (540, 960))
        self.assertAlmostEqual(d["duration_s"], 3.0, delta=0.2)
        self.assertTrue(d["video_url"].endswith(".mp4"))
        self.assertTrue(d["poster_url"])
        # visible in the video editor's bin (a store video)
        from apps.content import editor_project

        refs = [v["ref"] for v in editor_project.bin_items(self.store)["videos"]]
        self.assertIn(d["video_ref"], refs)
        # the rendered file really is in the store's media
        self.assertTrue((Path(self.media) / "generated" / "motion" / str(self.store.pk)).is_dir())

    def test_registered_but_offline_or_old_node_keeps_the_render_waiting(self):
        old = ComputeNode.objects.create(name="OLD", last_seen=timezone.now() - timedelta(days=3), capabilities={"photo": True})
        d = self.post_render().json()["render"]
        self.assertEqual(d["target"], "node", "the owner's rule: final renders wait for the node")
        self.assertEqual(d["state"], "WAITING_NODE")
        self.assertEqual(CS.claim(old), None, "an agent that never advertised motion_render never receives the kind")
        ov = self.api.get(f"{self.base}/")
        self.assertEqual(ov.json()["node"]["state"], "outdated")
        # «رندر روی سایت»: the waiting node job is cancelled and the same render runs on the site
        with mock.patch.object(services, "render_on_site", lambda r, on_wait=None: r) as m:
            r = self.api.post(f"{self.base}/renders/{d['id']}/site/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["render"]["target"], "site")
        self.assertEqual(ComputeJob.objects.get(uid=d["job_uid"]).state, ComputeJob.State.CANCELLED)

    def test_node_with_unfinished_install_does_not_take_the_job_yet(self):
        node = self.node(motion={"state": "installing", "message": "دانلودِ Node.js"})
        d = self.post_render().json()["render"]
        self.assertIsNone(CS.claim(node), "motion_blocked: queued until the toolchain is ready")
        self.assertEqual(self.api.get(f"{self.base}/").json()["node"]["state"], "installing")
        node.capabilities = {"motion_render": True, "kinds": ["motion.render"], "motion": {"state": "ready"}}
        node.save()
        self.assertEqual(CS.claim(node).uid.hex, d["job_uid"].replace("-", ""))

    def test_failed_node_job_marks_the_render_failed_with_the_reason(self):
        node = self.node()
        d = self.post_render().json()["render"]
        job = CS.claim(node)
        job.max_attempts = 1
        job.save()
        CS.finish(job, node, False, error="آزمونِ رندر روی این کامپیوتر ناموفق بود: gpu", meta={"retryable": False})
        d = self.api.get(f"{self.base}/renders/{d['id']}/").json()["render"]
        self.assertEqual(d["state"], "FAILED")
        self.assertIn("آزمونِ رندر", d["error"])
        again = self.api.post(f"{self.base}/renders/{d['id']}/retry/", {}, format="json").json()["render"]
        self.assertEqual(again["state"], "QUEUED")

    def test_cancel_cancels_the_node_job(self):
        self.node()
        d = self.post_render().json()["render"]
        c = self.api.post(f"{self.base}/renders/{d['id']}/cancel/", {}, format="json").json()["render"]
        self.assertEqual(c["state"], "CANCELLED")
        self.assertEqual(ComputeJob.objects.get(uid=d["job_uid"]).state, ComputeJob.State.CANCELLED)

    def test_user_code_goes_to_the_node_compiled_and_scanned(self):
        if not (runner.node_bin() and (runner.repo_motion_dir() / "node_modules" / "sucrase").exists()):
            self.skipTest("the code compiler (node + sucrase) is not set up here")
        from . import samples

        self.node()
        r = self.post_render(mode="code", spec=None, code=samples.HELLO, quality="720")
        self.assertEqual(r.status_code, 201, r.content)
        job = ComputeJob.objects.get(uid=r.json()["render"]["job_uid"])
        self.assertEqual(job.payload["composition"], "User")
        self.assertIn("__NM_USER_FACTORY", job.payload["user_js"])
        self.assertNotIn("import ", job.payload["user_js"])


class NodeContract(Base):
    """سایت ⇄ گره: همان payload ِ سایت را `motion_jobs.validate_payload` ِ گره می‌پذیرد (لیستِ سفیدِ کلیدها)."""

    def _node_module(self):
        p = Path(settings.BASE_DIR).parent / "processing" / "motion_jobs.py"
        if not p.is_file():
            self.skipTest("processing/motion_jobs.py not found")
        sp = importlib.util.spec_from_file_location("motion_jobs_contract", p)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m

    def test_payloads_the_site_builds_are_accepted_by_the_node(self):
        mj = self._node_module()
        self.node()
        d = self.post_render().json()["render"]
        payload = ComputeJob.objects.get(uid=d["job_uid"]).payload
        clean = mj.validate_payload(payload)
        self.assertEqual(clean["composition"], "Template")
        self.assertEqual(mj.validate_payload(selftest.PAYLOAD)["composition"], "Template")

    def test_selftest_payload_is_a_three_second_template(self):
        n = specs.normalize_spec(selftest.PAYLOAD["props"]["spec"])
        self.assertAlmostEqual(n["total_s"], 3.0, places=1)
        self.assertTrue(catalog.get(n["style"]))
        self.assertEqual(selftest.PAYLOAD["scale"], 0.5)

    def test_selftest_check(self):
        node = self.node()
        job = selftest.enqueue()
        got = CS.claim(node)
        self.assertEqual(got.pk, job.pk)
        make_mp4(CS.output_path(got, "out.mp4"))
        CS.finish(got, node, True, meta={"frames": 90, "width": 540, "height": 960, "fps": 30, "gl": "swangle"})
        got.refresh_from_db()
        ok, why = selftest.check(got)
        self.assertTrue(ok, why)
        bad = ComputeJob.objects.get(pk=got.pk)
        bad.result = {"outputs": [], "meta": {}}
        ok, why = selftest.check(bad)
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_capability_mapping(self):
        from apps.compute.models import capability_for

        self.assertEqual(capability_for("motion.render"), "motion_render")
        self.assertEqual(compute_queue.kind_label("motion.render"), "رندرِ ویدیوی موشن")

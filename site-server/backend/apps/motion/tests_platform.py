"""استودیوی موشن روی «پلتفرمِ گره» (نصبِ خودکار، آزمونِ خودکار): آزمونِ `motion_studio` ثبت است، تا پایانِ نصبِ خودکارِ ابزارِ موشن «منتظرِ نصب»
می‌ماند (نه شکست و نه ماندن در صف تا ۳۰ دقیقه)، نصبِ ناموفق با علتش «رد» می‌شود، و پس از آماده‌شدن کارِ واقعیِ آزمون روی گره اجرا و سنجیده می‌شود."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.compute import autopilot
from apps.compute import services as CS
from apps.compute.models import ComputeJob, ComputeNode
from apps.compute.selftests import REGISTRY, load_all, runner

from . import selftest
from .tests_api import make_mp4

KINDS = ["echo", "selftest.gpu", "ollama.generate", "edit.render", "motion.render"]


def mk_node(name="gpu-motion", **caps):
    base = {"agent": "2.99", "kinds": list(KINDS), "motion_render": True, "motion": {"state": "ready"}, "started_at": 1000,
            "code": {"version": "2.99", "id": "bbbbbbbbbbbbbbbbbbbb"}}
    base.update(caps)
    return ComputeNode.objects.create(name=name, capabilities=base, last_seen=timezone.now())


class SelfTestRegistration(TestCase):
    def test_the_code_module_registers_motion_studio_and_the_docs_block_does_not_double_it(self):
        reg = load_all()
        self.assertIn("motion_studio", reg)
        t = reg["motion_studio"]
        self.assertEqual((t.kind, t.group), ("motion.render", "video"))
        self.assertTrue(t.gpu_required)
        self.assertEqual(t.requeue, {"kinds": ("motion.render",)})
        self.assertEqual([k for k in reg if k.startswith("motion")], ["motion_studio"])

    def test_available_only_for_an_agent_that_advertises_the_kind(self):
        t = load_all()["motion_studio"]
        old = mk_node("old-agent", kinds=["echo"])
        ok, why = t.available(old)
        self.assertFalse(ok)
        self.assertIn("motion.render", why)
        off = mk_node("motion-off", motion_render=False)
        self.assertFalse(t.available(off)[0])
        self.assertTrue(t.available(mk_node("good"))[0])

    def test_the_job_is_the_three_second_template_of_apps_motion(self):
        spec = load_all()["motion_studio"].build(None)
        self.assertEqual(spec.kind, "motion.render")
        self.assertEqual(spec.payload, selftest.PAYLOAD)
        self.assertEqual(spec.payload["props"]["spec"]["scenes"][0]["duration"], 3)


class SelfTestRunOnTheMotionToolchain(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-motion-st-"))
        self.ctx = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True, MEDIA_ROOT=str(self.tmp / "media"))
        self.ctx.enable()
        self.patch_latest = mock.patch.object(autopilot.U, "latest", return_value={"version": "2.99", "id": "bbbbbbbbbbbbbbbbbbbb", "size": 1, "built": "x"})
        self.patch_latest.start()

    def tearDown(self):
        self.patch_latest.stop()
        self.ctx.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, node):
        run = runner.start_run(node, "manual", only=["motion_studio"])
        return run, run.results.get(key="motion_studio")

    def test_it_waits_for_the_automatic_install_instead_of_failing_or_timing_out(self):
        node = mk_node(motion={"state": "installing", "message": "دانلودِ بستهٔ رندرِ موشن", "progress": 0.4})
        run, r = self.start(node)
        r.refresh_from_db()
        self.assertEqual(r.state, "QUEUED")
        job = ComputeJob.objects.get(uid=r.job_uid)
        self.assertIsNone(CS.claim(node), "the node must not be handed the job while its toolchain is not ready")
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "WAITING")
        self.assertIn("منتظرِ نصبِ خودکار", r.detail)
        self.assertIn("دانلودِ بستهٔ رندرِ موشن", r.detail)
        self.assertEqual(ComputeJob.objects.get(pk=job.pk).state, "QUEUED")
        # a long wait is not a failure of the queue: even after the old 30-minute limit it still waits
        r.started_at = timezone.now() - timedelta(minutes=50)
        r.save()
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "WAITING")
        # the node finishes installing: the job is handed out, rendered, and judged
        node.capabilities = {**node.capabilities, "motion": {"state": "ready"}}
        node.save()
        got = CS.claim(node)
        self.assertEqual(got.pk, job.pk)
        make_mp4(CS.output_path(got, "out.mp4"))
        CS.output_path(got, "motion-render.json").write_text('{"frames": 90, "width": 540, "height": 960, "device": "gpu"}')
        CS.finish(got, node, True, meta={"frames": 90, "width": 540, "height": 960, "fps": 30, "device": "gpu", "device_note": "ANGLE/D3D11", "seconds": 61})
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "PASSED", r.detail)
        self.assertEqual(r.device, "gpu")
        self.assertIn("۹۰ فریم", r.detail)

    def test_a_render_on_the_cpu_does_not_pass_the_gpu_test(self):
        node = mk_node()
        run, r = self.start(node)
        got = CS.claim(node)
        make_mp4(CS.output_path(got, "out.mp4"))
        CS.finish(got, node, True, meta={"frames": 90, "width": 540, "height": 960, "fps": 30, "device": "cpu", "device_note": "software GL"})
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "FAILED")
        self.assertIn("پردازنده", r.detail)

    def test_a_failed_install_is_reported_with_its_reason_and_the_job_is_withdrawn(self):
        node = mk_node(motion={"state": "failed", "error": "دانلودِ «nm-motion-pack-x.zip» از سایت ناموفق بود"})
        run, r = self.start(node)
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "FAILED")
        self.assertIn("نصبِ ابزارِ موشن", r.detail)
        self.assertIn("nm-motion-pack-x.zip", r.detail)
        self.assertEqual(ComputeJob.objects.get(uid=r.job_uid).state, "CANCELLED")

    def test_an_old_agent_is_told_to_update_not_left_waiting_for_an_install(self):
        node = mk_node("old-agent-2", kinds=["echo", "selftest.gpu"], motion_render=False)
        run, r = self.start(node)
        r.refresh_from_db()
        self.assertEqual(r.state, "SKIPPED")
        self.assertIn("motion.render", r.detail)

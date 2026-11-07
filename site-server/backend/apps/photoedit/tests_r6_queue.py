"""نوبت ۶ ادیتور عکس: کارهایی که پردازششان روی سرورِ پردازش است و سرور خاموش است «در صف — منتظرِ سرورِ پردازش» می‌مانند
(صفِ ماندگارِ apps.compute)، نه شکست. بی شبکه، بی هوشِ مصنوعیِ واقعی."""
import time
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from apps.compute.models import ComputeJob, ComputeNode

from . import services
from .designer import engine
from .models import PhotoDesign, PhotoEdit
from .tests import ApiTestBase, photo
from .tests_designer import CRIT_OK, PLAN_OK, DesignerBase, FakeVision, patch_ai

WAIT = "در صف — منتظرِ سرورِ پردازش"


def offline_node(**caps):
    return ComputeNode.objects.create(name="gpu-off", last_seen=timezone.now() - timedelta(hours=2),
                                      capabilities={"photo": True, "ollama": True} | caps)


class QueuedMessageTests(ApiTestBase):
    def test_constants_are_the_shared_persian_text(self):
        self.assertEqual(services.WAIT_NODE, WAIT)
        self.assertTrue(services.GENFILL_WAIT_MESSAGE.startswith(WAIT))
        self.assertEqual(services.queued_message(object(), False), WAIT)
        with mock.patch("apps.compute.queue.one", side_effect=RuntimeError("x")):
            self.assertEqual(services.queued_message(object(), True), "در صفِ سرورِ پردازش")
        with mock.patch("apps.compute.queue.one", return_value={"status_text": "در صف — نفرِ ۲ام"}):
            self.assertEqual(services.queued_message(object(), True), "در صف — نفرِ ۲ام")

    def test_kit_edit_waits_for_an_offline_node_and_is_not_failed_by_polling(self):
        ids = self.upload(photo(seed=5))
        offline_node()
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "operations": [{"tool": "kit_auto"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual((e.state, e.message), ("NODE", WAIT))
        for _ in range(3):                                           # پنل چند بار می‌پرسد: همان‌جا می‌ماند
            d = self.api.get(f"{self.base}/edits/?ids={e.pk}").json()["edits"][0]
            self.assertEqual((d["state"], d["message"]), ("NODE", WAIT), d)
        job = ComputeJob.objects.get(uid=e.compute_job)
        self.assertEqual(job.state, "QUEUED")

    def test_analysis_waits_with_the_same_text(self):
        ids = self.upload(photo(seed=9))
        r = self.api.post(f"{self.base}/assets/{ids[0]}/analyze/", {}, format="json")
        self.assertEqual(r.json()["asset"]["kit_analysis"]["message"], WAIT)


class DesignWaitsForNodeTests(DesignerBase):
    def new_design(self, asset, **kw):
        base = {"prompt": "حراجِ پاییزه برای کفش ورزشی، تخفیف ۳۰ درصد", "quality": "normal", "variants": 1}
        return engine.create(self.store, self.owner, asset, base | kw)

    def test_ai_design_parks_then_resumes_when_the_node_returns(self):
        asset = self.asset()
        node = offline_node()
        d = self.new_design(asset)
        fake = FakeVision(RuntimeError("402 Payment Required"))
        with patch_ai(fake):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual((d.state, d.message), ("QUEUED", WAIT))
        self.assertEqual(len(d.variants or []), 0)
        self.assertIn("wait_since", d.options)
        self.assertGreater(d.options["wait_next"], time.time())
        self.assertIn("در صف می‌ماند", d.log[-1]["text"])
        n_log = len(d.log)
        # بیدارباشِ زودرس (ارسالِ دوبارهٔ پنل): نه هوش مصنوعی صدا می‌خورد نه چیزی عوض می‌شود
        with patch_ai(fake):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual((d.state, len(fake.calls), len(d.log)), ("QUEUED", 1, n_log))
        # سرور هنوز خاموش، بیدارباشِ سرِ وقت ⇒ دوباره منتظر؛ گزارش بزرگ نمی‌شود
        d.options = dict(d.options, wait_next=0)
        d.save(update_fields=["options"])
        with patch_ai(FakeVision(RuntimeError("timeout"))):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual((d.state, len(d.log)), ("QUEUED", n_log))
        # سرور برگشت ⇒ با هوش مصنوعی کامل می‌شود
        node.last_seen = timezone.now()
        node.save(update_fields=["last_seen"])
        d.options = dict(d.options, wait_next=0)
        d.save(update_fields=["options"])
        with patch_ai(FakeVision(PLAN_OK, CRIT_OK, CRIT_OK)):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        self.assertTrue(d.ai["planner"]["used"])
        self.assertTrue(d.ai["critic"]["used"])

    def test_critic_failure_before_any_round_also_waits(self):
        asset = self.asset()
        offline_node()
        d = self.new_design(asset)
        with patch_ai(FakeVision(PLAN_OK, RuntimeError("down"))):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual((d.state, d.message), ("QUEUED", WAIT))

    def test_gives_up_after_a_day_and_finishes_without_ai(self):
        asset = self.asset()
        offline_node()
        d = self.new_design(asset)
        d.options = dict(d.options, wait_since=time.time() - 25 * 3600)
        d.save(update_fields=["options"])
        with patch_ai(FakeVision(RuntimeError("a"), RuntimeError("b"))):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        self.assertFalse(d.ai["planner"]["used"])

    def test_no_wait_without_a_registered_node_or_when_waiting_is_not_allowed(self):
        asset = self.asset()
        d = self.new_design(asset)                                   # هیچ سروری ثبت نیست
        with patch_ai(FakeVision(RuntimeError("a"), RuntimeError("b"))):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        offline_node()
        d2 = self.new_design(asset)                                  # «طراحیِ گروهی» اجازهٔ انتظار ندارد
        with patch_ai(FakeVision(RuntimeError("a"), RuntimeError("b"))):
            engine.run(d2.pk)
        d2.refresh_from_db()
        self.assertEqual(d2.state, "READY", d2.error)
        self.assertEqual(PhotoDesign.objects.filter(state="QUEUED").count(), 0)

    def test_online_node_never_parks(self):
        asset = self.asset()
        self.node()
        d = self.new_design(asset)
        with patch_ai(FakeVision(RuntimeError("a"), RuntimeError("b"))):
            engine.run(d.pk, allow_wait=True)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)

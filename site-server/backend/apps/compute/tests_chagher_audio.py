"""آزمونِ مجازیِ «صداهای چغر» در خودآزمونِ سرورِ پردازش (selftests/chagher_audio.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.ai.models import AudioAsset
from apps.stores.models import Store

from .models import ComputeNode, SelfTestResult, SelfTestRun
from .selftests import REGISTRY, Ctx, load_all


class ChagherAudioSelfTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner-ca", password="x")
        self.store = Store.objects.create(id=34, owner=self.user, name="chagher-test")
        self.node = ComputeNode.objects.create(name="GPU-ca", last_seen=timezone.now(), capabilities={"agent": "2.18"})
        load_all()

    def take(self, status, error="", **params):
        return AudioAsset.objects.create(store=self.store, kind=AudioAsset.Kind.SPEECH, engine="moss-fa", status=status, text="سلام",
                                         error=error, params=params)

    def verdict(self, started_ago_s=0):
        from .selftests.chagher_audio import virtual

        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        res = SelfTestResult.objects.create(run=run, key="chagher_audio", label="x", started_at=timezone.now() - timedelta(seconds=started_ago_s))
        return virtual(Ctx(self.node, run, {}, result=res))

    def test_registered_optional_and_in_the_audio_group(self):
        t = REGISTRY["chagher_audio"]
        self.assertTrue(t.optional)
        self.assertEqual(t.group, "audio")

    def test_nothing_to_judge_passes(self):
        v = self.verdict()
        self.assertTrue(v.ok, v.detail)

    def test_all_ready_passes(self):
        self.take(AudioAsset.Status.READY)
        self.take(AudioAsset.Status.READY)
        v = self.verdict()
        self.assertTrue(v.ok, v.detail)
        self.assertEqual(v.extra["ready"], 2)

    def test_waiting_takes_wait_first_and_fail_after_thirty_minutes(self):
        self.take(AudioAsset.Status.PENDING)
        v = self.verdict(started_ago_s=60)
        self.assertTrue(v.wait and not v.ok, v.detail)
        v = self.verdict(started_ago_s=31 * 60)
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)

    def test_an_old_moss_failure_waits_for_its_automatic_remake(self):
        self.take(AudioAsset.Status.FAILED, error="RuntimeError: expected mat1 and mat2 to have the same dtype, but got: float != struct c10::BFloat16")
        v = self.verdict(started_ago_s=60)
        self.assertTrue(v.wait, v.detail)

    def test_a_take_that_fails_again_after_the_automatic_remake_is_a_real_failure(self):
        self.take(AudioAsset.Status.FAILED, error="خطای دیگر", auto_retried=True)
        v = self.verdict(started_ago_s=60)
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        self.assertIn("دوباره‌سازیِ خودکار", v.detail)

    def test_a_failure_for_another_reason_is_left_to_the_owner(self):
        self.take(AudioAsset.Status.READY)
        self.take(AudioAsset.Status.FAILED, error="مدل‌های «MOSS» روی این سرور نصب نیست.")
        v = self.verdict(started_ago_s=60)
        self.assertTrue(v.ok, v.detail)

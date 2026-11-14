"""«هر محصولِ چغر تحلیل دارد یا تحلیلش در صف است» در خودآزمونِ چغر (selftests/chagher_content.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.ai.models import ProductIntelligence
from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store

from .models import ComputeNode, SelfTestResult, SelfTestRun
from .selftests import REGISTRY, Ctx, load_all


class ChagherAnalysisCoverageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner-cc", password="x")
        self.store = Store.objects.create(id=34, owner=self.user, name="chagher-test")
        self.node = ComputeNode.objects.create(name="GPU-cc", last_seen=timezone.now(), capabilities={"agent": "2.18"})
        self.flagship = Product.objects.create(store=self.store, name="پرچم", price=1)
        load_all()

    def verdict(self):
        from .selftests.chagher_content import virtual

        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        res = SelfTestResult.objects.create(run=run, key="chagher_content", label="x", started_at=timezone.now() - timedelta(seconds=60))
        return virtual(Ctx(self.node, run, {}, result=res))

    def test_still_registered_and_optional(self):
        self.assertTrue(REGISTRY["chagher_content"].optional)

    def test_a_product_with_no_analysis_and_nothing_queued_fails_and_names_it(self):
        v = self.verdict()
        self.assertFalse(v.ok)
        self.assertIn(str(self.flagship.pk), v.detail)
        self.assertEqual(v.extra["no_analysis"], [self.flagship.pk])

    def test_a_queued_analysis_job_counts(self):
        Job.objects.create(store=self.store, type=Job.Type.PRODUCT_ANALYSIS, state=Job.State.QUEUED,
                           context={"product_id": self.flagship.pk})
        v = self.verdict()
        self.assertTrue(v.ok, v.detail)

    def test_a_cancelled_analysis_job_does_not_count(self):
        # the exact situation of job 371: cancelled once, never queued again
        Job.objects.create(store=self.store, type=Job.Type.PRODUCT_ANALYSIS, state=Job.State.CANCELLED,
                           context={"product_id": self.flagship.pk})
        self.assertFalse(self.verdict().ok)

    def test_a_finished_analysis_counts(self):
        ProductIntelligence.objects.create(product=self.flagship)
        v = self.verdict()
        self.assertTrue(v.ok, v.detail)

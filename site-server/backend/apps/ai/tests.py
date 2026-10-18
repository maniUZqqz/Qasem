from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store
from services.ai.ollama import OllamaMalformedOutput

from .models import AIRequest, MarketResearch, ProductIntelligence
from .tasks import analyze_market_task, analyze_product_task

VALID_INTELLIGENCE = {
    "summary": "کفش اسپرت سبک مناسب استفاده روزمره",
    "target_audience": ["جوانان ۱۸ تا ۳۰ سال"],
    "selling_points": ["وزن کم", "قیمت مناسب"],
    "weaknesses": ["تنوع رنگی محدود"],
    "objections": ["قیمتش بالاست"],
    "marketing_angles": ["راحتی در استفاده روزانه"],
    "positioning": "گزینه اقتصادی و سبک در رده کفش‌های اسپرت شهری",
    "recommended_tone": "صمیمی",
    "content_ideas": ["ریلز مقایسه وزن با کفش معمولی"],
    "use_cases": ["پیاده‌روی روزانه"],
}


class AnalyzeEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش اسپرت")
        self.client.force_authenticate(user=self.user)

    @patch("apps.ai.views.analyze_product_task")
    def test_analyze_returns_202_and_creates_job(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="celery-id-1")
        resp = self.client.post(f"/api/v1/products/{self.product.id}/analyze/")
        self.assertEqual(resp.status_code, 202, resp.content)
        job = Job.objects.get(id=resp.data["job_id"])
        self.assertEqual(job.type, Job.Type.PRODUCT_ANALYSIS)
        self.assertEqual(job.store, self.store)
        mock_task.delay.assert_called_once_with(job.id, self.product.id)

    @patch("apps.ai.views.analyze_product_task")
    def test_broker_unavailable_marks_job_failed(self, mock_task):
        mock_task.delay.side_effect = OSError("connection refused")
        resp = self.client.post(f"/api/v1/products/{self.product.id}/analyze/")
        self.assertEqual(resp.status_code, 503)
        job = Job.objects.get(id=resp.data["job"]["id"])
        self.assertEqual(job.state, Job.State.FAILED)

    def test_cannot_analyze_foreign_product(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        foreign = Product.objects.create(store=bob_store, name="B1")
        resp = self.client.post(f"/api/v1/products/{foreign.id}/analyze/")
        self.assertEqual(resp.status_code, 404)

    def test_intelligence_is_empty_not_an_error_before_analysis(self):
        # a product that was never analyzed is a normal state; 404 here used to
        # print a red error in the browser console on every page load
        resp = self.client.get(f"/api/v1/products/{self.product.id}/intelligence/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data)

    def test_market_analysis_is_empty_not_an_error_before_research(self):
        resp = self.client.get(f"/api/v1/products/{self.product.id}/market-analysis/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data)


class AnalyzeTaskTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش اسپرت", description="کفش سبک"
        )
        self.job = Job.objects.create(
            store=self.store, type=Job.Type.PRODUCT_ANALYSIS, context={"product_id": self.product.id}
        )

    @patch("apps.ai.tasks.vision_provider")
    @patch("apps.ai.tasks.text_provider")
    def test_successful_analysis_creates_intelligence(self, mock_text, mock_vision):
        provider = mock_text.return_value
        mock_vision.return_value = provider
        provider.generate_json.return_value = (VALID_INTELLIGENCE, "{}")

        analyze_product_task.apply(args=(self.job.id, self.product.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.state, Job.State.COMPLETED, self.job.error)
        intelligence = ProductIntelligence.objects.get(product=self.product)
        self.assertEqual(intelligence.recommended_tone, "صمیمی")
        request = AIRequest.objects.get(task_type=AIRequest.TaskType.REASONING)
        self.assertEqual(request.status, AIRequest.Status.OK)
        # API exposes it now
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(f"/api/v1/products/{self.product.id}/intelligence/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary"], VALID_INTELLIGENCE["summary"])

    @patch("apps.ai.tasks.vision_provider")
    @patch("apps.ai.tasks.text_provider")
    def test_malformed_output_fails_job(self, mock_text, mock_vision):
        provider = mock_text.return_value
        mock_vision.return_value = provider
        provider.generate_json.side_effect = OllamaMalformedOutput("not json")

        analyze_product_task.apply(args=(self.job.id, self.product.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.state, Job.State.FAILED)
        self.assertIn("not json", self.job.error)
        request = AIRequest.objects.latest("id")
        self.assertEqual(request.status, AIRequest.Status.MALFORMED_OUTPUT)
        self.assertFalse(ProductIntelligence.objects.filter(product=self.product).exists())

    @patch("apps.ai.tasks.vision_provider")
    @patch("apps.ai.tasks.text_provider")
    def test_validation_failure_fails_job(self, mock_text, mock_vision):
        provider = mock_text.return_value
        mock_vision.return_value = provider
        provider.generate_json.return_value = ({"summary": "فقط خلاصه"}, "{}")

        analyze_product_task.apply(args=(self.job.id, self.product.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.state, Job.State.FAILED)
        request = AIRequest.objects.latest("id")
        self.assertEqual(request.status, AIRequest.Status.VALIDATION_FAILED)


VALID_MARKET = {
    "observations": ["رقیب X این محصول را ۱٬۲۰۰٬۰۰۰ تومان می‌فروشد"],
    "competitor_positioning": ["احتمالاً رقبا روی قیمت پایین تمرکز دارند"],
    "common_messaging": ["تاکید بر ارسال رایگان"],
    "content_patterns": ["ریلز کوتاه محصول‌محور"],
    "pricing_observations": ["۱٬۲۰۰٬۰۰۰ تومان (از ورودی کاربر)"],
    "common_customer_concerns": ["نگرانی از کیفیت جنس"],
    "content_gaps": ["محتوای آموزشی استفاده از محصول کم است"],
    "differentiation_opportunities": ["گارانتی مرجوعی ۷ روزه"],
    "strategy_summary": "تمرکز بر کیفیت و گارانتی به‌جای رقابت قیمتی",
    "confidence": "MEDIUM",
}


class MarketAnalysisTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش اسپرت")
        self.client.force_authenticate(user=self.user)

    @patch("apps.ai.views.analyze_market_task")
    def test_market_analyze_returns_202_and_creates_job(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="celery-id-2")
        resp = self.client.post(
            f"/api/v1/products/{self.product.id}/market-analysis/",
            {"research_inputs": "رقیب X قیمت ۱٬۲۰۰٬۰۰۰"},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        job = Job.objects.get(id=resp.data["job_id"])
        self.assertEqual(job.type, Job.Type.MARKET_ANALYSIS)
        mock_task.delay.assert_called_once_with(
            job.id, self.product.id, "رقیب X قیمت ۱٬۲۰۰٬۰۰۰"
        )

    def test_market_get_is_empty_not_an_error_before_analysis(self):
        resp = self.client.get(f"/api/v1/products/{self.product.id}/market-analysis/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data)

    def test_cannot_analyze_foreign_product_market(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        foreign = Product.objects.create(store=bob_store, name="B1")
        resp = self.client.post(f"/api/v1/products/{foreign.id}/market-analysis/")
        self.assertEqual(resp.status_code, 404)

    SAMPLE_WEB = {
        "fetched_at": "2026-08-27T12:00:00+00:00",
        "query": "کفش اسپرت",
        "sources": [{"source": "digikala", "ok": True, "count": 1}],
        "items": [
            {
                "source": "digikala",
                "title": "کفش اسپرت رقیب",
                "price_toman": 1190000,
                "url": "https://www.digikala.com/product/dkp-1/",
            }
        ],
    }

    @patch("services.research.web.research_product")
    @patch("apps.ai.tasks.text_provider")
    def test_market_task_creates_research(self, mock_provider_cls, mock_research):
        mock_research.return_value = dict(self.SAMPLE_WEB)
        provider = mock_provider_cls.return_value
        provider.generate_json.return_value = (dict(VALID_MARKET), "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.MARKET_ANALYSIS)

        analyze_market_task.apply(args=(job.id, self.product.id, "یادداشت اختیاری"))

        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        research = MarketResearch.objects.get(product=self.product)
        self.assertEqual(research.confidence, "MEDIUM")
        self.assertEqual(research.observations, VALID_MARKET["observations"])
        self.assertEqual(
            research.conclusions["strategy_summary"], VALID_MARKET["strategy_summary"]
        )
        self.assertNotIn("observations", research.conclusions)
        # automated web research is stored with the analysis
        self.assertEqual(research.web_results["items"][0]["price_toman"], 1190000)
        mock_research.assert_called_once()
        # exposed via API
        resp = self.client.get(f"/api/v1/products/{self.product.id}/market-analysis/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["confidence"], "MEDIUM")
        self.assertEqual(len(resp.data["web_results"]["items"]), 1)

    @patch("services.research.web.research_product")
    @patch("apps.ai.tasks.text_provider")
    def test_market_task_validation_failure(self, mock_provider_cls, mock_research):
        mock_research.return_value = {"fetched_at": "x", "query": "q", "sources": [], "items": []}
        provider = mock_provider_cls.return_value
        provider.generate_json.return_value = ({"strategy_summary": "ناقص"}, "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.MARKET_ANALYSIS)

        analyze_market_task.apply(args=(job.id, self.product.id, ""))

        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertFalse(MarketResearch.objects.filter(product=self.product).exists())


class EmbeddingsTests(APITestCase):
    """Semantic product search: OFF by default, transparent fallback on failure."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.shoe = Product.objects.create(
            store=self.store, name="کفش دویدن", description="کفش ورزشی سبک", price=100
        )
        self.bag = Product.objects.create(
            store=self.store, name="کیف چرمی", description="کیف اداری", price=200
        )
        self.client.force_authenticate(user=self.user)

    def test_disabled_by_default_returns_empty_and_keyword_fallback(self):
        from services.ai.embeddings import semantic_product_ids
        from apps.customers.agent import relevant_products

        self.assertEqual(semantic_product_ids(self.store, "کفش"), [])
        products = relevant_products(self.store, "کفش")
        self.assertEqual(products[0].id, self.shoe.id)  # keyword retrieval still works

    def test_rebuild_endpoint_rejected_when_disabled(self):
        resp = self.client.post(f"/api/v1/stores/{self.store.id}/embeddings/rebuild/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "embeddings_disabled")
        resp = self.client.get(f"/api/v1/stores/{self.store.id}/embeddings/")
        self.assertFalse(resp.data["enabled"])
        self.assertEqual(resp.data["embedded"], 0)

    def _enable(self):
        from django.conf import settings

        return patch.dict(settings.UPMARKET_AI, {"EMBEDDINGS_ENABLED": True})

    @patch("services.ai.embeddings.requests.post")
    def test_semantic_search_ranks_by_cosine(self, mock_post):
        from services.ai.embeddings import ensure_product_embedding, semantic_product_ids

        vectors = {
            "کفش": [1.0, 0.0],
            "کیف": [0.0, 1.0],
        }

        def fake_post(url, json=None, timeout=None):
            batch = []
            for text in json["input"]:
                key = "کفش" if "کفش" in text else "کیف"
                batch.append(vectors[key])
            return MagicMock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {"embeddings": batch},
            )

        mock_post.side_effect = fake_post
        with self._enable():
            ensure_product_embedding(self.shoe)
            ensure_product_embedding(self.bag)
            ids = semantic_product_ids(self.store, "کفش راحتی می‌خواهم")
            self.assertEqual(ids[0], self.shoe.id)

            # sales-agent retrieval puts the semantic hit first
            from apps.customers.agent import relevant_products

            products = relevant_products(self.store, "کفش راحتی می‌خواهم")
            self.assertEqual(products[0].id, self.shoe.id)

    @patch("services.ai.embeddings.requests.post")
    def test_embedding_failure_falls_back_to_keywords(self, mock_post):
        import requests as requests_lib

        from apps.customers.agent import relevant_products
        from services.ai.embeddings import semantic_product_ids
        from .models import ProductEmbedding

        ProductEmbedding.objects.create(
            product=self.shoe, vector=[1.0, 0.0], model="m", source_hash="x"
        )
        mock_post.side_effect = requests_lib.ConnectionError("down")
        with self._enable():
            self.assertEqual(semantic_product_ids(self.store, "کفش"), [])
            products = relevant_products(self.store, "کفش")
            self.assertEqual(products[0].id, self.shoe.id)

    @patch("services.ai.embeddings.requests.post")
    def test_unchanged_product_not_reembedded(self, mock_post):
        from services.ai.embeddings import ensure_product_embedding

        mock_post.return_value = MagicMock(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"embeddings": [[0.5, 0.5]]},
        )
        with self._enable():
            ensure_product_embedding(self.shoe)
            ensure_product_embedding(self.shoe)  # same text → no second call
        self.assertEqual(mock_post.call_count, 1)

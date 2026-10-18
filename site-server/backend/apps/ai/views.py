from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.serializers import JobSerializer
from apps.jobs.services import dispatch_job
from apps.products.models import Product
from apps.stores.models import Store
from services.ai import embeddings as embedding_service

from .models import MarketResearch, ProductEmbedding, ProductIntelligence
from .serializers import MarketResearchSerializer, ProductIntelligenceSerializer
from .tasks import analyze_market_task, analyze_product_task, build_embeddings_task
from apps.stores import access


class ProductAnalyzeView(APIView):
    """POST /api/v1/products/{id}/analyze/ → 202 {job_id} (runs on Celery)."""

    def post(self, request, pk):
        product = get_object_or_404(
            Product.objects.filter(store__in=access.stores_for(request.user)).select_related("store"), pk=pk
        )
        job = Job.objects.create(
            store=product.store,
            type=Job.Type.PRODUCT_ANALYSIS,
            state=Job.State.QUEUED,
            context={"product_id": product.id},
        )
        error = dispatch_job(job, analyze_product_task, job.id, product.id)
        if error is not None:
            return error
        job.refresh_from_db()
        return Response(
            {"job_id": job.id, "job": JobSerializer(job).data}, status=status.HTTP_202_ACCEPTED
        )


class EmbeddingsView(APIView):
    """Semantic product search vectors.

    GET  /api/v1/stores/{store_id}/embeddings/  → feature status + coverage
    POST /api/v1/stores/{store_id}/embeddings/rebuild/ → backfill job (202)
    """

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        total = store.products.filter(is_available=True).count()
        embedded = ProductEmbedding.objects.filter(
            product__store=store, product__is_available=True
        ).count()
        return Response(
            {
                "enabled": embedding_service.is_enabled(),
                "model": embedding_service.embedding_model(),
                "products": total,
                "embedded": embedded,
            }
        )

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        if not embedding_service.is_enabled():
            return Response(
                {
                    "error": {
                        "code": "embeddings_disabled",
                        "message": "جستجوی معنایی غیرفعال است. در backend/.env مقدار "
                        "EMBEDDINGS_ENABLED=true بگذارید و مدل embedding را روی Ollama نصب کنید "
                        "(مثلاً: ollama pull nomic-embed-text). تا آن موقع جستجوی کلیدواژه‌ای فعال است.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        job = Job.objects.create(
            store=store, type=Job.Type.EMBEDDING_BUILD, context={"store_id": store.id}
        )
        error = dispatch_job(job, build_embeddings_task, job.id, store.id)
        if error is not None:
            return error
        job.refresh_from_db()
        return Response(
            {"job_id": job.id, "job": JobSerializer(job).data}, status=status.HTTP_202_ACCEPTED
        )


class ProductIntelligenceView(APIView):
    """GET /api/v1/products/{id}/intelligence/ -> the analysis, or 200 + null.

    "not analyzed yet" is a normal state of a product page, not an error: a 404
    here painted the browser console red on every single page load (beter.md #10).
    """

    def get(self, request, pk):
        product = get_object_or_404(Product.objects.filter(store__in=access.stores_for(request.user)), pk=pk)
        intelligence = ProductIntelligence.objects.filter(product=product).first()
        if intelligence is None:
            return Response(None)
        return Response(ProductIntelligenceSerializer(intelligence).data)


class MarketAnalysisView(APIView):
    """GET = latest market research; POST = run a new analysis (202 + job)."""

    def get(self, request, pk):
        # 200 + null when nothing has been researched yet — same reason as
        # ProductIntelligenceView: a normal empty state must not log as an error
        product = get_object_or_404(Product.objects.filter(store__in=access.stores_for(request.user)), pk=pk)
        research = MarketResearch.objects.filter(product=product).first()
        if research is None:
            return Response(None)
        return Response(MarketResearchSerializer(research).data)

    def post(self, request, pk):
        product = get_object_or_404(
            Product.objects.filter(store__in=access.stores_for(request.user)).select_related("store"), pk=pk
        )
        research_inputs = str(request.data.get("research_inputs", "") or "")
        job = Job.objects.create(
            store=product.store,
            type=Job.Type.MARKET_ANALYSIS,
            state=Job.State.QUEUED,
            context={"product_id": product.id},
        )
        error = dispatch_job(job, analyze_market_task, job.id, product.id, research_inputs)
        if error is not None:
            return error
        job.refresh_from_db()
        return Response(
            {"job_id": job.id, "job": JobSerializer(job).data}, status=status.HTTP_202_ACCEPTED
        )

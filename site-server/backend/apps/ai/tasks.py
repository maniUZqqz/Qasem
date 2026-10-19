"""Celery tasks for the AI domain. Routed to the `ai` queue (see settings)."""
import base64
import logging

from celery import shared_task

from apps.jobs.models import Job
from apps.products.models import Product
from services.ai.gateway import text_provider, vision_provider
from services.ai.prompts import market_analysis as market_prompts
from services.ai.prompts import product_analysis as prompts
from services.ai.router import TASK_REASONING, TASK_VISION, models_for

from .models import AIRequest, MarketResearch, ProductIntelligence
from .services import recorded_json_call as _recorded_json_call
from services.ai import embeddings as embedding_service
from services import gpu

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def analyze_product_task(self, job_id, product_id):
    """VISION per product image → REASONING synthesis → ProductIntelligence."""
    job = Job.objects.get(id=job_id)
    try:
        product = (
            Product.objects.select_related("store")
            .prefetch_related("images", "attributes")
            .get(id=product_id)
        )
        # vision and reasoning may now be served by different providers —
        # one local, one API — so each stage resolves its own
        vision = vision_provider(product.store)
        reasoner = text_provider(product.store)
        images = list(product.images.all())
        job.total_steps = len(images) + 1
        job.mark_running("در حال تحلیل تصاویر محصول")
        vision_models = models_for(TASK_VISION)
        # free ComfyUI VRAM and evict every other model so this one fits
        gpu.before_ollama_work(vision_models[0])

        visual_analyses = []
        for index, product_image in enumerate(images, start=1):
            with product_image.image.open("rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("ascii")
            parsed, _ = _recorded_json_call(
                job=job,
                store=product.store,
                task_type=AIRequest.TaskType.VISION,
                prompt_id=prompts.VISION_PROMPT_ID,
                prompt_version=prompts.VISION_PROMPT_VERSION,
                provider=vision,
                models=vision_models,
                prompt=prompts.build_vision_prompt(product),
                images=[encoded],
            )
            visual_analyses.append(parsed)
            job.mark_progress(index, f"تصویر {index} از {len(images)} تحلیل شد")

        job.mark_progress(len(images), "در حال تولید استراتژی و هوش محصول")
        reasoning_models = models_for(TASK_REASONING)
        # the vision model is still resident here — evict it or the reasoning
        # model lands half on the CPU and the run times out (beter.md v2 #9)
        gpu.before_ollama_work(reasoning_models[0])
        parsed, request_row = _recorded_json_call(
            job=job,
            store=product.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=prompts.REASONING_PROMPT_ID,
            prompt_version=prompts.REASONING_PROMPT_VERSION,
            provider=reasoner,
            models=reasoning_models,
            prompt=prompts.build_reasoning_prompt(product, visual_analyses),
            system=prompts.REASONING_SYSTEM,
            # checked inside the call so an incomplete answer falls through to
            # the next installed model instead of failing the job
            validate=prompts.validate_intelligence,
            validation_message="تحلیل محصول ناقص بود",
        )

        intelligence, _ = ProductIntelligence.objects.update_or_create(
            product=product,
            defaults={
                "summary": parsed.get("summary", ""),
                "target_audience": parsed.get("target_audience", []),
                "selling_points": parsed.get("selling_points", []),
                "weaknesses": parsed.get("weaknesses", []),
                "objections": parsed.get("objections", []),
                "marketing_angles": parsed.get("marketing_angles", []),
                "positioning": parsed.get("positioning", ""),
                "recommended_tone": parsed.get("recommended_tone", ""),
                "content_ideas": parsed.get("content_ideas", []),
                "use_cases": parsed.get("use_cases", []),
                "visual_analysis": visual_analyses,
                "source_request": request_row,
            },
        )
        job.mark_progress(job.total_steps, "")
        job.mark_completed({"intelligence_id": intelligence.id, "product_id": product.id})
        return {"intelligence_id": intelligence.id}
    except Exception as exc:  # noqa: BLE001 — job must always end in a terminal state
        logger.exception("Product analysis job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def analyze_market_task(self, job_id, product_id, research_inputs=""):
    """Automated web research (code) → REASONING (qwq) → MarketResearch row."""
    from services.research.web import research_product

    job = Job.objects.get(id=job_id)
    try:
        product = (
            Product.objects.select_related("store").prefetch_related("attributes").get(id=product_id)
        )
        intelligence = ProductIntelligence.objects.filter(product=product).first()
        provider = text_provider(product.store)
        job.total_steps = 2
        job.mark_running("در حال جستجوی خودکار رقبا در وب (دیجی‌کالا/ترب)")

        # Real competitor data fetched by code — the owner enters nothing.
        # Marketplaces get the plain product name; general web gets a buying-intent
        # query so competitor SITES surface too.
        query = f"{product.name} {product.brand}".strip()
        web_results = research_product(query, web_query=f"خرید {query}")
        job.mark_progress(1, "در حال تحلیل بازار و رقبا")
        reasoning_models = models_for(TASK_REASONING)
        gpu.before_ollama_work(reasoning_models[0])

        parsed, request_row = _recorded_json_call(
            job=job,
            store=product.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=market_prompts.MARKET_PROMPT_ID,
            prompt_version=market_prompts.MARKET_PROMPT_VERSION,
            provider=provider,
            models=reasoning_models,
            prompt=market_prompts.build_market_prompt(
                product, intelligence, research_inputs, web_results
            ),
            system=market_prompts.MARKET_SYSTEM,
            validate=market_prompts.validate_market,
            validation_message="تحلیل بازار ناقص بود",
        )

        research = MarketResearch.objects.create(
            store=product.store,
            product=product,
            research_inputs=research_inputs,
            web_results=web_results,
            observations=parsed.get("observations", []),
            conclusions={
                key: parsed.get(key)
                for key in market_prompts.REQUIRED_KEYS
                if key not in {"observations", "confidence"}
            },
            confidence=parsed.get("confidence", MarketResearch.Confidence.LOW),
            source_request=request_row,
        )
        job.mark_progress(2, "")
        job.mark_completed({"market_research_id": research.id, "product_id": product.id})
        return {"market_research_id": research.id}
    except Exception as exc:  # noqa: BLE001 — job must always end in a terminal state
        logger.exception("Market analysis job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def embed_product_task(self, product_id):
    """Refresh one product's embedding (fired on product save when enabled)."""
    if not embedding_service.is_enabled():
        return {"skipped": "embeddings disabled"}
    try:
        product = Product.objects.prefetch_related("attributes").get(id=product_id)
    except Product.DoesNotExist:
        return {"skipped": "product gone"}
    try:
        embedding_service.ensure_product_embedding(product)
        return {"product_id": product_id}
    except Exception as exc:  # noqa: BLE001 — embedding is best-effort; search falls back
        logger.warning("Embedding for product %s failed: %s", product_id, exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def build_embeddings_task(self, job_id, store_id):
    """Backfill/refresh embeddings for every available product of a store."""
    job = Job.objects.get(id=job_id)
    try:
        if not embedding_service.is_enabled():
            raise RuntimeError(
                "جستجوی معنایی غیرفعال است — EMBEDDINGS_ENABLED=true و یک مدل embedding "
                "(مثلاً `ollama pull nomic-embed-text`) لازم است."
            )
        products = list(
            Product.objects.filter(store_id=store_id, is_available=True).prefetch_related(
                "attributes"
            )
        )
        job.total_steps = len(products)
        job.mark_running("در حال ساخت بردارهای محصولات")
        built, failed = 0, []
        for step, product in enumerate(products, start=1):
            job.mark_progress(step, f"محصول {step} از {len(products)}")
            try:
                embedding_service.ensure_product_embedding(product)
                built += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{product.name}: {exc}")
        if failed and not built:
            raise RuntimeError("هیچ برداری ساخته نشد: " + "; ".join(failed[:3]))
        job.mark_completed({"built": built, "failed": len(failed), "errors": failed[:10]})
        return {"built": built, "failed": len(failed)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Embedding build job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


# Registered here so the worker (autodiscovers `apps.ai.tasks`) knows it.
from . import competitor_tasks  # noqa: E402,F401

"""The five public APIs. §28 of `ایده‌ها پنل.md`.

Sales Admin · Text & Caption · Advertising Video · Advertising Poster ·
Product Showcase.

Every one of them is a thin wrapper over the task the panel already calls. That
is the whole design: §28 says "این همان سیستمی است که خودمان استفاده می‌کنیم",
and a second implementation would drift from the first within a month — the API
would keep a rule the panel dropped, or miss a fix the panel got.

Three things every endpoint here does, and the panel does too:

* **Bills the same allowance.** A caption through the API spends the same
  caption as a caption through the panel, because it spends the same GPU.
* **Respects the store's data policy.** An API caller does not get to send a
  `Local Only` shop's data to an external model by asking differently.
* **Answers with a job id for anything slow.** A video takes minutes; holding
  an HTTP connection open for that is a broken integration on every network in
  between.
"""
from __future__ import annotations

import time

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.serializers import JobSerializer
from apps.jobs.services import dispatch_job
from apps.products.models import Product

from . import sandbox
from .auth import APIKeyAuthentication, record


class APIThrottle(UserRateThrottle):
    """A ceiling on calls, separate from the monthly allowance.

    The allowance stops a shop spending more GPU than they paid for. This stops
    a loop in their code spending all of it in ten seconds and leaving them
    with nothing for the rest of the month — which is a bug in their software
    that our system should not amplify.

    **Counted per key, not per shop.** Each key is one integration, and a bug in
    the shop's website should not take down their CRM sync. The store-wide
    ceiling is the monthly allowance, which already exists.
    """

    scope = "public_api"

    def get_cache_key(self, request, view):
        """DRF's default reaches for `request.user.pk`, and the thing calling
        this API is a key, not a person.

        This was a 500 on every real API call: `APIKeyUser` carries a store, not
        a primary key, and every test in the suite skipped this path because
        `IS_TEST` short-circuits `allow_request` below.
        """
        key = getattr(request.user, "api_key", None)
        if key is not None:
            return self.cache_format % {"scope": self.scope, "ident": key.prefix}
        return super().get_cache_key(request, view)

    def allow_request(self, request, view):
        from django.conf import settings

        if getattr(settings, "IS_TEST", False):
            return True
        return super().allow_request(request, view)


class PublicAPIView(APIView):
    """Shared behaviour: key auth, throttling, call logging, quota mapping."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIThrottle]

    #: Set by each endpoint; used for the call log and for key scopes.
    endpoint = "unknown"

    def dispatch(self, request, *args, **kwargs):
        started = time.monotonic()
        response = super().dispatch(request, *args, **kwargs)
        record(request, response, self.endpoint, started)
        return response

    # ------------------------------------------------------------------

    @property
    def store(self):
        return self.request.user.store

    def check_scope(self):
        """A narrowed key may not call everything."""
        key = getattr(self.request.user, "api_key", None)
        if key is not None and not key.allows(self.endpoint):
            return Response(
                {"error": {
                    "code": "scope_denied",
                    "message": f"این کلید اجازه‌ی «{self.endpoint}» را ندارد.",
                }},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def product_or_404(self, product_id):
        return get_object_or_404(
            Product.objects.filter(store=self.store).select_related("store"),
            pk=product_id,
        )

    @property
    def is_sandbox(self) -> bool:
        key = getattr(self.request.user, "api_key", None)
        return bool(key and key.is_test)

    def start(self, task, job_type, *args, context=None):
        """Queue work and answer with a job id.

        Never blocks. A video takes minutes and an HTTP connection held that
        long fails somewhere in between, leaving the caller unable to tell a
        timeout from a failure.
        """
        if self.is_sandbox:
            # Stopped at the last possible moment: everything before this —
            # auth, scope, the product lookup, the argument validation — ran
            # exactly as it does for a live key, so a sandbox call that
            # succeeds is a live call that will succeed.
            return Response(
                sandbox.queued(self.endpoint, None),
                status=status.HTTP_202_ACCEPTED,
            )

        job = Job.objects.create(
            store=self.store, type=job_type, context=context or {},
        )
        failed = dispatch_job(job, task, job.id, *args)
        if failed is not None:
            return failed
        return Response(
            {"job_id": job.id, "status_url": f"/api/v1/public/jobs/{job.id}/"},
            status=status.HTTP_202_ACCEPTED,
        )


# ---------------------------------------------------------------- 28.1


class SalesAgentAPI(PublicAPIView):
    """Answer a customer message the way the shop's agent would. §28.1

    Synchronous, unlike the others: a sales reply is useless in two minutes,
    and the caller is usually holding a chat window open.
    """

    endpoint = "sales_agent"

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied

        from apps.customers.agent import SalesRulesUnmet, run_sales_agent
        from apps.customers.models import Conversation, Customer
        from services.ai.ollama import OllamaError

        text = str(request.data.get("message", "")).strip()
        if not text:
            return Response(
                {"error": {"code": "empty", "message": "message لازم است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if self.is_sandbox:
            product = Product.objects.filter(store=self.store).first()
            return Response(sandbox.sales_agent(self.store, product, text))

        # The caller identifies their own end user. Threads are per external
        # id so a conversation has history, which is what makes the agent
        # answer "the blue one" correctly on the third message.
        external_id = str(request.data.get("customer_id", "")).strip() or "api-guest"
        customer, _ = Customer.objects.get_or_create(
            store=self.store, external_id=external_id,
            defaults={"name": request.data.get("customer_name", "مشتری")},
        )
        conversation, _ = Conversation.objects.get_or_create(
            store=self.store, customer=customer, channel="API",
            defaults={"external_id": external_id},
        )

        try:
            result = run_sales_agent(conversation, text)
        except SalesRulesUnmet as exc:
            return Response(
                {"error": {"code": "rules_unmet", "message": str(exc)}},
                status=status.HTTP_409_CONFLICT,
            )
        except OllamaError as exc:
            return Response(
                {"error": {"code": "ai_unavailable", "message": str(exc)}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({
            "reply": result["reply"],
            "intent": result["intent"],
            "action": result["action"],
            "needs_human": result["needs_human"],
            "products": result.get("product_ids", []),
            "order": result.get("order"),
            "conversation_id": conversation.pk,
        })


# ---------------------------------------------------------------- 28.2


class CaptionAPI(PublicAPIView):
    """Sales copy and captions for one product. §28.2"""

    endpoint = "caption"

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied

        from apps.content.tasks import generate_captions_task

        product = self.product_or_404(request.data.get("product_id"))
        platforms = request.data.get("platforms") or ["instagram"]
        return self.start(
            generate_captions_task, Job.Type.CAPTION_GENERATION,
            product.pk, platforms,
            context={"product_id": product.pk, "via": "api"},
        )


# ---------------------------------------------------------------- 28.3


class VideoAPI(PublicAPIView):
    """An advertising video for one product. §28.3"""

    endpoint = "video"

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied

        from apps.content.tasks import generate_video_script_task

        product = self.product_or_404(request.data.get("product_id"))
        try:
            duration = int(request.data.get("duration", 15))
        except (TypeError, ValueError):
            duration = 15

        # The script first: video generation needs scenes, and an API that
        # silently made both would bill twice for one call.
        return self.start(
            generate_video_script_task, Job.Type.VIDEO_SCRIPT,
            product.pk, duration, str(request.data.get("objective", "")),
            context={"product_id": product.pk, "via": "api"},
        )


# ---------------------------------------------------------------- 28.4


class PosterAPI(PublicAPIView):
    """A poster: AI makes the image, code lays the Persian text on it. §28.4A"""

    endpoint = "poster"

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied

        from apps.content.models import GeneratedImage
        from apps.content.tasks import generate_image_task

        product = self.product_or_404(request.data.get("product_id"))
        return self.start(
            generate_image_task, Job.Type.IMAGE_GENERATION,
            product.pk, GeneratedImage.Kind.POSTER,
            str(request.data.get("style", "")),
            str(request.data.get("instructions", "")),
            context={"product_id": product.pk, "via": "api"},
        )


class ShowcaseAPI(PublicAPIView):
    """The real product, in a scene. §28.4B

    A separate endpoint from the poster rather than a parameter, because the
    two make opposite promises: a poster may reinvent the scene freely, a
    showcase must keep the customer's actual product recognisable. Hiding that
    behind a flag is how a caller gets the wrong one.
    """

    endpoint = "showcase"

    def post(self, request):
        denied = self.check_scope()
        if denied:
            return denied

        from apps.content.models import GeneratedImage
        from apps.content.tasks import generate_image_task

        product = self.product_or_404(request.data.get("product_id"))
        kind = (
            GeneratedImage.Kind.ENHANCED
            if request.data.get("mode") == "enhance"
            else GeneratedImage.Kind.PRODUCT_SHOT
        )
        return self.start(
            generate_image_task, Job.Type.IMAGE_GENERATION,
            product.pk, kind,
            str(request.data.get("style", "")),
            str(request.data.get("instructions", "")),
            context={"product_id": product.pk, "via": "api"},
        )


# ------------------------------------------------------------ job status


class PublicJobView(PublicAPIView):
    """Where an integration finds out whether its work finished."""

    endpoint = "job_status"

    def get(self, request, pk):
        if sandbox.is_sandbox_job(pk):
            # Always COMPLETED. A sandbox job that stayed QUEUED would make the
            # caller write a polling loop that never exits, which is worse than
            # having no sandbox at all.
            return Response(sandbox.job_status(str(pk)))

        job = Job.objects.filter(store=self.store, pk=pk).first()
        if job is None:
            return Response(
                {"error": {"code": "not_found", "message": "این کار پیدا نشد."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = JobSerializer(job).data
        return Response({
            "id": job.pk,
            "state": data["state"],
            "state_label": data["state_label"],
            "progress": {
                "step": job.progress_step,
                "total": job.total_steps,
                "label": job.current_step_label,
            },
            "awaiting_human": data["awaiting_human"],
            "result": job.result,
            "error": job.error,
        })

"""The trending page. §6 of `ایده‌ها پنل.md`.

§6.3 is the part that shapes this file: «کاربر باید بتواند از همین صفحه یک Trend
را انتخاب کند و مستقیماً وارد صفحه تولید محتوا شود». So `TrendIdeaUseView` does
not hand the panel a pre-filled form to submit — it starts the generation job
itself, with the trend and the product already attached. An idea that requires
the shop to retype it somewhere else is an idea most shops abandon.
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.research import trends as source

from . import trends as engine
from .trend_models import Trend, TrendIdea

logger = logging.getLogger(__name__)


class TrendSerializer(serializers.ModelSerializer):
    region_title = serializers.CharField(read_only=True)
    is_stale = serializers.BooleanField(read_only=True)
    age_hours = serializers.IntegerField(read_only=True)
    #: Headlines that explain *why* it trends (title, url, source).
    news = serializers.ListField(read_only=True)
    relevance = serializers.SerializerMethodField()
    also_in = serializers.SerializerMethodField()

    class Meta:
        model = Trend
        fields = [
            "id", "title", "region", "region_title", "traffic", "context",
            "image", "source", "seen_at", "is_stale", "age_hours", "news",
            "relevance", "also_in",
        ]

    def get_relevance(self, trend):
        vocabulary = self.context.get("vocabulary")
        if vocabulary is None:
            return None
        rel = engine.relevance(trend, vocabulary)
        llm = (self.context.get("llm") or {}).get(trend.pk)
        if llm:
            rel["llm"] = llm
        return rel

    def get_also_in(self, trend):
        return (self.context.get("also_in") or {}).get(trend.pk, [])


class TrendIdeaSerializer(serializers.ModelSerializer):
    trend_title = serializers.CharField(source="trend.title", read_only=True)
    product_name = serializers.CharField(
        source="product.name", read_only=True, default=None,
    )
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = TrendIdea
        fields = [
            "id", "trend", "trend_title", "product", "product_name", "kind",
            "kind_label", "idea", "hook", "why", "state", "expired",
            "job_id", "created_at",
        ]


class TrendListView(APIView):
    """What is trending, and which sources we could actually reach."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        regions = [
            r for r in request.query_params.get("regions", "").split(",") if r
        ] or None
        rows = engine.current(regions, limit=200)

        # «جهانی»: the same search rising in several countries at once.
        from services.research.product_match import normalize

        by_title: dict[str, set] = {}
        for trend in rows:
            if trend.region != source.INSTAGRAM:
                by_title.setdefault(normalize(trend.title), set()).add(trend.region)
        also_in = {
            t.pk: sorted(source.REGION_TITLES.get(r, r) for r in by_title.get(normalize(t.title), set()) if r != t.region)
            for t in rows
        }
        vocabulary = engine.store_vocabulary(store)
        llm = engine.stored_llm_relevance(store)

        def rank(t):
            rel = engine.relevance(t, vocabulary)
            llm_level = (llm.get(t.pk) or {}).get("relevance") or 0
            # Either signal can put a trend on top; both are shown on the card,
            # so a disagreement is visible rather than silently resolved.
            return (
                -max(llm_level, min(2, rel["score"])),
                -len(also_in.get(t.pk, [])),
                -t.seen_at.timestamp(),
            )

        global_view = bool(regions) and source.ALL in regions
        if global_view:
            # One card per story, the most widespread first.
            seen, unique = set(), []
            for t in sorted(rows, key=lambda t: -len(also_in.get(t.pk, []))):
                key = normalize(t.title)
                if t.region != source.INSTAGRAM and key in seen:
                    continue
                seen.add(key)
                unique.append(t)
            rows = unique
        rows = sorted(rows, key=rank)[:80]

        # Whether a text model is *configured* for this store — no network
        # probe on page load; «سنجش با هوش مصنوعی» finds out when pressed.
        try:
            from services.ai import gateway, providers

            resolved = gateway.resolve(providers.TEXT, store)
            llm_ok, llm_note = True, getattr(resolved, "name", "") or ""
        except Exception as exc:  # noqa: BLE001
            llm_ok, llm_note = False, str(exc)[:200]
        return Response({
            "trends": TrendSerializer(
                rows, many=True,
                context={"vocabulary": vocabulary, "llm": llm, "also_in": also_in},
            ).data,
            "ideas": TrendIdeaSerializer(
                TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN)
                .select_related("trend", "product"),
                many=True,
            ).data,
            "regions": [
                {"key": key, "title": title} for key, title in source.REGIONS.items()
            ] + [
                {"key": source.INSTAGRAM, "title": "اینستاگرام (غیرمستقیم)"},
                {"key": source.ALL, "title": "جهانی (همه‌ی کشورها)"},
            ],
            # Listed rather than hidden: a shop that cannot see Instagram trends
            # should know we did not check, not conclude nothing is happening.
            "sources": source.available(),
            "store_groups": vocabulary["groups"],
            "llm": {"available": llm_ok, "note": llm_note},
        })

    def post(self, request, store_id):
        """Fetch today's trends. Synchronous — it is two HTTP requests."""
        access.get_store(request.user, store_id, access.CONTENT)
        regions = source.expand_regions(request.data.get("regions") or ["IR"])
        try:
            return Response(engine.refresh(regions))
        except Exception as exc:  # noqa: BLE001
            logger.info("Trend refresh failed: %s", exc)
            return Response(
                {"error": {"code": "unavailable", "message": str(exc)}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class TrendIdeaView(APIView):
    """«با این ترند چه بسازیم؟» §6.2"""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        trend_id = request.data.get("trend_id")
        try:
            result = engine.suggest(
                store, regions=request.data.get("regions") or None,
                trend_ids=[trend_id] if trend_id else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Trend suggestion failed for store %s", store_id)
            return Response(
                {"error": {"code": "ai_unavailable", "message": str(exc)}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({
            "ideas": TrendIdeaSerializer(result["ideas"], many=True).data,
            "dropped": result["dropped"],
            "note": result["note"],
        })


class TrendRelevanceView(APIView):
    """Ask the model to rank current trends for this shop — only if reachable.

    Keyword relevance is always shown; this adds the model's 0/1/2 and reason
    next to it. Without a reachable model it answers 503 with the reason and
    nothing changes.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        from . import research_llm

        store = access.get_store(request.user, store_id, access.CONTENT)
        regions = request.data.get("regions") or None
        trends = engine.current(regions, limit=200)
        if not trends:
            return Response({"ranked": 0, "note": "ترندِ تازه‌ای نیست."})
        vocabulary = engine.store_vocabulary(store)
        # The model sees the keyword-relevant ones first, then the rest.
        trends.sort(key=lambda t: -engine.relevance(t, vocabulary)["score"])
        try:
            ranked = engine.rank_with_llm(store, trends[:30])
        except research_llm.LLMUnavailable as exc:
            return Response(
                {"error": {"code": "ai_unavailable",
                           "message": f"مدلِ زبانی در دسترس نیست: {exc}"}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Trend relevance failed: %s", exc)
            return Response(
                {"error": {"code": "ai_failed", "message": str(exc)[:300]}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"ranked": len(ranked)})


class TrendIdeaUseView(APIView):
    """«این را بساز». §6.3 — straight into content generation.

    The trend travels with the request rather than the shop retyping it: §6.3's
    whole point is that the idea does not have to be carried by hand from one
    page to another.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        idea = get_object_or_404(
            TrendIdea.objects.select_related("trend", "product"), pk=pk, store=store,
        )

        if idea.product is None:
            return Response(
                {"error": {
                    "code": "no_product",
                    "message": "این ایده به محصولی وصل نیست؛ اول محصولش را انتخاب کنید.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if idea.trend.is_stale:
            # Refused rather than warned about: the shop is about to spend GPU
            # minutes on a moment that has already passed.
            return Response(
                {"error": {
                    "code": "stale",
                    "message": (
                        f"این ترند {idea.trend.age_hours} ساعت پیش دیده شده و دیگر "
                        "تازه نیست. ترندها را به‌روز کنید."
                    ),
                }},
                status=status.HTTP_409_CONFLICT,
            )

        objective = f"{idea.idea}\n\nقلاب پیشنهادی: {idea.hook}".strip()

        if idea.kind == TrendIdea.Kind.VIDEO:
            from apps.content.tasks import generate_video_script_task

            job = Job.objects.create(
                store=store, type=Job.Type.VIDEO_SCRIPT,
                context={"product_id": idea.product_id, "trend_id": idea.trend_id},
            )
            failed = dispatch_job(
                job, generate_video_script_task, job.id, idea.product_id, 20,
                objective, "fa",
            )
        else:
            from apps.content.tasks import generate_captions_task

            platforms = (
                ["INSTAGRAM"] if idea.kind == TrendIdea.Kind.STORY
                else ["INSTAGRAM", "TELEGRAM"]
            )
            job = Job.objects.create(
                store=store, type=Job.Type.CAPTION_GENERATION,
                context={"product_id": idea.product_id, "trend_id": idea.trend_id},
            )
            failed = dispatch_job(
                job, generate_captions_task, job.id, idea.product_id, platforms,
                "", objective,
            )

        if failed is not None:
            return failed

        idea.state = TrendIdea.State.USED
        idea.job_id = job.id
        idea.save(update_fields=["state", "job_id", "updated_at"])

        return Response(
            {"job_id": job.id, "idea": TrendIdeaSerializer(idea).data},
            status=status.HTTP_202_ACCEPTED,
        )


class TrendIdeaDismissView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        idea = get_object_or_404(TrendIdea, pk=pk, store=store)
        idea.state = TrendIdea.State.DISMISSED
        idea.save(update_fields=["state", "updated_at"])
        return Response(TrendIdeaSerializer(idea).data)

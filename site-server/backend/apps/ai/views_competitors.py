"""Competitors, opportunities and the profit report — §3, §4 and §5.

One module because they are one screen's worth of thinking: who else sells
this, what does it cost us, and what should we do about it.
"""
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import competitor_research, opportunities
from .competitor_models import Competitor, CompetitorProduct, Opportunity


class CompetitorProductSerializer(serializers.ModelSerializer):
    #: «رقیب کالایی» verdict for this row (score, reason, model answer).
    match = serializers.SerializerMethodField()
    matches_name = serializers.CharField(source="matches.name", read_only=True, default=None)
    our_price = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()
    currency_how = serializers.SerializerMethodField()

    class Meta:
        model = CompetitorProduct
        fields = [
            "id", "name", "url", "price_toman", "observed_at",
            "matches", "matches_name", "our_price", "source", "match", "image",
            "link", "currency_how",
        ]
        read_only_fields = ["match", "matches_name", "our_price", "image", "link", "currency_how"]

    def get_match(self, row):
        return (row.raw or {}).get("match")

    def get_our_price(self, row):
        product = row.matches
        return int(product.price) if product is not None and product.price else None

    def get_image(self, row):
        return (row.raw or {}).get("image", "")

    def get_link(self, row):
        # Long Persian URLs do not fit the 200-char column; the full one is in raw.
        return row.url or (row.raw or {}).get("url", "")

    def get_currency_how(self, row):
        return (row.raw or {}).get("currency_how", "")


def _latest_crawl(competitor):
    from apps.jobs.models import Job

    from .competitor_tasks import JOB_KIND

    job = (
        Job.objects.filter(
            store_id=competitor.store_id, type=Job.Type.MARKET_ANALYSIS,
            context__kind=JOB_KIND, context__competitor_id=competitor.pk,
        )
        .order_by("-created_at")
        .first()
    )
    if job is None:
        return None
    return {
        "job_id": job.id, "state": job.state, "progress": job.progress_step,
        "total": job.total_steps, "label": job.current_step_label,
        "error": job.error, "result": job.result, "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


class CompetitorSerializer(serializers.ModelSerializer):
    products = CompetitorProductSerializer(many=True, read_only=True)
    #: Shown next to the conclusions so month-old positioning is read as
    #: history rather than intelligence.
    is_stale = serializers.BooleanField(read_only=True)
    #: Is this a confirmed «رقیب کالایی»? From the stored per-product matches.
    product_competitor = serializers.SerializerMethodField()
    crawl = serializers.SerializerMethodField()
    is_marketplace = serializers.SerializerMethodField()

    class Meta:
        model = Competitor
        fields = [
            "id", "name", "kind", "website", "instagram", "notes",
            "revenue_model", "positioning", "strengths", "weaknesses",
            "analysed_at", "is_stale", "is_active", "products", "created_at",
            "product_competitor", "crawl", "is_marketplace",
        ]
        read_only_fields = ["analysed_at"]

    def get_product_competitor(self, row):
        from services.research import product_match

        return product_match.classify_competitor(
            [(p.raw or {}).get("match") for p in row.products.all() if (p.raw or {}).get("match")]
        )

    def get_crawl(self, row):
        if self.context.get("skip_crawl"):
            return None
        return _latest_crawl(row)

    def get_is_marketplace(self, row):
        return competitor_research.is_marketplace_url(row.website)


class OpportunitySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True, default=None)

    class Meta:
        model = Opportunity
        fields = [
            "id", "kind", "kind_label", "product", "product_name",
            "title", "reason", "action", "evidence", "state", "priority",
            "created_at",
        ]
        read_only_fields = ["kind", "product", "title", "reason", "action", "evidence"]


class CompetitorListView(APIView):
    """GET the shop's competitors, POST to add one."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.PRODUCTS, write=False)
        rows = store.competitors.filter(is_active=True).prefetch_related(
            "products", "products__matches",
        )
        return Response(CompetitorSerializer(rows, many=True).data)

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.PRODUCTS)
        serializer = CompetitorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = serializer.save(store=store)
        except Exception:  # unique (store, name)
            return Response(
                {"error": {
                    "code": "duplicate",
                    "message": "رقیبی با این نام قبلاً ثبت شده است.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(CompetitorSerializer(row).data, status=status.HTTP_201_CREATED)


class CompetitorDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _row(self, request, store_id, pk, write=True):
        permission = access.PRODUCTS
        store = access.get_store(request.user, store_id, permission, write=write)
        return get_object_or_404(Competitor, pk=pk, store=store)

    def patch(self, request, store_id, pk):
        row = self._row(request, store_id, pk)
        serializer = CompetitorSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, store_id, pk):
        row = self._row(request, store_id, pk)
        # Deactivated, not deleted: the observed prices attached to it are the
        # evidence behind pricing suggestions the owner may still be reading.
        row.is_active = False
        row.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompetitorProductsView(APIView):
    """Record something a competitor sells, and what it cost on the day."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.PRODUCTS)
        competitor = get_object_or_404(Competitor, pk=pk, store=store)

        serializer = CompetitorProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # A price with no date is a claim. Stamp it now rather than leaving the
        # field empty and letting a month-old number look current.
        from django.utils import timezone

        manual = serializer.validated_data.get("matches") is not None
        row = serializer.save(
            competitor=competitor,
            observed_at=serializer.validated_data.get("observed_at") or timezone.now(),
            raw={"matches_manual": True} if manual else {},
        )
        # Recording what a competitor sells IS the analysis of that competitor.
        # Without this the row stayed "never analysed" for ever and `is_stale`
        # flagged every competitor, however fresh its prices were.
        competitor.analysed_at = row.observed_at or timezone.now()
        competitor.save(update_fields=["analysed_at", "updated_at"])
        # «رقیب کالایی» for the new row too — heuristic only, it is instant.
        competitor_research.match_competitor(competitor)
        row.refresh_from_db()
        return Response(
            CompetitorProductSerializer(row).data, status=status.HTTP_201_CREATED
        )


class CompetitorProductDetailView(APIView):
    """The owner confirms or rejects a match by hand: ``{"matches": id|null}``.

    A hand-set match is final — later automatic runs never overwrite it.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk, product_pk):
        from apps.products.models import Product

        store = access.get_store(request.user, store_id, access.PRODUCTS)
        row = get_object_or_404(
            CompetitorProduct, pk=product_pk, competitor_id=pk, competitor__store=store,
        )
        if "matches" not in request.data:
            return Response(
                {"error": {"code": "bad_request", "message": "فیلدِ matches لازم است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target = request.data.get("matches")
        if target in (None, "", 0):
            row.matches = None
        else:
            row.matches = get_object_or_404(Product, pk=target, store=store)
        raw = dict(row.raw or {})
        raw["matches_manual"] = True
        row.raw = raw
        row.save(update_fields=["matches", "raw", "updated_at"])
        return Response(CompetitorProductSerializer(row).data)


class CompetitorCrawlView(APIView):
    """Start (POST) or read (GET) the crawl of this competitor's own site."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.PRODUCTS, write=False)
        competitor = get_object_or_404(Competitor, pk=pk, store=store)
        return Response({"crawl": _latest_crawl(competitor)})

    def post(self, request, store_id, pk):
        from apps.jobs.models import Job
        from apps.jobs.services import dispatch_job
        from services.research import shop_crawler

        from .competitor_tasks import JOB_KIND, crawl_competitor_task

        store = access.get_store(request.user, store_id, access.PRODUCTS)
        competitor = get_object_or_404(Competitor, pk=pk, store=store)
        try:
            shop_crawler.normalise_site(competitor.website)
        except ValueError as exc:
            return Response(
                {"error": {"code": "no_website", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if competitor_research.is_marketplace_url(competitor.website):
            return Response(
                {"error": {
                    "code": "marketplace",
                    "message": (
                        "این نشانیِ یک غرفه در بازار (دیجی‌کالا/باسلام/…) است، نه سایتِ خودشان. "
                        "کالاهایش هنگامِ افزودن از جست‌وجوی همان بازار ثبت شد؛ برای تازه کردن، "
                        "«یافتنِ خودکارِ رقبا» را دوباره بزنید."
                    ),
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )
        running = _latest_crawl(competitor)
        if running and running["state"] in (Job.State.QUEUED, Job.State.RUNNING, Job.State.PROCESSING):
            return Response({"crawl": running}, status=status.HTTP_200_OK)
        try:
            max_pages = int(request.data.get("max_pages", shop_crawler.DEFAULT_MAX_PAGES))
        except (TypeError, ValueError):
            max_pages = shop_crawler.DEFAULT_MAX_PAGES
        max_pages = max(1, min(max_pages, shop_crawler.HARD_MAX_PAGES))
        job = Job.objects.create(
            store=store, type=Job.Type.MARKET_ANALYSIS,
            context={"kind": JOB_KIND, "competitor_id": competitor.pk, "max_pages": max_pages},
            current_step_label="در صف",
        )
        failed = dispatch_job(job, crawl_competitor_task, job.id, competitor.pk, max_pages)
        if failed is not None:
            return failed
        return Response({"crawl": _latest_crawl(competitor)}, status=status.HTTP_202_ACCEPTED)


class CompetitorMatchView(APIView):
    """Re-run «رقیب کالایی» for one competitor (after adding products, say)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.PRODUCTS)
        competitor = get_object_or_404(Competitor, pk=pk, store=store)
        verdict = competitor_research.match_competitor(
            competitor, use_llm=bool(request.data.get("use_llm")),
        )
        competitor.refresh_from_db()
        return Response({
            "verdict": verdict,
            "competitor": CompetitorSerializer(competitor).data,
        })


class CompetitorDiscoverView(APIView):
    """Suggest competitors from marketplace sellers of the shop's products.

    Nothing is saved here — the owner adds a suggestion with
    ``POST .../discover/add/``.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.PRODUCTS, write=False)
        return Response(competitor_research.discover(store))


class CompetitorDiscoverAddView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.PRODUCTS)
        suggestion = request.data.get("suggestion") or request.data
        try:
            competitor = competitor_research.add_suggestion(store, suggestion)
        except ValueError as exc:
            return Response(
                {"error": {"code": "bad_suggestion", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(CompetitorSerializer(competitor).data, status=status.HTTP_201_CREATED)


class ProfitReportView(APIView):
    """Revenue and **real** profit, plus what is missing to compute it."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.ANALYTICS, write=False)
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        return Response(opportunities.profit_report(store, days))


class OpportunityListView(APIView):
    """What the shop should do next."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.ANALYTICS, write=False)
        state = request.query_params.get("state", Opportunity.State.OPEN)
        rows = store.opportunities.all()
        if state != "all":
            rows = rows.filter(state=state)
        return Response(OpportunitySerializer(rows.select_related("product"), many=True).data)

    def post(self, request, store_id):
        """Recompute. Dismissed suggestions are never resurrected."""
        store = access.get_store(request.user, store_id, access.ANALYTICS)
        try:
            days = int(request.data.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        # Marketplace search («کجا بفروشم») is opt-in per call: it costs a few
        # outside HTTP requests per product. The panel's «بازمحاسبه» asks for it.
        summary = opportunities.refresh(
            store, days, check_channels_now=bool(request.data.get("check_channels")),
        )
        rows = store.opportunities.filter(state=Opportunity.State.OPEN)
        return Response({
            "summary": summary,
            "readiness": opportunities.readiness(store, days),
            "opportunities": OpportunitySerializer(
                rows.select_related("product"), many=True
            ).data,
        })


class OpportunityReadinessView(APIView):
    """«چه چیزی لازم است»: missing data, how to fix it, what it unlocks."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.ANALYTICS, write=False)
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        return Response(opportunities.readiness(store, days))


class OpportunityDetailView(APIView):
    """Mark one done or dismissed."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.ANALYTICS)
        row = get_object_or_404(Opportunity, pk=pk, store=store)

        state = request.data.get("state")
        if state not in Opportunity.State.values:
            return Response(
                {"error": {"code": "bad_state", "message": "وضعیت نامعتبر است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row.state = state
        row.save(update_fields=["state", "updated_at"])
        return Response(OpportunitySerializer(row).data)

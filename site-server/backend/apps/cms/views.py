"""What the public site reads. Read-only, unauthenticated, cached-friendly.

The site is a separate Next.js process, so this is the seam between them. Two
properties it has to hold:

**A draft is invisible, and so is a scheduled article until its moment.** The
filter lives here, once, rather than in the site — a front-end that forgets it
publishes next week's article today, and nobody finds out until a customer
mentions it.

**Nothing here needs a login.** It is the public blog. Requiring auth would mean
the site holding a credential it has no other use for, which is a credential
that leaks.
"""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Article,
    CaseStudy,
    Category,
    CustomerLogo,
    FaqItem,
    Redirect,
    Resource,
    SeoPage,
    ShowcaseItem,
    SiteSettings,
    Testimonial,
)
from apps.common.utils import with_tag


def live():
    """The one definition of "published", in one place."""
    return Article.objects.filter(
        status=Article.Status.PUBLISHED, published_at__lte=timezone.now(),
    ).select_related("category")


class ArticleListSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    tags = serializers.ListField(source="clean_tags", read_only=True)
    readingMinutes = serializers.IntegerField(source="reading_minutes", read_only=True)
    date = serializers.CharField(source="display_date", read_only=True)
    cover = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "slug", "title", "description", "author", "category",
            "category_slug", "tags", "readingMinutes", "date", "cover",
            "published_at",
        ]

    def get_cover(self, obj) -> str | None:
        return obj.cover.url if obj.cover else None


class ArticleDetailSerializer(ArticleListSerializer):
    class Meta(ArticleListSerializer.Meta):
        fields = ArticleListSerializer.Meta.fields + ["body"]


class ArticleList(ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ArticleListSerializer
    pagination_class = None

    def get_queryset(self):
        rows = live()
        category = self.request.query_params.get("category")
        if category:
            rows = rows.filter(category__slug=category)
        tag = self.request.query_params.get("tag")
        if tag:
            rows = with_tag(rows, tag)
        return rows


class ArticleDetail(RetrieveAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ArticleDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return live()


class CategoryList(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        rows = Category.objects.all()
        return Response([
            {
                "name": c.name,
                "slug": c.slug,
                "description": c.description,
                # Counted from live articles only. A category page listing three
                # articles under a heading that says five is a page that looks
                # broken.
                "count": c.live_count,
            }
            for c in rows
            if c.live_count
        ])


class RedirectList(APIView):
    """Old paths the site should still honour.

    Read at build time. Without these, changing a slug 404s every link anyone
    ever shared — including the ones Google indexed, which is the traffic the
    article was written for.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response([
            {"from": r.old_path, "to": r.new_path}
            for r in Redirect.objects.all()[:500]
        ])


# ---------------------------------------------------------------------------
#  Site content. Same three properties as the blog endpoints above: read-only,
#  unauthenticated, and the one place the filtering lives.
# ---------------------------------------------------------------------------


def _abs(request, filefield) -> str | None:
    """An absolute URL, because the site is a different origin.

    A relative `/media/...` resolves against the Next.js host, where nothing is
    served — so the poster renders as a broken image and the video as a dead
    player, on a page whose whole job is showing that the output is real.
    """
    if not filefield:
        return None
    return request.build_absolute_uri(filefield.url)


class SiteSettingsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        row = SiteSettings.load()
        return Response({
            "name": row.name,
            "nameEn": row.name_en,
            "tagline": row.tagline,
            "taglineEn": row.tagline_en,
            "oneLiner": row.one_liner,
            "oneLinerEn": row.one_liner_en,
            "email": row.email,
            "phone": row.phone,
            "instagram": row.instagram,
            "telegram": row.telegram,
            "address": row.address,
            "keywords": SiteSettings.split(row.keywords),
            "keywordsEn": SiteSettings.split(row.keywords_en),
        })


class ShowcaseList(APIView):
    """The real outputs, one video each.

    The video is whatever is on the row. If the segments were stitched, that is
    the stitched file; if somebody uploaded a finished video, that is theirs.
    Either way the site gets one URL and renders one player, because five tiles
    playing at once is a picture of how we render, not of what we make.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        rows = ShowcaseItem.objects.filter(published=True).prefetch_related("segments")
        return Response([
            {
                "id": item.slug,
                "category": item.category,
                "categoryEn": item.category_en or item.category,
                "product": item.product,
                "productEn": item.product_en or item.product,
                "image": _abs(request, item.image),
                "video": _abs(request, item.video),
                "videoPoster": _abs(request, item.video_poster) or _abs(request, item.image),
                "caption": item.caption,
                "captionEn": item.caption_en or item.caption,
                "featured": item.featured,
                # Only so the page can say "stitched from five five-second
                # shots" — it is a fact about the work, and it is the part
                # people do not believe.
                "segmentCount": item.segments.count(),
            }
            for item in rows
        ])


class FaqList(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        rows = FaqItem.objects.filter(published=True)
        if request.query_params.get("home") in ("1", "true"):
            rows = rows.filter(on_home=True)
        return Response([
            {
                "group": item.group,
                "groupLabel": item.get_group_display(),
                "q": item.question,
                "a": item.answer,
                "qEn": item.question_en or item.question,
                "aEn": item.answer_en or item.answer,
                "onHome": item.on_home,
            }
            for item in rows
        ])


class SeoPageList(APIView):
    """Marketing pages written in the admin.

    The site merges these over the ones in its own repo, by slug. So a row here
    either **replaces** a shipped page — a sentence fixed without a deploy — or
    **adds** one that never existed, which is the whole point of §2's «۱۰۰ تا
    ۵۰۰+ صفحه».

    Bullets come back grouped, because the page renders them in named sections
    and regrouping them in the front-end means the grouping lives in two files.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        rows = SeoPage.objects.filter(published=True).prefetch_related(
            "bullets", "steps", "rows",
        )
        kind = request.query_params.get("kind")
        if kind:
            rows = rows.filter(kind=kind.upper())
        locale = request.query_params.get("locale")
        if locale:
            rows = rows.filter(locale=locale)

        return Response([self._page(page) for page in rows])

    def _page(self, page) -> dict:
        bullets: dict[str, list[str]] = {}
        for bullet in page.bullets.all():
            bullets.setdefault(bullet.group, []).append(bullet.text)

        return {
            "kind": page.kind,
            "slug": page.slug,
            "locale": page.locale,
            "icon": page.icon,
            "title": page.title,
            "lead": page.lead,
            # Falls back to the lead rather than coming back empty: a page with
            # no meta description is a page Google writes its own snippet for.
            "metaDescription": page.meta_description or page.lead,
            "intro": page.intro,
            "problem": page.problem,
            "benefit": page.benefit,
            "verdict": page.verdict,
            "effort": page.effort,
            "example": (
                {"before": page.example_before, "after": page.example_after}
                if page.example_before or page.example_after
                else None
            ),
            "bullets": bullets,
            "steps": [
                {"title": s.title, "desc": s.description, "soon": s.soon}
                for s in page.steps.all()
            ],
            "rows": [
                {"aspect": r.aspect, "us": r.us, "them": r.them}
                for r in page.rows.all()
            ],
        }


class ProofView(APIView):
    """Case studies, customers and testimonials — §11, §12, §13.

    One endpoint for three pages because the three are one subject: proof that
    somebody else already did this. The site asks once and renders three pages
    from it rather than making three round trips for a handful of rows.

    **Consent is enforced here, not in the site.** A logo or a quote is a
    public claim about somebody else's business; a front-end that forgets the
    filter publishes it anyway, and nobody finds out until the customer does.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        cases = (
            CaseStudy.objects.filter(published=True)
            .select_related("customer")
            .prefetch_related("testimonials")
        )
        return Response({
            "caseStudies": [self._case(request, c) for c in cases],
            "customers": [
                {
                    "slug": c.slug,
                    "name": c.name,
                    "description": c.description,
                    "logo": _abs(request, c.logo),
                    "website": c.website,
                    "industry": c.industry,
                    # Only when there is a published study to link to.
                    "caseStudy": next(
                        (s.slug for s in c.case_studies.all() if s.published), None,
                    ),
                }
                for c in CustomerLogo.objects.filter(consented=True)
                .prefetch_related("case_studies")
            ],
            "testimonials": [
                self._quote(request, t)
                for t in Testimonial.objects.filter(consented=True)
                .select_related("case_study")
            ],
        })

    def _case(self, request, case) -> dict:
        return {
            "slug": case.slug,
            "title": case.title,
            "lead": case.lead,
            "cover": _abs(request, case.cover),
            "customer": case.who,
            "problem": case.problem,
            "before": case.before,
            "solution": case.solution,
            "process": case.process,
            "outputs": case.outputs,
            "results": case.results,
            "conclusion": case.conclusion,
            "testimonials": [
                self._quote(request, t)
                for t in case.testimonials.all()
                if t.consented
            ],
        }

    def _quote(self, request, row) -> dict:
        return {
            "quote": row.quote,
            "name": row.name,
            "business": row.business,
            "role": row.role,
            "photo": _abs(request, row.photo),
            "outcome": row.outcome,
            "caseStudy": row.case_study.slug if row.case_study else None,
        }


class ResourceList(APIView):
    """Guides, templates, checklists and e-books — §19."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        rows = Resource.objects.filter(published=True)
        kind = request.query_params.get("kind")
        if kind:
            rows = rows.filter(kind=kind)
        return Response({
            "resources": [
                {
                    "slug": r.slug,
                    "kind": r.kind,
                    "kindLabel": r.get_kind_display(),
                    "title": r.title,
                    "description": r.description,
                    "icon": r.icon,
                    "file": _abs(request, r.file),
                    "body": r.body,
                }
                for r in rows
            ],
            "kinds": [
                {"value": v, "label": label} for v, label in Resource.Kind.choices
            ],
        })

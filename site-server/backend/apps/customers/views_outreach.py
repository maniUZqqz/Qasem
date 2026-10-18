"""The outbound sales list (`ایده‌ها پنل.md` صفحه ۷).

The response leads with what is **due**, not with everything. A list sorted by
"whatever was added last" is a list nobody opens twice; a list that opens on
«این سه تا را امروز باید زنگ بزنی» is a tool.

It also states, in the payload, what this page deliberately does not do, and
what it has since gained. Both matter: a reader of the spec looks for phone
lookup and call recording, and silence about either reads as unfinished rather
than as a decision. Saying it here means the panel and the spec cannot drift.
"""
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from .outreach import Prospect, counts, due

#: Named here rather than in the front-end so the panel cannot claim something
#: the product does not do, and cannot forget to mention something it will.
#:
#: Call recording used to be on this list. It came off by building the thing
#: that was actually missing — a consent record — rather than by deciding the
#: constraint did not matter. What is left is one item, and it is not a consent
#: problem a form solves.
HELD = [
    {
        "title": "پیدا کردن شبکه‌های اجتماعی از روی شماره",
        "why": (
            "این یعنی از روی شماره‌ی آدم‌هایی که با شما کاری نداشته‌اند، "
            "حسابشان را پیدا کردن — همان کاری که برای آزار آدم‌ها استفاده "
            "می‌شود، و فقط با سوءاستفاده از API پلتفرم‌ها ممکن است. "
            "ساخته نشده و کلیدی هم برای روشن کردنش نیست. "
            "آنچه واقعاً لازم دارید — «این شماره را از قبل می‌شناسیم؟» — "
            "از روی داده‌های خودِ فروشگاه جواب داده می‌شود."
        ),
    },
]

#: What *was* held and now is not. Shown next to `HELD`, because a shop that
#: read the old page has a wrong idea of what this can do.
BUILT_SINCE = [
    {
        "title": "ضبط و تحلیل تماس",
        "note": (
            "ساخته شد — با یک شرط: تا رضایت طرف مقابل ثبت نشود، هیچ فایلی "
            "ذخیره نمی‌شود. پیاده‌سازی متن روی سرور خودمان انجام می‌شود."
        ),
    },
    {
        "title": "آماده‌سازی قبل از تماس",
        "note": (
            "چه گفت، به چه چیزی اعتراض داشت، چه قولی داده شد — قبل از "
            "شماره گرفتن جلوی چشمتان است."
        ),
    },
]


class ProspectSerializer(serializers.ModelSerializer):
    is_due = serializers.BooleanField(read_only=True)
    is_closed = serializers.BooleanField(read_only=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = Prospect
        exclude = ["store"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_company(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("اسم کسب‌وکار لازم است.")
        return value


class ProspectListView(APIView):
    """Everything on the list, with the overdue rows called out."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)
        rows = Prospect.objects.filter(store=store)

        stage = request.query_params.get("stage")
        if stage:
            rows = rows.filter(stage=stage)
        if request.query_params.get("due") in ("1", "true"):
            rows = due(store)

        return Response({
            "prospects": ProspectSerializer(rows[:500], many=True).data,
            "due": ProspectSerializer(due(store)[:50], many=True).data,
            "counts": counts(store),
            "stages": [
                {"value": v, "label": label} for v, label in Prospect.Stage.choices
            ],
            "held": HELD,
            "built_since": BUILT_SINCE,
        })

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        serializer = ProspectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(store=store)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProspectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        row = get_object_or_404(Prospect, pk=pk, store=store)
        serializer = ProspectSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        get_object_or_404(Prospect, pk=pk, store=store).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

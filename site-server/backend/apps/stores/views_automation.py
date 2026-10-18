"""The content page's settings, read and written.

The response carries more than the row: the choices with their Persian labels,
the weekday order the panel should show, the store's products, and a sentence
saying what the current settings actually do. All of it is derivable, and
deriving it in the front-end is how a label and its value drift apart.
"""
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access
from .content_automation import (
    MAX_SECONDS,
    MIN_SECONDS,
    SEGMENT_SECONDS,
    WEEKDAYS,
    ContentAutomation,
    automation_for,
)


class ContentAutomationSerializer(serializers.ModelSerializer):
    segment_count = serializers.IntegerField(read_only=True)
    is_scheduled = serializers.BooleanField(read_only=True)
    summary = serializers.CharField(read_only=True)
    next_run = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ContentAutomation
        exclude = ["id", "store"]
        read_only_fields = ["last_run_at", "created_at", "updated_at"]

    def validate(self, attrs):
        # Runs the model's own `clean`, so the seconds-must-be-a-multiple-of-5
        # rule is stated once and enforced everywhere — admin, API and shell.
        row = ContentAutomation(**{**self._current(), **attrs})
        row.clean()
        return attrs

    def _current(self) -> dict:
        if not self.instance:
            return {}
        fields = {f.name for f in ContentAutomation._meta.fields}
        return {
            name: getattr(self.instance, name)
            for name in fields
            if name not in {"id", "store", "created_at", "updated_at"}
        }


def _choices(field) -> list[dict]:
    return [{"value": v, "label": label} for v, label in field]


class StoreContentAutomationView(APIView):
    """`GET`/`PATCH` one store's standing content instructions."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        # CONTENT, not SETTINGS: a content manager is exactly the person whose
        # job this page is, and making them ask the owner to change a posting
        # day is how the setting stops being used.
        store = access.get_store(request.user, pk, access.CONTENT, write=False)
        row = automation_for(store)
        return Response({
            "settings": ContentAutomationSerializer(row).data,
            "weekdays": [{"value": v, "label": label} for v, label in WEEKDAYS],
            "approvals": _choices(ContentAutomation.Approval.choices),
            "image_modes": _choices(ContentAutomation.ImageMode.choices),
            "modes": _choices(ContentAutomation.Mode.choices),
            "video": {
                "step": SEGMENT_SECONDS,
                "min": MIN_SECONDS,
                "max": MAX_SECONDS,
                # Said out loud because it is the thing people ask about the
                # video pipeline, and the thing the showcase page proves.
                "note": (
                    f"رندر {SEGMENT_SECONDS} ثانیه‌ای است و قطعه‌ها به هم "
                    "چسبانده می‌شوند — فریم آخر هر قطعه، فریم اول بعدی."
                ),
            },
            "products": [
                {"id": p.id, "name": p.name}
                for p in store.products.order_by("-created_at")[:200]
            ],
        })

    def patch(self, request, pk):
        store = access.get_store(request.user, pk, access.CONTENT)
        row = automation_for(store)
        serializer = ContentAutomationSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

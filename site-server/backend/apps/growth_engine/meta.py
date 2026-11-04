"""GET /growth/meta/ - the vocabulary and limits the front end needs, from one source of truth."""
from rest_framework.response import Response
from rest_framework.views import APIView

from .core import conf
from .core.permissions import IsGrowthStaff
from .discovery.services import csv_mapping
from .leads.serializers import choices_payload


class MetaView(APIView):
    permission_classes = [IsGrowthStaff]

    def get(self, request):
        return Response(
            {
                **choices_payload(),
                "csv": {
                    "max_bytes": conf.get("CSV_MAX_BYTES"),
                    "max_rows": conf.get("CSV_MAX_ROWS"),
                    "targets": csv_mapping.TARGETS,
                    "default_country": conf.get("DEFAULT_COUNTRY"),
                },
                "limits": {"bulk_max_ids": conf.get("BULK_MAX_IDS"), "export_max_rows": conf.get("EXPORT_MAX_ROWS")},
            }
        )

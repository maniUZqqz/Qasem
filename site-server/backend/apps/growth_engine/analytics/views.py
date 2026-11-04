from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.core.permissions import IsGrowthStaff

from . import services


class DashboardView(APIView):
    """GET /growth/dashboard/ - real counts only."""

    permission_classes = [IsGrowthStaff]

    def get(self, request):
        return Response(services.build_dashboard())

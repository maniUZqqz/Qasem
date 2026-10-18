"""Which model is serving what, and what the analysis engine produces.

This is the endpoint behind the panel's «موتور هوش مصنوعی» card: it answers
"is my content being made on your GPU or bought from an API, and with which
model" without exposing keys.
"""
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from services.ai import providers


class AIStatusView(APIView):
    """Read-only view of the active provider per capability. No secrets."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = providers.summary()
        return Response({
            "capabilities": rows,
            "all_local": all(r["local"] for r in rows if r["local"] is not None),
            "any_external": any(r["local"] is False for r in rows),
        })


class AIProviderHealthView(APIView):
    """Probe every configured provider. Admin only — it makes real calls."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        from django.utils import timezone

        from services.ai import factory

        from .models import ModelProvider

        results = []
        for row in ModelProvider.objects.filter(is_active=True):
            resolved = providers._from_row(row)
            ok, detail = factory.health(resolved)
            row.is_healthy, row.last_error = ok, "" if ok else detail
            row.checked_at = timezone.now()
            row.save(update_fields=["is_healthy", "last_error", "checked_at"])
            results.append({
                "id": row.pk, "name": row.name, "capability": row.capability,
                "healthy": ok, "detail": detail,
            })
        return Response({"checked": len(results), "results": results})

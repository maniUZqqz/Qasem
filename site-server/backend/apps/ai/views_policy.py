"""The store owner's own view of where their data goes, and their say in it.

A privacy setting the customer cannot read or change is not a privacy setting.
This endpoint answers three questions for one store: which mode is in force,
what will actually serve each capability under it, and what is blocked as a
result — the last one matters most, because a shop that switches to
`Local Only` and then finds video narration silently missing deserves to have
been told why beforehand.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store
from services.ai import gateway

from .models import StoreAIPolicy
from apps.stores import access


def _payload(store) -> dict:
    policy = gateway.policy_for(store)
    capabilities = gateway.explain(store)
    # Who would narrate this shop's videos under this policy. With the offline
    # Piper voice installed, «فقط لوکال» narrates on this machine; without it,
    # the owner has to see that here rather than discover it when a video
    # comes back silent.
    from services.audio.tts import get_tts_provider, TTSError

    try:
        speaker = get_tts_provider(language="fa", store=store).describe()
        narration = {
            "available": True, "reason": None,
            "engine": speaker.get("processor"), "local": speaker.get("local"),
        }
    except TTSError as exc:
        narration = {"available": False, "reason": str(exc)}

    return {
        "mode": policy.mode,
        "mode_label": policy.label,
        "allow_customer_data_external": policy.allow_customer_data_external,
        "is_platform_default": policy.is_default,
        "modes": [
            {"value": value, "label": label}
            for value, label in StoreAIPolicy.Mode.choices
        ],
        "capabilities": capabilities,
        "narration": narration,
        "any_external": any(c["local"] is False for c in capabilities),
        "blocked": [c for c in capabilities if c["blocked"]],
    }


class StoreAIPolicyView(APIView):
    """GET the effective policy, PATCH to change it."""

    permission_classes = [IsAuthenticated]

    def _store(self, request, store_id):
        return access.get_store(request.user, store_id, access.SETTINGS)

    def get(self, request, store_id):
        return Response(_payload(self._store(request, store_id)))

    def patch(self, request, store_id):
        store = self._store(request, store_id)
        row, _ = StoreAIPolicy.objects.get_or_create(store=store)

        mode = request.data.get("mode")
        if mode is not None:
            if mode not in StoreAIPolicy.Mode.values:
                return Response(
                    {"error": {"code": "invalid_mode", "message": "حالت نامعتبر است."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            row.mode = mode

        allow = request.data.get("allow_customer_data_external")
        if allow is not None:
            row.allow_customer_data_external = bool(allow)

        # Changing the policy is the consent. Recording who and when is the
        # only thing that makes it worth anything in a later dispute.
        row.acknowledged_at = timezone.now()
        row.acknowledged_by = request.user
        row.save()

        store.refresh_from_db()
        return Response(_payload(store))

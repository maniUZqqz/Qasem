import logging

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Store
from .serializers import StoreProfileSerializer, StoreSerializer
from . import access

logger = logging.getLogger(__name__)


class StoreViewSet(viewsets.ModelViewSet):
    """Stores of the authenticated user only — tenancy enforced server-side."""

    serializer_class = StoreSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return access.stores_for(self.request.user)

    # Membership is what get_queryset enforces; WHAT a member may do is the
    # role's business. Before these, any member — a «بازدیدکننده» included —
    # could rename the store through PATCH and delete it through DELETE.

    def update(self, request, *args, **kwargs):
        store = self.get_object()
        access.get_store(request.user, store.pk, access.SETTINGS)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        store = self.get_object()
        if access.role_of(request.user, store) != access.Role.OWNER:
            raise access.NoAccess("فقط مالک فروشگاه می‌تواند آن را حذف کند.")
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        store = serializer.save(owner=self.request.user)
        self._record_where_they_came_from(store)

    def _record_where_they_came_from(self, store) -> None:
        """Attribution, written once, at the only moment it can be known.

        A store is the first thing that exists per customer, so this is where
        phase 26 gets its answer to «این مشتری از کجا آمد». Reconstructing it
        later is impossible — the referrer header and the code they typed are
        gone by the second request.

        Never fails the creation. A shop that could not create their store
        because an analytics row would not save is a far worse outcome than an
        attribution we cannot report on.
        """
        from apps.marketing.gtm import record_signup

        data = self.request.data
        try:
            record_signup(
                store,
                code=str(data.get("code", "") or data.get("referral_code", "")),
                utm=data.get("utm") if isinstance(data.get("utm"), dict) else {},
                landing_path=str(data.get("landing_path", "")),
                referrer=str(
                    data.get("referrer")
                    or self.request.META.get("HTTP_REFERER", "")
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record attribution for store %s: %s", store.pk, exc)

    @action(detail=True, methods=["get", "put", "patch"], url_path="profile")
    def profile(self, request, pk=None):
        store = self.get_object()
        if request.method == "GET":
            # Every member reads it: the brand voice feeds every page they
            # work on. The credentials are not in it (see the serializer).
            return Response(StoreProfileSerializer(store.profile).data)
        # Changing it is a settings change: owner and admin.
        access.get_store(request.user, store.pk, access.SETTINGS)
        serializer = StoreProfileSerializer(
            store.profile, data=request.data, partial=(request.method == "PATCH")
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

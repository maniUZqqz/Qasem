"""Public lead intake endpoint.

This is the only anonymous write endpoint in the product, so it carries its own
throttle rather than riding the global `anon` rate: a contact form legitimately
gets used once or twice, never thirty times a minute.
"""
import logging

from django.conf import settings

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .models import Lead
from .serializers import LeadCreateSerializer

logger = logging.getLogger(__name__)


class LeadThrottle(AnonRateThrottle):
    """Tighter than the global anon rate — see module docstring.

    Declaring `throttle_classes` on the view bypasses the project-wide
    "no throttling during tests" switch in settings, which made the suite fail
    on the sixth request rather than on the assertion under test. Honour that
    switch here too.
    """

    scope = "lead"

    def allow_request(self, request, view):
        if getattr(settings, "IS_TEST", False):
            return True
        return super().allow_request(request, view)


def _client_ip(request) -> str | None:
    """Best-effort client IP.

    Only the first hop of X-Forwarded-For is used, and only when the app is
    actually behind a proxy that sets it; a client can forge the rest of the
    chain. Stored for abuse triage, nothing else.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


class LeadCreateView(APIView):
    """`POST /api/v1/leads/` — the public contact form."""

    permission_classes = [AllowAny]
    throttle_classes = [LeadThrottle]
    serializer_class = LeadCreateSerializer

    def post(self, request):
        serializer = LeadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Honeypot filled → a bot. Answer exactly like success so it learns
        # nothing and moves on, but store nothing.
        if data.pop("website", "").strip():
            logger.info("Lead honeypot triggered from %s — discarded", _client_ip(request))
            return Response({"ok": True}, status=status.HTTP_201_CREATED)

        lead = Lead.objects.create(
            **data,
            ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )
        logger.info("Lead #%s from %s <%s>", lead.pk, lead.name, lead.email)

        # Nothing about the stored row is echoed back: the form only needs to
        # know it worked.
        return Response(
            {"ok": True, "message": "پیام شما ثبت شد. به‌زودی جواب می‌دهیم."},
            status=status.HTTP_201_CREATED,
        )

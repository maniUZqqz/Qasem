"""Registration, identity, and getting back in after a forgotten password."""
import logging

from django.conf import settings
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import password_reset
from .serializers import RegisterSerializer, UserSerializer

logger = logging.getLogger(__name__)


class PasswordResetThrottle(AnonRateThrottle):
    """Tight, because each request sends a real email to someone who did not
    necessarily ask for it — an unthrottled endpoint is a way to fill a shop
    owner's inbox from the outside.

    Declaring `throttle_classes` on a view bypasses the project-wide "no
    throttling during tests" switch, which makes the suite fail on the sixth
    request instead of on the assertion under test. Honour that switch here
    too, the same way `apps.marketing.views.LeadThrottle` does.
    """

    scope = "password_reset"

    def allow_request(self, request, view):
        if getattr(settings, "IS_TEST", False):
            return True
        return super().allow_request(request, view)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class PasswordResetRequestView(APIView):
    """POST an email; a reset link goes out if an account matches.

    The reply is identical whether or not one does — see
    `apps.accounts.password_reset` for why.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        email = request.data.get("email", "")
        try:
            result = password_reset.request_reset(email)
        except Exception as exc:  # noqa: BLE001 — mail server refused or timed out
            # Told plainly. "We sent you a link" when nothing was sent leaves
            # the customer waiting instead of asking for help.
            logger.exception("Could not send a password reset email")
            return Response(
                {"error": {
                    "code": "email_failed",
                    "message": "ارسال ایمیل ممکن نشد. چند دقیقه بعد دوباره تلاش کنید "
                               "یا با پشتیبانی تماس بگیرید.",
                }},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"detail": result["detail"]})


class PasswordResetCheckView(APIView):
    """GET with uid+token — is this link still usable?

    Lets the page say "this link expired" on load instead of after the user has
    typed a new password twice.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            user = password_reset.check_token(
                request.query_params.get("uid", ""),
                request.query_params.get("token", ""),
            )
        except password_reset.ResetFailed as exc:
            return Response(
                {"valid": False, "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"valid": True, "username": user.username})


class PasswordResetConfirmView(APIView):
    """POST uid+token+password — set the new password."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        try:
            password_reset.confirm_reset(
                request.data.get("uid", ""),
                request.data.get("token", ""),
                request.data.get("password", ""),
            )
        except password_reset.ResetFailed as exc:
            return Response(
                {"error": {"code": "reset_failed", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # No tokens handed back on purpose: a leaked link should mean a password
        # change the owner can notice, not a silent session for whoever had it.
        return Response({"detail": "رمز جدید ثبت شد. حالا با آن وارد شوید."})


class SessionLoginView(APIView):
    """پلِ ورود: پنلِ React با JWT وارد شده؛ ابزارهای کارکنان (سایت‌ساز، سه‌بعدی، سرورهای
    پردازش، ادمین) صفحه‌های جنگو هستند و سشن می‌خواهند. یک فرمِ ساده همان JWT را POST می‌کند،
    سشن ساخته می‌شود و مرورگر به `next` می‌رود. هیچ دسترسیِ تازه‌ای نمی‌دهد: همان کاربر، همان حقوق."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        from django.contrib.auth import login
        from django.http import HttpResponseRedirect
        from django.utils.http import url_has_allowed_host_and_scheme
        from rest_framework_simplejwt.authentication import JWTAuthentication
        from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError

        raw = request.data.get("token") or ""
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not raw and header.startswith("Bearer "):
            raw = header[7:]
        auth = JWTAuthentication()
        try:
            user = auth.get_user(auth.get_validated_token(raw))
        except (AuthenticationFailed, InvalidToken, TokenError):
            return Response({"detail": "توکن نامعتبر است؛ دوباره وارد شوید."}, status=status.HTTP_401_UNAUTHORIZED)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        nxt = request.data.get("next") or request.query_params.get("next") or "/"
        if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
            nxt = "/"
        return HttpResponseRedirect(nxt)

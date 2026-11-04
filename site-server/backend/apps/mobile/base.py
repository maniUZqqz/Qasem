"""Auth, permissions, throttles and the error format of the mobile API.

Every error is `{"error": {"code": "...", "message": "<Persian>"}}`. The phone shows `message` as is.
"""
from __future__ import annotations

from django.conf import settings as dj_settings
from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import MobileActionLog, MobileDevice, hash_token


class MobileError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, headers: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.headers = code, message, status, headers or {}


def client_ip(request) -> str | None:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = (fwd.split(",")[0].strip() if fwd else "") or request.META.get("REMOTE_ADDR") or ""
    return ip or None


class DeviceAuthentication(authentication.BaseAuthentication):
    """`Authorization: Device <token>` -> (user, device). Revoked/unknown tokens answer 401 `device_revoked`."""

    keyword = "Device"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Device "):
            return None
        raw = header.split(" ", 1)[1].strip()
        device = MobileDevice.objects.select_related("user").filter(token_hash=hash_token(raw)).first()
        if device is None or device.revoked_at is not None:
            raise exceptions.AuthenticationFailed("این گوشی دیگر مجاز نیست؛ دوباره وصل شوید.", code="device_revoked")
        user = device.user
        if not (user.is_active and user.is_staff):
            raise exceptions.PermissionDenied("این حساب دیگر کارمند نیست.", code="not_staff")
        now = timezone.now()
        if not device.last_seen_at or (now - device.last_seen_at).total_seconds() > 20:
            device.last_seen_at = now
            device.last_ip = client_ip(request)
            device.save(update_fields=["last_seen_at", "last_ip"])
        return (user, device)

    def authenticate_header(self, request):
        return "Device"


class IsDeviceOrStaff(BasePermission):
    """A paired device of an active staff user, or a staff user with a panel login."""

    message = "فقط برای کارمندان."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            raise exceptions.NotAuthenticated("برای ادامه وارد شوید.")
        if not (user.is_active and user.is_staff):
            raise exceptions.PermissionDenied("فقط برای کارمندان.", code="not_staff")
        return True


class IsDevice(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            raise exceptions.NotAuthenticated("برای ادامه وارد شوید.")
        if not isinstance(request.auth, MobileDevice):
            raise exceptions.PermissionDenied("این درخواست فقط از گوشیِ جفت‌شده انجام می‌شود.", code="device_only")
        return IsDeviceOrStaff().has_permission(request, view)


class _FixedRateThrottle(SimpleRateThrottle):
    rate_text = "60/min"

    def get_rate(self):
        return self.rate_text

    def allow_request(self, request, view):
        if getattr(dj_settings, "IS_TEST", False) and not getattr(dj_settings, "MOBILE_TEST_THROTTLE", False):
            return True
        return super().allow_request(request, view)


class DeviceThrottle(_FixedRateThrottle):
    scope = "mobile_device"
    rate_text = "300/min"

    def get_cache_key(self, request, view):
        ident = str(request.auth.uid) if isinstance(request.auth, MobileDevice) else (str(request.user.pk) if request.user and request.user.is_authenticated else None)
        return self.cache_format % {"scope": self.scope, "ident": ident} if ident else None


class PairThrottle(_FixedRateThrottle):
    scope = "mobile_pair"
    rate_text = "10/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": client_ip(request) or "?"}


class MobileAPIView(APIView):
    """Device token or staff login (panel). Errors in the mobile format."""

    authentication_classes = [DeviceAuthentication, JWTAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsDeviceOrStaff]
    throttle_classes = [DeviceThrottle]

    @property
    def device(self) -> MobileDevice | None:
        auth = getattr(self.request, "auth", None)
        return auth if isinstance(auth, MobileDevice) else None

    def handle_exception(self, exc):
        if isinstance(exc, MobileError):
            return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status, headers=exc.headers)
        if isinstance(exc, exceptions.Throttled):
            wait = int(exc.wait or 1)
            return Response({"error": {"code": "rate_limited", "message": f"درخواست‌ها زیاد است؛ {wait} ثانیه بعد دوباره."}},
                            status=429, headers={"Retry-After": str(wait)})
        if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
            code = getattr(exc.detail, "code", "") or "unauthenticated"
            if code in ("authentication_failed", "not_authenticated"):
                code = "unauthenticated"
            return Response({"error": {"code": code, "message": str(exc.detail)}}, status=401,
                            headers={"WWW-Authenticate": "Device"})
        if isinstance(exc, exceptions.PermissionDenied):
            code = getattr(exc.detail, "code", "") or "forbidden"
            if code == "permission_denied":
                code = "forbidden"
            return Response({"error": {"code": code, "message": str(exc.detail)}}, status=403)
        if isinstance(exc, exceptions.ValidationError):
            return Response({"error": {"code": "invalid", "message": _flatten(exc.detail)}}, status=400)
        if isinstance(exc, exceptions.NotFound):
            return Response({"error": {"code": "not_found", "message": "پیدا نشد."}}, status=404)
        if isinstance(exc, exceptions.ParseError):
            return Response({"error": {"code": "bad_request", "message": "قالبِ درخواست درست نیست."}}, status=400)
        return super().handle_exception(exc)


def _flatten(detail) -> str:
    if isinstance(detail, dict):
        return "؛ ".join(f"{k}: {_flatten(v)}" for k, v in detail.items())
    if isinstance(detail, (list, tuple)):
        return "؛ ".join(_flatten(v) for v in detail)
    return str(detail)


def log_action(request, action: str, target: str = "", params: dict | None = None, ok: bool = True, message: str = "", device=None,
               user=None):
    if user is None:
        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    dev = device or (request.auth if isinstance(getattr(request, "auth", None), MobileDevice) else None)
    return MobileActionLog.objects.create(
        user=user, device=dev, action=action, target=str(target)[:80], params=params or {}, ok=ok, message=message[:400],
        ip=client_ip(request),
    )


def require_fields(data, *names):
    missing = [n for n in names if not str(data.get(n, "")).strip()]
    if missing:
        raise MobileError("missing_fields", "این موارد لازم است: " + "، ".join(missing), 400)

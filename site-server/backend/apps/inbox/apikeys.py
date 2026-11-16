"""Per-store API keys for the inbox API.

Format: `nmk_<8-char prefix>_<32-char secret>`. Only the SHA-256 of the whole key
is stored; the prefix is stored in clear so the panel can show «nmk_ab12cd34…»
and so lookup is one indexed query instead of hashing against every row. The
full key is shown **once**, at creation - there is no "show it again", only
"revoke and make a new one", which is the property that makes a leaked database
dump useless for calling the API.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from django.core.cache import cache
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, Throttled
from rest_framework.permissions import BasePermission

from .models import ApiKey

SCOPES = ("read", "write")
#: Requests per minute per key. Generous for an integration, tight enough that
#: a runaway loop on the customer's side is noticed before it is a problem.
RATE_PER_MINUTE = 120


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(store, name: str, scopes, by) -> tuple[ApiKey, str]:
    scopes = [s for s in (scopes or ["read"]) if s in SCOPES] or ["read"]
    prefix = secrets.token_hex(4)
    key = f"nmk_{prefix}_{secrets.token_urlsafe(24)}"
    row = ApiKey.objects.create(
        store=store, name=(name or "کلید")[:80], prefix=prefix, key_hash=_hash(key),
        scopes=scopes, created_by=by,
    )
    return row, key


def lookup(raw: str) -> ApiKey | None:
    raw = (raw or "").strip()
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != "nmk":
        return None
    for row in ApiKey.objects.filter(prefix=parts[1], revoked_at__isnull=True).select_related("store"):
        if hmac.compare_digest(row.key_hash, _hash(raw)):
            return row
    return None


def revoke(row: ApiKey) -> None:
    row.revoked_at = timezone.now()
    row.save(update_fields=["revoked_at", "updated_at"])


class KeyAuthentication(BaseAuthentication):
    """`Authorization: Bearer nmk_...` or `X-API-Key: nmk_...`."""

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        raw = header[7:] if header.lower().startswith("bearer ") else request.headers.get("X-API-Key", "")
        if not raw:
            return None
        row = lookup(raw)
        if row is None:
            raise AuthenticationFailed("کلید API معتبر نیست یا باطل شده است.")
        bucket = f"inbox-api:{row.pk}:{int(timezone.now().timestamp() // 60)}"
        cache.add(bucket, 0, 90)
        try:
            used = cache.incr(bucket)
        except ValueError:
            used = 1
        if used > RATE_PER_MINUTE:
            raise Throttled(detail="تعداد درخواست‌ها از سقف دقیقه‌ای گذشت.")
        ApiKey.objects.filter(pk=row.pk).update(last_used_at=timezone.now())
        return (None, row)

    def authenticate_header(self, request):
        return "Bearer"


class HasKey(BasePermission):
    """The request carries a valid key; `write` views also need the write scope."""

    def has_permission(self, request, view):
        key = request.auth
        if not isinstance(key, ApiKey):
            return False
        needs = "write" if request.method not in ("GET", "HEAD", "OPTIONS") else "read"
        return needs in (key.scopes or [])

"""API keys a shop can put in their own system. Phase 29.

§28 of `ایده‌ها پنل.md`: "این همان سیستمی است که خودمان استفاده می‌کنیم — پس
اگر داخلاً درست ساخته شده باشد، بیرونی‌کردنش عمدتاً کار احراز هویت و سهمیه
است، نه بازنویسی." That is exactly what this is: authentication, quota and
documentation over the endpoints that already exist.

**The key is never stored.** Only a hash of it, the way a password is. A key
table an attacker can read is a table of live credentials to every shop that
uses the API, and "we will be careful with the database" is not a security
model. The plaintext is shown once, at creation, and never again — which is
mildly annoying and the correct trade.

**Why a visible prefix.** A shop with four keys needs to tell them apart in
their own config, and a hash cannot do that. The first eight characters are
stored in clear so the panel can show `up_live_a1b2c3d4…` next to a name.

**Quota comes from the subscription, not from the key.** A key is a way in, not
an allowance. Metering it separately would let a shop multiply their plan by
making more keys, and every generated image would still cost us the same GPU
minute.
"""
import hashlib
import secrets

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.stores.models import Store

#: Long enough that guessing is hopeless, short enough to paste.
KEY_BYTES = 32
PREFIX = "up_live_"
#: A different prefix so a test key is recognisable at a glance — in a config
#: file, in a log line, in a screenshot pasted into a support chat. Someone who
#: shipped the wrong one can see it without decoding anything.
TEST_PREFIX = "up_test_"
VISIBLE = 8


def generate_key(test: bool = False) -> tuple[str, str, str]:
    """Returns (plaintext, prefix, hash). The plaintext is never stored."""
    start = TEST_PREFIX if test else PREFIX
    raw = start + secrets.token_urlsafe(KEY_BYTES)
    return raw, raw[: len(start) + VISIBLE], hash_key(raw)


def hash_key(raw: str) -> str:
    """SHA-256. Not a slow KDF, and that is deliberate.

    A password needs a slow hash because it is short, human-chosen and guessable
    offline. This key is 32 random bytes — brute force is not the threat model,
    and a slow hash on every single API request would be a self-inflicted rate
    limit.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class APIKey(TimeStampedModel):
    """One credential belonging to one store."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(
        max_length=80,
        help_text="برای خودتان — مثلاً «سایت فروشگاه» یا «اپ موبایل»",
    )
    #: Shown in the panel so four keys can be told apart. Not a secret.
    prefix = models.CharField(max_length=32, db_index=True)
    #: The only thing we keep. See the module docstring.
    key_hash = models.CharField(max_length=64, unique=True)

    #: Which APIs this key may call. Empty means all of them — the common case,
    #: and narrowing is for a shop that wants a key only their website uses.
    scopes = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    #: A sandbox key. Its calls go through every check a live one does and stop
    #: at the last moment, returning a shaped example instead of queueing work.
    #: A developer gets the first five requests wrong; charging them GPU for
    #: that is a tax on integrating with us.
    is_test = models.BooleanField(
        default=False, help_text="کلید تست — هیچ پردازشی انجام نمی‌دهد و سهمیه مصرف نمی‌کند",
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    #: Kept so a shop can answer "is this key still in use?" before deleting it.
    call_count = models.PositiveIntegerField(default=0)
    #: Optional expiry. A key with no end date is fine for a shop's own server
    #: and wrong for a contractor's laptop.
    expires_at = models.DateTimeField(null=True, blank=True)

    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "is_active"])]
        verbose_name = "کلید API"
        verbose_name_plural = "کلیدهای API"

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def usable(self) -> bool:
        return self.is_active and not self.revoked_at and not self.is_expired

    def allows(self, scope: str) -> bool:
        """Empty scopes means everything; otherwise the scope must be listed."""
        return not self.scopes or scope in self.scopes

    def touch(self) -> None:
        """Record use without a write on every single request.

        `last_used_at` to the minute is plenty for "is this key still alive?",
        and updating a row on every call would put a write in front of every
        read the API serves.
        """
        now = timezone.now()
        if self.last_used_at and (now - self.last_used_at).total_seconds() < 60:
            APIKey.objects.filter(pk=self.pk).update(call_count=models.F("call_count") + 1)
            return
        APIKey.objects.filter(pk=self.pk).update(
            last_used_at=now, call_count=models.F("call_count") + 1,
        )


class APICall(TimeStampedModel):
    """One request, kept so a shop can debug their own integration.

    Not a full request log: no bodies, no headers. Those would hold customer
    messages and product data that the shop already has, and storing a second
    copy of it in a table nobody prunes is a liability rather than a feature.
    """

    key = models.ForeignKey(APIKey, on_delete=models.CASCADE, related_name="calls")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="api_calls")
    endpoint = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField(default=0)
    #: Present only when the call failed, and only the reason.
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "-created_at"])]
        verbose_name = "فراخوانی API"
        verbose_name_plural = "فراخوانی‌های API"

    def __str__(self):
        return f"{self.endpoint} → {self.status_code}"

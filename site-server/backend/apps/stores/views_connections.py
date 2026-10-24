"""Connecting the shop's own social accounts (`ایده‌ها پنل.md` صفحه ۳، بند ۱).

The plumbing was all there — `StoreProfile.novinhub_token`,
`novinhub_account_ids`, `Store.social_links`, and `services.publishing.channels`
already answering "is this channel configured" — and **no page ever asked for
any of it**. So every shop published through the shared `.env` token or not at
all, and the inbox showed «تنظیم نشده» next to channels the owner had no way to
set up.

Two things this does that the generic profile `PATCH` could not.

**It says what is missing, per channel, in the same response.** A token field
on its own leaves the owner guessing whether it worked; the channel list next
to it turns green when it did.

**The token is never sent back.** It is a credential belonging to the shop's
own account. Whether one is *set* is a yes/no, and that is the only part a
settings page needs in order to be useful.
"""
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.customers import webhooks
from services.publishing import channels

from . import access
from .models import StoreProfile

#: The ones a shop actually writes in. Free-form would mean a typo in a key
#: becomes a link nobody ever renders.
SOCIAL_KEYS = [
    ("instagram", "اینستاگرام"),
    ("telegram", "تلگرام"),
    ("whatsapp", "واتس‌اپ"),
    ("website", "سایت"),
    ("linkedin", "لینکدین"),
    ("aparat", "آپارات"),
]


class ConnectionsSerializer(serializers.Serializer):
    """Write-only where it must be, so a credential is never echoed back."""

    novinhub_token = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=255,
    )
    #: The shop's own Telegram bot. Empty means "use the shared one", which is
    #: what every shop used to do whether it wanted to or not.
    telegram_bot_token = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=255,
    )
    #: `allow_blank`, because the panel builds this by splitting a
    #: comma-separated box and a trailing comma yields "". Rejecting it would
    #: fail the whole save with `{'1': ['This field may not be blank.']}` —
    #: an error about an index, for a comma the person cannot see. The empties
    #: are dropped below instead.
    novinhub_account_ids = serializers.ListField(
        child=serializers.CharField(max_length=64, allow_blank=True), required=False,
    )
    social_links = serializers.DictField(
        child=serializers.CharField(allow_blank=True, max_length=300), required=False,
    )

    def validate_social_links(self, value):
        known = {key for key, _ in SOCIAL_KEYS}
        unknown = set(value) - known
        if unknown:
            raise serializers.ValidationError(
                f"کلید ناشناخته: {'، '.join(sorted(unknown))}"
            )
        return value


class StoreConnectionsView(APIView):
    """Read or change how this store reaches its own audience."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = access.get_store(request.user, pk, access.SETTINGS, write=False)
        profile, _ = StoreProfile.objects.get_or_create(store=store)
        return Response(self._payload(store, profile, request))

    def patch(self, request, pk):
        store = access.get_store(request.user, pk, access.SETTINGS)
        profile, _ = StoreProfile.objects.get_or_create(store=store)

        serializer = ConnectionsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "novinhub_token" in data:
            profile.novinhub_token = data["novinhub_token"].strip()
        if "telegram_bot_token" in data:
            profile.telegram_bot_token = data["telegram_bot_token"].strip()
        if "novinhub_account_ids" in data:
            profile.novinhub_account_ids = [
                i.strip() for i in data["novinhub_account_ids"] if i.strip()
            ]
        profile.save()

        if "social_links" in data:
            store.social_links = {
                k: v.strip() for k, v in data["social_links"].items() if v.strip()
            }
            store.save(update_fields=["social_links"])

        return Response(self._payload(store, profile, request))

    def _payload(self, store, profile, request) -> dict:
        return {
            # Never the token itself — only whether there is one.
            "has_token": bool((profile.novinhub_token or "").strip()),
            "has_telegram_token": bool((profile.telegram_bot_token or "").strip()),
            # True when this shop is answering through the installation's
            # shared bot, which is worth saying out loud: two shops on the
            # shared bot speak to customers under the same name.
            "telegram_shared": not (profile.telegram_bot_token or "").strip(),
            "novinhub_account_ids": list(profile.novinhub_account_ids or []),
            "social_links": dict(store.social_links or {}),
            "social_keys": [{"key": k, "label": label} for k, label in SOCIAL_KEYS],
            # The same list the inbox shows, so «تنظیم نشده» in one place and
            # «وصل است» in the other can never disagree.
            "channels": channels.status_for(store),
            # The inbound half. The URL is a bearer credential — anyone
            # holding it can deliver a message that runs the shop's AI — so it
            # is only ever returned to somebody who can already change these
            # settings, and the panel says what it is.
            "webhooks": {
                channel: request.build_absolute_uri(
                    f"/api/v1/webhooks/{channel}/{webhooks.secret_for(store)}/"
                )
                for channel in webhooks.CHANNELS
            },
            "webhook_note": (
                "این آدرس مثل رمز است — هرکس داشته باشد می‌تواند پیام بفرستد و "
                "هوش مصنوعی فروشگاه را به کار بیندازد. فقط در تنظیمات همان "
                "پلتفرم بگذارید."
            ),
            "shared_token_note": (
                "اگر توکن اختصاصی ندهید، از توکن مشترک NMarketing استفاده می‌شود — "
                "کار می‌کند، ولی انتشار از حساب ما انجام می‌شود نه حساب خودتان."
            ),
        }

"""Managing API keys from the panel, and the documentation that goes with them.

The docs live here rather than in a static page because they describe the
endpoints this file's neighbours implement — a separate document drifts, and a
shop debugging at midnight against stale docs concludes the API is broken.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from .models import APICall, APIKey, generate_key

#: What each endpoint does, in the shape the panel renders. Written for someone
#: wiring it into their own shop software, not for a marketing page.
ENDPOINTS = [
    {
        "scope": "sales_agent",
        "title": "ایجنت فروش",
        "method": "POST",
        "path": "/api/v1/public/sales-agent/",
        "sync": True,
        "body": {"message": "قیمت این کفش چند؟", "customer_id": "user-42"},
        "note": (
            "هم‌زمان جواب می‌دهد، چون پاسخ فروش دو دقیقه بعد بی‌فایده است. "
            "قیمت و موجودی از دیتابیس خوانده می‌شود و مدل عددی از خودش "
            "درنمی‌آورد."
        ),
    },
    {
        "scope": "caption",
        "title": "متن و کپشن",
        "method": "POST",
        "path": "/api/v1/public/caption/",
        "sync": False,
        "body": {"product_id": 12, "platforms": ["instagram", "telegram"]},
        "note": "job_id برمی‌گرداند؛ نتیجه را از status_url بگیرید.",
    },
    {
        "scope": "video",
        "title": "ویدیو تبلیغاتی",
        "method": "POST",
        "path": "/api/v1/public/video/",
        "sync": False,
        "body": {"product_id": 12, "duration": 15, "objective": "معرفی محصول"},
        "note": (
            "اول سناریو ساخته می‌شود. رندر ویدیو دقایقی طول می‌کشد و از همان "
            "سهمیه‌ی ثانیه‌ی ویدیوی پلن شما کم می‌شود."
        ),
    },
    {
        "scope": "poster",
        "title": "پوستر تبلیغاتی",
        "method": "POST",
        "path": "/api/v1/public/poster/",
        "sync": False,
        "body": {"product_id": 12, "style": "مینیمال", "instructions": ""},
        "note": "عکس را AI می‌سازد و متن فارسی را کد روی آن می‌نشاند.",
    },
    {
        "scope": "showcase",
        "title": "نمایش محصول",
        "method": "POST",
        "path": "/api/v1/public/showcase/",
        "sync": False,
        "body": {"product_id": 12, "mode": "scene"},
        "note": (
            "برخلاف پوستر، **محصول واقعی شما حفظ می‌شود**. `mode=enhance` فقط "
            "عکس موجود را بهتر می‌کند و کمترین تغییر را می‌دهد."
        ),
    },
    {
        "scope": "job_status",
        "title": "وضعیت کار",
        "method": "GET",
        "path": "/api/v1/public/jobs/{id}/",
        "sync": True,
        "body": None,
        "note": "برای هر کاری که job_id داده است.",
    },
]


class APIKeySerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)
    usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = APIKey
        fields = [
            "id", "name", "prefix", "scopes", "is_active", "usable", "is_test",
            "is_expired", "expires_at", "last_used_at", "call_count", "created_at",
        ]


class APIKeyListView(APIView):
    """The shop's keys, and the one place a new key's plaintext is ever shown."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS, write=False)
        return Response({
            "keys": APIKeySerializer(store.api_keys.all(), many=True).data,
            "endpoints": ENDPOINTS,
            "base_url": request.build_absolute_uri("/api/v1/public/"),
            "header": "X-Api-Key",
            # Said here rather than in a separate doc page, for the same reason
            # the endpoint docs are: a developer debugging at midnight reads
            # what the API tells them, not what a wiki said last year.
            "sandbox": {
                "how": "کلید را با `test: true` بسازید.",
                "note": (
                    "کلید تست از همه‌ی بررسی‌های کلید واقعی رد می‌شود — احراز "
                    "هویت، محدوده، پیدا کردن محصول، اعتبارسنجی ورودی — و فقط "
                    "در آخرین لحظه به‌جای صف‌کردن کار، یک نمونه‌ی هم‌شکل "
                    "برمی‌گرداند. پس فراخوانی‌ای که در تست کار کند، در واقعی هم "
                    "کار می‌کند."
                ),
                "marker": "هر پاسخ تست `\"sandbox\": true` دارد.",
            },
        })

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS)

        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response(
                {"error": {"code": "name_required", "message": "برای کلید یک نام بگذارید."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_test = bool(request.data.get("test"))
        raw, prefix, hashed = generate_key(test=is_test)
        key = APIKey.objects.create(
            store=store,
            name=name,
            prefix=prefix,
            key_hash=hashed,
            scopes=request.data.get("scopes") or [],
            is_test=is_test,
            created_by=request.user,
        )

        return Response(
            {
                "key": APIKeySerializer(key).data,
                # The only time this is ever returned. Stored as a hash, like a
                # password — a key table an attacker can read is a table of live
                # credentials to every shop that uses the API.
                "secret": raw,
                "warning": (
                    "این کلید فقط همین یک بار نشان داده می‌شود. جایی امن "
                    "ذخیره‌اش کنید — ما فقط هش آن را نگه می‌داریم و اگر گمش "
                    "کنید باید کلید تازه بسازید."
                ) + (
                    " این یک **کلید تست** است: شکل پاسخ‌ها دقیقاً مثل واقعی "
                    "است ولی هیچ پردازشی انجام نمی‌شود و سهمیه‌ای مصرف نمی‌کند."
                    if is_test else ""
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class APIKeyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        key = get_object_or_404(APIKey, pk=pk, store=store)

        # Revoked, not deleted: the call log points at it, and "which key made
        # these 4000 requests last Tuesday?" has to stay answerable.
        key.is_active = False
        key.revoked_at = timezone.now()
        key.save(update_fields=["is_active", "revoked_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class APIUsageView(APIView):
    """Recent calls, so a shop can debug their own integration."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS, write=False)
        rows = (
            APICall.objects.filter(store=store).select_related("key")[:100]
        )
        failed = [r for r in rows if r.status_code >= 400]
        return Response({
            "calls": [
                {
                    "endpoint": r.endpoint,
                    "status": r.status_code,
                    "ms": r.duration_ms,
                    "error": r.error,
                    "key": r.key.name,
                    "at": r.created_at,
                }
                for r in rows
            ],
            "total": len(rows),
            "failed": len(failed),
        })

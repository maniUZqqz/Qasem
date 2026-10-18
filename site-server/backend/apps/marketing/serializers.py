"""Lead intake.

Two rules shape this file:

1. **Ask for little.** Only name, email and message are required. Everything
   else is optional, because a longer required form converts worse and we can
   always ask later.
2. **Never trust the client on anything that matters.** Status, notes, IP and
   user agent are set server-side; a POST that tries to set `status=CONVERTED`
   is ignored rather than rejected, so a hostile client learns nothing.
"""
from rest_framework import serializers

from .models import Lead


class LeadCreateSerializer(serializers.ModelSerializer):
    """Public intake — anonymous, rate-limited, write-only."""

    # Honeypot: a field real people never see and never fill. Bots fill
    # everything. Cheaper and less hostile than a CAPTCHA, and it costs a
    # legitimate visitor nothing.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Lead
        fields = [
            "name",
            "email",
            "phone",
            "business",
            "subject",
            "message",
            "source_path",
            "referrer",
            "utm",
            "website",
        ]
        extra_kwargs = {
            "phone": {"required": False, "allow_blank": True},
            "business": {"required": False, "allow_blank": True},
            "subject": {"required": False},
            "source_path": {"required": False, "allow_blank": True},
            "referrer": {"required": False, "allow_blank": True},
            "utm": {"required": False},
        }

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("نام را کامل بنویسید.")
        return value

    def validate_message(self, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                "کمی بیشتر توضیح بدهید تا بتوانیم درست کمک کنیم."
            )
        if len(value) > 5000:
            raise serializers.ValidationError("پیام خیلی طولانی است.")
        return value

    def validate_utm(self, value):
        """Keep attribution small and flat — it is analytics, not storage."""
        if not isinstance(value, dict):
            return {}
        allowed = {"source", "medium", "campaign", "term", "content"}
        return {
            k: str(v)[:120] for k, v in value.items() if k in allowed and v
        }


class LeadAdminSerializer(serializers.ModelSerializer):
    """Read side, for our own inbox. Everything, including attribution."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    subject_display = serializers.CharField(source="get_subject_display", read_only=True)

    class Meta:
        model = Lead
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "ip", "user_agent"]

from rest_framework import serializers

from .models import Plan, Subscription, Usage


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id", "slug", "name", "description", "price_toman",
            "video_seconds", "images", "captions",
            "max_products", "max_stores",
            "allows_publishing", "allows_sales_agent",
            "is_trial", "trial_days", "sort_order",
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    days_left = serializers.IntegerField(read_only=True)
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id", "plan", "status", "period_start", "period_end",
            "days_left", "is_usable", "cancel_at_period_end",
            "bonus_video_seconds", "bonus_images", "bonus_captions",
        ]


class UsageSerializer(serializers.ModelSerializer):
    metric_label = serializers.CharField(source="get_metric_display", read_only=True)
    state_label = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = Usage
        fields = ["id", "metric", "metric_label", "quantity", "state", "state_label",
                  "external", "detail", "attempt", "quality_reason", "quality_source",
                  "created_at"]

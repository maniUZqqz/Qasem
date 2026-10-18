from rest_framework import serializers

from .models import AIRequest, MarketResearch, ProductIntelligence


class MarketResearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketResearch
        fields = [
            "id",
            "product",
            "research_inputs",
            "web_results",
            "observations",
            "conclusions",
            "confidence",
            "created_at",
            "updated_at",
        ]


class ProductIntelligenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductIntelligence
        fields = [
            "id",
            "product",
            "summary",
            "target_audience",
            "selling_points",
            "weaknesses",
            "objections",
            "marketing_angles",
            "positioning",
            "recommended_tone",
            "content_ideas",
            "use_cases",
            "visual_analysis",
            "created_at",
            "updated_at",
        ]


class AIRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIRequest
        fields = [
            "id",
            "task_type",
            "model",
            "prompt_id",
            "prompt_version",
            "status",
            "attempts",
            "latency_ms",
            "error",
            "created_at",
        ]

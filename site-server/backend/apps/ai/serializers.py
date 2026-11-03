from rest_framework import serializers

from .models import AIRequest, MarketResearch, ProductIntelligence


def _answer(obj):
    """«جواب از: لوکال (qwq:32b)» — از AIRequest ِ منبعِ این نتیجه (None اگر نتیجه از جای دیگری آمده)."""
    row = getattr(obj, "source_request", None)
    return row.answer_info() if row is not None else None


class MarketResearchSerializer(serializers.ModelSerializer):
    answer = serializers.SerializerMethodField()

    def get_answer(self, obj):
        return _answer(obj)

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
            "answer",
            "created_at",
            "updated_at",
        ]


class ProductIntelligenceSerializer(serializers.ModelSerializer):
    answer = serializers.SerializerMethodField()

    def get_answer(self, obj):
        return _answer(obj)

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
            "answer",
            "created_at",
            "updated_at",
        ]


class AIRequestSerializer(serializers.ModelSerializer):
    answer_label = serializers.CharField(read_only=True)

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
            "via",
            "fell_back",
            "fallback_reason",
            "answer_label",
            "created_at",
        ]

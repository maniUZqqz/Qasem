from django.contrib import admin

from .models import AIRequest, AIResponse, MarketResearch, ProductIntelligence


class AIResponseInline(admin.StackedInline):
    model = AIResponse
    extra = 0
    readonly_fields = ["raw_output", "parsed", "valid"]


@admin.register(AIRequest)
class AIRequestAdmin(admin.ModelAdmin):
    name_en = "AI requests"
    description = (
        "دفتر ثبت هر تماسی که با موتور هوش مصنوعی گرفته شده — چه مدلی، چه هزینه‌ای، چه "
        "جوابی. وقتی کسی می‌پرسد «چرا این‌قدر مصرف شد؟»، جواب اینجاست."
    )
    list_display = ["id", "task_type", "model", "prompt_id", "status", "latency_ms", "created_at"]
    list_filter = ["task_type", "status", "model"]
    inlines = [AIResponseInline]


@admin.register(ProductIntelligence)
class ProductIntelligenceAdmin(admin.ModelAdmin):
    name_en = "Product intelligence"
    description = (
        "برداشت هوش مصنوعی از هر محصول: مخاطب، لحن، نقاط قوت. کپشن و پوستر و سناریو همه "
        "از روی همین ساخته می‌شوند."
    )
    list_display = ["product", "recommended_tone", "updated_at"]


@admin.register(MarketResearch)
class MarketResearchAdmin(admin.ModelAdmin):
    name_en = "Market research"
    description = (
        "تحلیل رقبا و بازار برای یک محصول. «مشاهدات» فقط از داده‌ای است که کاربر داده؛ "
        "«نتیجه‌گیری» حرف هوش مصنوعی است. این دو عمداً جدا نگه داشته شده‌اند."
    )
    list_display = ["product", "store", "confidence", "created_at"]
    list_filter = ["confidence"]
from .admin_providers import ModelProviderAdmin  # noqa: F401
from .admin_audio import AudioEngineAdmin  # noqa: E402,F401

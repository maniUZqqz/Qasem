from django.contrib.auth.models import User
from django.db import models

from apps.common.models import TimeStampedModel
from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store


class AIRequest(TimeStampedModel):
    """Audit record of every call made through the AI orchestration layer."""

    class TaskType(models.TextChoices):
        REASONING = "REASONING", "استدلال"
        VISION = "VISION", "بینایی"
        CODE = "CODE", "کد"

    class Status(models.TextChoices):
        OK = "OK", "موفق"
        TIMEOUT = "TIMEOUT", "اتمام مهلت"
        PROVIDER_ERROR = "PROVIDER_ERROR", "خطای سرویس‌دهنده"
        MALFORMED_OUTPUT = "MALFORMED_OUTPUT", "خروجی نامعتبر"
        VALIDATION_FAILED = "VALIDATION_FAILED", "رد شدن در اعتبارسنجی"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="ai_requests")
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_requests")
    task_type = models.CharField(max_length=16, choices=TaskType.choices)
    model = models.CharField(max_length=64)
    prompt_id = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=16)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OK)
    attempts = models.PositiveIntegerField(default=1)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = "درخواست هوش مصنوعی"
        verbose_name_plural = "درخواست‌های هوش مصنوعی"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_type} {self.model} [{self.status}]"


class AIResponse(models.Model):
    request = models.OneToOneField(AIRequest, on_delete=models.CASCADE, related_name="response")
    raw_output = models.TextField(blank=True)
    parsed = models.JSONField(null=True, blank=True)
    valid = models.BooleanField(default=False)


class ProductIntelligence(TimeStampedModel):
    """Structured AI understanding of a product (replaces legacy free-text ProductAnalysis)."""

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="intelligence")
    summary = models.TextField(blank=True)
    target_audience = models.JSONField(default=list, blank=True)
    selling_points = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    objections = models.JSONField(default=list, blank=True)
    marketing_angles = models.JSONField(default=list, blank=True)
    positioning = models.TextField(blank=True)
    recommended_tone = models.CharField(max_length=100, blank=True)
    content_ideas = models.JSONField(default=list, blank=True)
    use_cases = models.JSONField(default=list, blank=True)
    visual_analysis = models.JSONField(default=list, blank=True)
    source_request = models.ForeignKey(
        AIRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "تحلیل محصول"
        verbose_name_plural = "تحلیل‌های محصول"

    def __str__(self):
        return f"Intelligence for {self.product.name}"


class ProductEmbedding(TimeStampedModel):
    """Vector embedding of a product's text, for semantic catalog search.

    Only written when EMBEDDINGS_ENABLED=true and an embedding model is
    installed on the Ollama host; the sales agent transparently falls back to
    keyword search when rows are missing.
    """

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="embedding")
    vector = models.JSONField(default=list)
    model = models.CharField(max_length=64)
    # hash of the embedded text — unchanged products are not re-embedded
    source_hash = models.CharField(max_length=40)

    def __str__(self):
        return f"Embedding for {self.product.name} ({self.model})"


class MarketResearch(TimeStampedModel):
    """Structured market/competitor analysis for a product.

    `research_inputs` holds real user-provided material (competitor names,
    prices, links, notes). `observations` are facts extracted ONLY from those
    inputs; `conclusions` are AI strategic reasoning, kept clearly separate so
    fabricated competitor data can never masquerade as fact.
    """

    class Confidence(models.TextChoices):
        LOW = "LOW", "کم"
        MEDIUM = "MEDIUM", "متوسط"
        HIGH = "HIGH", "زیاد"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="market_research")
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="market_research"
    )
    research_inputs = models.TextField(blank=True)
    web_results = models.JSONField(default=dict, blank=True)
    observations = models.JSONField(default=list, blank=True)
    conclusions = models.JSONField(default=dict, blank=True)
    confidence = models.CharField(
        max_length=8, choices=Confidence.choices, default=Confidence.LOW
    )
    source_request = models.ForeignKey(
        AIRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "تحقیق بازار"
        verbose_name_plural = "تحقیق‌های بازار"

    def __str__(self):
        return f"Market research for {self.product.name} ({self.created_at:%Y-%m-%d})"


class ModelProvider(TimeStampedModel):
    """Where a given AI capability is served from — local hardware or an API.

    The whole point is that switching between "our RTX 3060" and "someone
    else's API" is an admin decision, not a code change: pick the capability,
    paste a base URL, an API key and a model name, save. Business logic asks
    for a capability and never learns which side answered.

    Providers are tried in `priority` order, so a cheap local card can be the
    default with a paid API behind it as an overflow — or the reverse while
    the GPU box is down.
    """

    class Capability(models.TextChoices):
        TEXT = "TEXT", "متن، تحلیل و ریسرچ"
        VISION = "VISION", "تحلیل تصویر"
        IMAGE = "IMAGE", "تولید تصویر"
        VIDEO = "VIDEO", "تولید ویدیو"

    class Kind(models.TextChoices):
        # local, self-hosted — no API key, no per-call cost
        OLLAMA = "OLLAMA", "Ollama (لوکال)"
        COMFYUI = "COMFYUI", "ComfyUI (لوکال)"
        # remote APIs
        OPENAI = "OPENAI", "API سازگار با OpenAI"
        REPLICATE = "REPLICATE", "Replicate"
        HTTP = "HTTP", "HTTP سفارشی"

    LOCAL_KINDS = {Kind.OLLAMA, Kind.COMFYUI}

    capability = models.CharField(max_length=8, choices=Capability.choices)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    name = models.CharField(max_length=80, help_text="نام دلخواه برای تشخیص در پنل")

    base_url = models.URLField(
        blank=True,
        help_text="مثال: http://127.0.0.1:11434 یا https://api.openai.com/v1 — "
        "خالی یعنی از مقدار .env استفاده شود",
    )
    api_key = models.CharField(
        max_length=255, blank=True, help_text="برای سرویس‌های لوکال خالی بگذار"
    )
    model_name = models.CharField(
        max_length=120,
        help_text="نام مدل یا ورک‌فلو. مثال: qwq:32b · gpt-4o-mini · wan22_i2v@v1",
    )

    is_active = models.BooleanField(default=True)
    priority = models.PositiveSmallIntegerField(
        default=100, help_text="کمتر = زودتر امتحان می‌شود"
    )
    timeout_s = models.PositiveIntegerField(default=600)
    options = models.JSONField(
        default=dict, blank=True,
        help_text="پارامترهای اضافه به‌صورت JSON (temperature، steps، …)",
    )

    # ---- data governance -------------------------------------------------
    # An external provider is a place our customers' data goes. Recording
    # where, for how long, and under whose terms is the difference between a
    # privacy promise and a privacy claim.

    class DataLocation(models.TextChoices):
        ON_PREMISE = "ON_PREMISE", "روی سرور خودمان"
        IRAN = "IRAN", "ایران"
        EU = "EU", "اتحادیه اروپا"
        US = "US", "آمریکا"
        OTHER = "OTHER", "جای دیگر"
        UNKNOWN = "UNKNOWN", "نامشخص"

    class DataClass(models.TextChoices):
        PRODUCT = "PRODUCT", "محصول (متن و تصویر کالا)"
        BRAND = "BRAND", "برند (لحن، قوانین، پروفایل فروشگاه)"
        CUSTOMER = "CUSTOMER", "مشتری (پیام، نام، سفارش)"

    ALL_DATA_CLASSES = [DataClass.PRODUCT, DataClass.BRAND, DataClass.CUSTOMER]
    # What an external provider may see unless the operator widens it. Customer
    # messages are excluded on purpose: that data belongs to a third person who
    # is not in the room when this row is filled in.
    DEFAULT_EXTERNAL_DATA = [DataClass.PRODUCT, DataClass.BRAND]

    data_location = models.CharField(
        max_length=12, choices=DataLocation.choices, default=DataLocation.UNKNOWN,
        verbose_name="داده کجا پردازش می‌شود",
    )
    is_approved = models.BooleanField(
        default=False,
        verbose_name="تأییدشده",
        help_text="فروشگاه‌هایی که «فقط سرویس‌های تأییدشده» را انتخاب کرده‌اند، "
                  "تنها از سرویس‌های تیک‌خورده استفاده می‌کنند.",
    )
    allowed_data = models.JSONField(
        default=list, blank=True,
        verbose_name="مجاز برای کدام داده",
        help_text="خالی برای سرویس لوکال یعنی همه‌چیز؛ برای سرویس بیرونی یعنی "
                  "فقط محصول و برند.",
    )
    data_retention = models.CharField(
        max_length=200, blank=True,
        verbose_name="نگه‌داری داده",
        help_text="مثال: «۳۰ روز برای پایش سوءاستفاده» یا «نگه‌داری نمی‌شود».",
    )
    privacy_policy_url = models.URLField(blank=True, verbose_name="لینک سیاست حریم خصوصی")

    # filled in by the admin "test connection" action
    checked_at = models.DateTimeField(null=True, blank=True)
    is_healthy = models.BooleanField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["capability", "priority", "id"]
        indexes = [models.Index(fields=["capability", "is_active", "priority"])]
        verbose_name = "موتور هوش مصنوعی"
        verbose_name_plural = "موتورهای هوش مصنوعی"

    def __str__(self):
        return f"{self.get_capability_display()} · {self.name} ({self.get_kind_display()})"

    @property
    def is_local(self) -> bool:
        """Local providers cost GPU minutes; remote ones cost money per call."""
        return self.kind in self.LOCAL_KINDS

    @property
    def effective_allowed_data(self) -> list[str]:
        """Data classes this provider may see, with the blank field resolved.

        Blank means "the safe default for this kind", not "everything": a new
        external provider row saved without thinking about the field must not
        silently gain access to customer messages.
        """
        if self.allowed_data:
            return list(self.allowed_data)
        return list(self.ALL_DATA_CLASSES if self.is_local else self.DEFAULT_EXTERNAL_DATA)

    def clean(self):
        from django.core.exceptions import ValidationError

        if not self.is_local and not self.base_url:
            raise ValidationError({"base_url": "برای سرویس بیرونی، آدرس الزامی است."})
        if self.kind == self.Kind.COMFYUI and self.capability not in {
            self.Capability.IMAGE, self.Capability.VIDEO,
        }:
            raise ValidationError({"kind": "ComfyUI فقط تصویر و ویدیو تولید می‌کند."})
        if self.kind == self.Kind.OLLAMA and self.capability not in {
            self.Capability.TEXT, self.Capability.VISION,
        }:
            raise ValidationError({"kind": "Ollama فقط متن و تحلیل تصویر انجام می‌دهد."})
        # "Approved" has to mean something. A row marked approved without a
        # stated data location is the exact rubber stamp this field exists to
        # prevent.
        if self.is_approved and not self.is_local:
            if self.data_location == self.DataLocation.UNKNOWN:
                raise ValidationError({
                    "data_location": "سرویس بیرونی تأییدشده باید مشخص کند داده کجا پردازش می‌شود.",
                })
            if not self.data_retention:
                raise ValidationError({
                    "data_retention": "سرویس بیرونی تأییدشده باید بگوید داده چقدر نگه داشته می‌شود.",
                })
        unknown = set(self.allowed_data or []) - {c.value for c in self.DataClass}
        if unknown:
            raise ValidationError({
                "allowed_data": f"نوع داده‌ی ناشناخته: {'، '.join(sorted(unknown))}",
            })


class StoreAIPolicy(TimeStampedModel):
    """How much of a store's data is allowed to leave our servers.

    Until this existed, `ModelProvider` was a platform-wide switch: an operator
    could point TEXT at a foreign API and every store's product copy — and
    every customer's chat message — would start flowing there, with the store
    owner neither seeing it nor agreeing to it. That is the whole reason this
    model has a `store` foreign key and the provider table does not.

    A store with no row here follows the platform default
    (`AI_DEFAULT_POLICY`), which is HYBRID — the behaviour every install had
    before this model was added.
    """

    class Mode(models.TextChoices):
        LOCAL_ONLY = "LOCAL_ONLY", "فقط لوکال — هیچ داده‌ای از سرور خارج نمی‌شود"
        APPROVED_EXTERNAL = "APPROVED_EXTERNAL", "فقط سرویس‌های تأییدشده"
        HYBRID = "HYBRID", "ترکیبی — هر سرویس فعالی، با اعلام شفاف"

    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name="ai_policy")
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.HYBRID)

    # Product copy leaving the country is a business decision. A customer's
    # private message leaving the country is someone else's decision, made
    # about them, so it is off unless the owner deliberately turns it on.
    allow_customer_data_external = models.BooleanField(
        default=False,
        verbose_name="ارسال پیام‌های مشتری به سرویس بیرونی",
        help_text="پیش‌فرض خاموش. پیام خصوصی مشتری، داده‌ی خود اوست نه فروشگاه.",
    )

    # Consent is only meaningful if we can say who gave it and when.
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "سیاست داده‌ی فروشگاه"
        verbose_name_plural = "سیاست‌های داده‌ی فروشگاه"

    def __str__(self):
        return f"{self.store.name} · {self.get_mode_display()}"


# Competitor registry and opportunities live in their own module for size;
# Django only discovers models imported from here.
from .competitor_models import (  # noqa: E402,F401
    Competitor,
    CompetitorProduct,
    Opportunity,
)

# Trends and the content ideas made from them (§6). Imported here so Django
# discovers them; they live in their own module because trends are a different
# subject from providers and policy.
from .trend_models import Trend, TrendIdea  # noqa: E402,F401

# Voice, ambience/effects and noise-removal engines, plus the mix levels and
# the local sound library. Their own module: sound is a different subject from
# text models, but it is switched in the same place (the admin) for the same
# reason — which engine answers is an operator decision, not a code change.
from .audio_models import AudioEngine, AudioMix, SoundClip  # noqa: E402,F401

# Cloned voices: consent and recordings live here, the voice itself on a processing node
# (services.audio.voice_clone).
from .voice_clone_models import ClonedVoice, ClonedVoiceClip  # noqa: E402,F401

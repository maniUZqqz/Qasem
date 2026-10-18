"""How the sales agent should talk for one particular shop.

ROADMAP §9.15 sets the bar: "این تنظیمات باید **واقعاً روی رفتار مدل اعمال
شوند**، نه اینکه فقط ذخیره شوند." A settings page that writes rows nobody reads
is worse than no settings page — the owner believes they have configured
something and stops watching.

So the settings arrive in three separate ways, each doing a different job:

1. **In the prompt**, as an explicit instruction block. This is what makes the
   model *usually* comply.
2. **After the answer**, as a check on the text. `never_say` phrases are looked
   for in the reply itself, because "usually" is not a promise. A reply that
   breaks the rule is rejected like malformed JSON is: try the next model, and
   if nothing clean comes back, hand the conversation to a human.
3. **Never at all** for the two rules that do not bend: prices and stock come
   from the database, and a payment is confirmed by a person. No wording in
   any settings field can reach those — they are enforced in code, after the
   model has spoken.
"""
from django.db import models

from apps.common.models import TimeStampedModel

from .models import Store


class SalesAgentSettings(TimeStampedModel):
    """Brand voice and selling rules for one store's agent."""

    class Tone(models.TextChoices):
        FORMAL = "FORMAL", "رسمی"
        FRIENDLY = "FRIENDLY", "دوستانه"
        PROFESSIONAL = "PROFESSIONAL", "حرفه‌ای"
        WARM = "WARM", "صمیمی"
        CUSTOM = "CUSTOM", "لحن سفارشی خودم"

    #: What each tone means to the model. Kept here rather than in the prompt
    #: file so the label the owner picks and the instruction the model gets can
    #: never drift apart.
    TONE_INSTRUCTION = {
        Tone.FORMAL: "با لحن رسمی و محترمانه بنویس. از «شما» استفاده کن و از شوخی پرهیز کن.",
        Tone.FRIENDLY: "با لحن دوستانه و گرم بنویس، ولی حرفه‌ای بمان. جمله‌ها کوتاه و ساده.",
        Tone.PROFESSIONAL: "با لحن حرفه‌ای و دقیق بنویس. روی مشخصات و واقعیت‌ها تکیه کن، نه احساسات.",
        Tone.WARM: "با لحن صمیمی و خودمانی بنویس، مثل فروشنده‌ای که مشتری را می‌شناسد.",
    }

    store = models.OneToOneField(
        Store, on_delete=models.CASCADE, related_name="agent_settings"
    )

    tone = models.CharField(max_length=14, choices=Tone.choices, default=Tone.FRIENDLY)
    custom_tone = models.TextField(
        blank=True,
        verbose_name="لحن سفارشی",
        help_text="اگر «لحن سفارشی» را انتخاب کردی، اینجا توضیح بده چطور حرف بزند.",
    )

    always_say = models.TextField(
        blank=True,
        verbose_name="همیشه این‌ها را بگو",
        help_text="مثلاً: «ارسال تهران همان‌روز است» یا «ضمانت اصالت کالا داریم».",
    )
    never_say = models.TextField(
        blank=True,
        verbose_name="هرگز این‌ها را نگو",
        help_text="هر خط یک عبارت. اگر جواب مدل شامل این عبارت‌ها باشد، "
                  "جواب رد می‌شود و دوباره تولید می‌شود.",
    )
    sale_terms = models.TextField(
        blank=True,
        verbose_name="شرایط فروش",
        help_text="حداقل سفارش، شهرهای تحت پوشش، شرایط پیش‌پرداخت…",
    )
    limits = models.TextField(
        blank=True,
        verbose_name="محدودیت‌ها",
        help_text="کارهایی که ایجنت نباید انجام دهد — مثلاً قول زمان دقیق تحویل ندهد.",
    )

    # ---- discounts -------------------------------------------------------
    # Kept as a flag plus free text rather than only free text: "may this agent
    # offer a discount at all" is a yes/no the owner should be able to answer
    # without trusting a sentence to be interpreted correctly.
    can_offer_discount = models.BooleanField(
        default=False,
        verbose_name="اجازه‌ی پیشنهاد تخفیف",
        help_text="خاموش یعنی ایجنت هیچ تخفیفی پیشنهاد نمی‌دهد و سؤال تخفیف را به شما ارجاع می‌دهد.",
    )
    discount_policy = models.TextField(
        blank=True,
        verbose_name="سیاست تخفیف",
        help_text="کِی و چقدر. مثلاً «بالای ۳ عدد، ۱۰٪».",
    )

    escalate_on_complaint = models.BooleanField(
        default=True,
        verbose_name="شکایت را به آدم ارجاع بده",
        help_text="مشتری ناراضی معمولاً جواب انسان می‌خواهد، نه جواب درست.",
    )

    class Meta:
        verbose_name = "تنظیمات ایجنت فروش"
        verbose_name_plural = "تنظیمات ایجنت فروش"

    def __str__(self):
        return f"تنظیمات ایجنت {self.store.name}"

    # ------------------------------------------------------------------

    @property
    def tone_instruction(self) -> str:
        """The sentence the model is actually given about voice."""
        if self.tone == self.Tone.CUSTOM:
            return self.custom_tone.strip() or self.TONE_INSTRUCTION[self.Tone.FRIENDLY]
        return self.TONE_INSTRUCTION.get(self.tone, "")

    @property
    def banned_phrases(self) -> list[str]:
        """`never_say`, one phrase per line, blanks dropped.

        Read as a list rather than a blob because the check after the model
        speaks needs individual phrases, not a paragraph.
        """
        return [
            line.strip()
            for line in (self.never_say or "").splitlines()
            if line.strip()
        ]

    def as_prompt_rules(self) -> dict:
        """The block handed to the prompt builder. Empty values are left out —
        a prompt full of "(not set)" teaches the model that rules are optional.
        """
        rules = {"tone": self.tone_instruction}
        if self.always_say.strip():
            rules["always_mention"] = self.always_say.strip()
        if self.banned_phrases:
            rules["never_say"] = self.banned_phrases
        if self.sale_terms.strip():
            rules["sale_terms"] = self.sale_terms.strip()
        if self.limits.strip():
            rules["limits"] = self.limits.strip()

        if self.can_offer_discount:
            rules["discounts"] = (
                self.discount_policy.strip()
                or "تخفیف مجاز است ولی سیاستی مشخص نشده — تخفیف نده و به فروشنده ارجاع بده."
            )
        else:
            rules["discounts"] = (
                "هیچ تخفیفی پیشنهاد نکن. اگر مشتری تخفیف خواست، بگو باید با فروشنده هماهنگ شود."
            )

        if self.escalate_on_complaint:
            rules["on_complaint"] = "برای شکایت، needs_human را true بگذار."
        return rules


def settings_for(store) -> SalesAgentSettings:
    """This store's settings, creating the default row on first use.

    Defaults are deliberately conservative: friendly tone, no discounts,
    complaints go to a person. An agent that starts out promising discounts
    because nobody configured it is a bill the shop did not agree to.
    """
    row, _ = SalesAgentSettings.objects.get_or_create(store=store)
    return row


def violations(reply: str, banned: list[str]) -> list[str]:
    """Which forbidden phrases appear in this reply.

    Plain case-insensitive substring matching. Persian has no cheap stemmer
    worth trusting here, and a fuzzy match that rejects good replies would push
    the owner to empty the field — which removes the protection entirely.
    """
    if not reply or not banned:
        return []
    haystack = reply.casefold()
    return [phrase for phrase in banned if phrase.casefold() in haystack]

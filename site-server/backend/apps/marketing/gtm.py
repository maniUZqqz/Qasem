"""Where customers come from, and what we owe the people who sent them. Phase 26.

Four things live here — referral, affiliate, discount codes and the attribution
that ties a signup back to whatever produced it — because they are one subject:
**a code someone used at signup, and what follows from it.**

Three decisions worth reading before the code.

**Attribution is recorded once, at signup, and never recomputed.** A store that
arrived through a referral in March is still a referral in December, even after
that referral code is deleted and the campaign it belonged to is forgotten. A
report that derives attribution from live rows changes its own history every
time somebody tidies up, and a number that moves on its own is a number nobody
trusts.

**Nothing is paid out from here.** `Reward` records what is owed and who it is
owed to; marking it paid is a separate, deliberate act by a person. An automatic
payout pipeline built on a signup event is a fraud surface, and the fix after
the fact is clawing money back from customers.

**A discount is validated against a moment, not a flag.** `unusable_because`
takes the plan and the time and answers for those, because "is this code valid"
has no answer on its own — it was valid yesterday, for a different plan, for a customer
who had not used it yet.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel

#: Unambiguous in Persian handwriting and over the phone: no 0/O, no 1/I/l.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_code(prefix: str = "", length: int = 8) -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{prefix}{body}" if prefix else body


class ReferralCode(TimeStampedModel):
    """One shop inviting another. «مشتری، مشتری می‌آورد»."""

    owner = models.ForeignKey(
        "auth.User", on_delete=models.CASCADE, related_name="referral_codes",
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, null=True, blank=True,
        related_name="referral_codes",
    )
    code = models.CharField(max_length=24, unique=True)
    is_active = models.BooleanField(default=True)
    #: What the referrer gets, in toman, when someone they sent starts paying.
    reward_toman = models.PositiveIntegerField(default=0)
    #: What the new shop gets — a discount percentage applied to their first
    #: period. Both sides get something or the code does not spread.
    friend_discount_percent = models.PositiveSmallIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = make_code("REF-", 6)
        super().save(*args, **kwargs)

    @property
    def signups(self) -> int:
        return self.attributions.count()

    @property
    def paying(self) -> int:
        """Signups that turned into paying shops — the number that matters.

        Counting signups alone rewards whoever can create the most accounts,
        which is the failure mode of every referral programme.
        """
        return self.attributions.filter(became_paying_at__isnull=False).count()


class Affiliate(TimeStampedModel):
    """A partner who sends shops our way for a cut. Not a customer."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "در انتظار تأیید"
        ACTIVE = "ACTIVE", "فعال"
        PAUSED = "PAUSED", "متوقف"
        BANNED = "BANNED", "مسدود"

    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="affiliate_profiles",
    )
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    code = models.CharField(max_length=24, unique=True)
    #: Percent of what the referred shop pays, for the window below.
    commission_percent = models.PositiveSmallIntegerField(default=20)
    #: How long commission keeps accruing. Open-ended commission on a customer
    #: who stayed four years is a liability nobody modelled when signing.
    commission_months = models.PositiveSmallIntegerField(default=12)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.PENDING,
    )
    payout_details = models.TextField(blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = make_code("AFF-", 6)
        super().save(*args, **kwargs)

    @property
    def usable(self) -> bool:
        return self.status == self.Status.ACTIVE


class DiscountCode(TimeStampedModel):
    """«کد تخفیف». Validated against a moment, never against a flag."""

    class Kind(models.TextChoices):
        PERCENT = "PERCENT", "درصدی"
        AMOUNT = "AMOUNT", "مبلغ ثابت"

    code = models.CharField(max_length=24, unique=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.PERCENT)
    value = models.PositiveIntegerField(help_text="درصد، یا مبلغ به تومان")
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    #: 0 means unlimited. Counted against `used_count`, which only a successful
    #: subscription increments.
    max_uses = models.PositiveIntegerField(default=0)
    used_count = models.PositiveIntegerField(default=0)
    once_per_store = models.BooleanField(default=True)
    #: Empty means every plan.
    plans = models.ManyToManyField(
        "billing.Plan", blank=True, related_name="discount_codes",
    )
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = make_code("", 8)
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------

    def unusable_because(self, *, plan=None, store=None, at=None) -> str | None:
        """Why this code cannot be used right now, or None if it can.

        Not called `check`: Django reserves that name on Model for its system
        checks, and shadowing it makes `manage.py check` fail on this app.

        Returns the reason rather than a boolean because every one of these is
        something the customer needs told: "expired" and "not for this plan"
        lead to completely different next actions, and «کد نامعتبر است» for both
        sends someone to support.
        """
        at = at or timezone.now()

        if not self.is_active:
            return "این کد دیگر فعال نیست."
        if self.starts_at and at < self.starts_at:
            return "این کد هنوز شروع نشده است."
        if self.ends_at and at > self.ends_at:
            return "این کد منقضی شده است."
        # Before the capacity check, not after. When a shop used the last of a
        # code's capacity themselves, both are true — and "you already used
        # this" explains what happened, while "it is full" sounds like they
        # missed out on something.
        if store is not None and self.once_per_store and \
                self.redemptions.filter(store=store).exists():
            return "این کد قبلاً برای همین فروشگاه استفاده شده است."
        if self.max_uses and self.used_count >= self.max_uses:
            return "ظرفیت استفاده از این کد پر شده است."
        if plan is not None and self.plans.exists() and not self.plans.filter(pk=plan.pk).exists():
            # Names the plans it *does* work on, not the one they picked.
            # "this code is not for your plan" ends the conversation; "this
            # code works on حرفه‌ای" is something they can act on.
            allowed = "، ".join(self.plans.values_list("name", flat=True))
            return f"این کد فقط روی این پلن‌ها کار می‌کند: {allowed}"
        return None

    def discount_on(self, price_toman: int) -> int:
        """How much comes off. Never more than the price itself."""
        if self.kind == self.Kind.PERCENT:
            off = price_toman * min(100, self.value) // 100
        else:
            off = self.value
        return max(0, min(off, price_toman))


class Redemption(TimeStampedModel):
    """One use of a discount code, by one store.

    Kept as its own row so `once_per_store` has something to check and so the
    revenue report can subtract what was actually given away rather than what
    the code says it gives away.
    """

    code = models.ForeignKey(
        DiscountCode, on_delete=models.CASCADE, related_name="redemptions",
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="redemptions",
    )
    plan = models.ForeignKey(
        "billing.Plan", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    price_toman = models.PositiveIntegerField(default=0)
    discount_toman = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code_id} → {self.store_id}"


class Attribution(TimeStampedModel):
    """Where this shop came from. Written once, at signup, and left alone.

    Every field is a copy, not a link, for the channel and campaign: a report
    that re-derives attribution from live rows rewrites its own history every
    time somebody renames a campaign, and a number that moves on its own is one
    nobody trusts.
    """

    class Channel(models.TextChoices):
        DIRECT = "DIRECT", "مستقیم"
        REFERRAL = "REFERRAL", "معرفی مشتری"
        AFFILIATE = "AFFILIATE", "همکار فروش"
        SEARCH = "SEARCH", "جست‌وجو"
        SOCIAL = "SOCIAL", "شبکه‌های اجتماعی"
        ADS = "ADS", "تبلیغات"
        CONTENT = "CONTENT", "بلاگ و محتوا"
        OTHER = "OTHER", "سایر"

    store = models.OneToOneField(
        "stores.Store", on_delete=models.CASCADE, related_name="attribution",
    )
    channel = models.CharField(
        max_length=10, choices=Channel.choices, default=Channel.DIRECT,
    )
    #: Copies, deliberately. See the class docstring.
    campaign = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=120, blank=True)
    medium = models.CharField(max_length=120, blank=True)
    landing_path = models.CharField(max_length=300, blank=True)
    referrer = models.CharField(max_length=300, blank=True)

    referral = models.ForeignKey(
        ReferralCode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attributions",
    )
    affiliate = models.ForeignKey(
        Affiliate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attributions",
    )
    lead = models.ForeignKey(
        "marketing.Lead", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attributions",
    )

    #: The moment this became a real customer. Null until it does, which is the
    #: difference between a signup and a business.
    became_paying_at = models.DateTimeField(null=True, blank=True)
    first_payment_toman = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["channel", "-created_at"])]

    def __str__(self):
        return f"{self.store_id} ← {self.get_channel_display()}"

    @property
    def days_to_pay(self) -> int | None:
        if self.became_paying_at is None:
            return None
        return (self.became_paying_at - self.created_at).days


class Reward(TimeStampedModel):
    """What we owe someone, and whether we have paid it.

    Recorded automatically, paid by a person. An automatic payout triggered by a
    signup event is a fraud surface, and the remedy afterwards is taking money
    back from customers.
    """

    class Kind(models.TextChoices):
        REFERRAL = "REFERRAL", "پاداش معرفی"
        COMMISSION = "COMMISSION", "کمیسیون همکار"

    class State(models.TextChoices):
        PENDING = "PENDING", "در انتظار"
        APPROVED = "APPROVED", "تأیید‌شده"
        PAID = "PAID", "پرداخت‌شده"
        VOID = "VOID", "باطل"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    state = models.CharField(
        max_length=8, choices=State.choices, default=State.PENDING,
    )
    amount_toman = models.PositiveIntegerField(default=0)
    #: Who earns it. One of these, never both.
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rewards",
    )
    affiliate = models.ForeignKey(
        Affiliate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rewards",
    )
    #: What earned it.
    attribution = models.ForeignKey(
        Attribution, on_delete=models.CASCADE, related_name="rewards",
    )
    because = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["state", "-created_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount_toman:,} ({self.get_state_display()})"

    def pay(self, by) -> None:
        self.state = self.State.PAID
        self.paid_at = timezone.now()
        self.paid_by = by
        self.save(update_fields=["state", "paid_at", "paid_by", "updated_at"])


# ------------------------------------------------------------------ the flow


def resolve_code(code: str) -> tuple[str, object | None]:
    """One box on the signup form, three kinds of code behind it.

    Making a customer know whether they were handed a referral, an affiliate or
    a discount code is asking them to understand our business model to sign up.
    """
    code = (code or "").strip().upper()
    if not code:
        return "none", None

    referral = ReferralCode.objects.filter(code__iexact=code, is_active=True).first()
    if referral is not None:
        return "referral", referral

    affiliate = Affiliate.objects.filter(
        code__iexact=code, status=Affiliate.Status.ACTIVE,
    ).first()
    if affiliate is not None:
        return "affiliate", affiliate

    discount = DiscountCode.objects.filter(code__iexact=code).first()
    if discount is not None:
        return "discount", discount
    return "unknown", None


def record_signup(store, *, code: str = "", utm: dict | None = None,
                  landing_path: str = "", referrer: str = "", lead=None) -> Attribution:
    """Write down where this shop came from. Idempotent per store.

    Idempotent because it is called from signup, which can be retried, and a
    second attribution row would let one shop be counted for two channels.
    """
    existing = Attribution.objects.filter(store=store).first()
    if existing is not None:
        return existing

    utm = utm or {}
    kind, found = resolve_code(code)

    channel = _channel_from(kind, utm, referrer)
    return Attribution.objects.create(
        store=store,
        channel=channel,
        campaign=str(utm.get("utm_campaign", ""))[:120],
        source=str(utm.get("utm_source", ""))[:120],
        medium=str(utm.get("utm_medium", ""))[:120],
        landing_path=landing_path[:300],
        referrer=referrer[:300],
        referral=found if kind == "referral" else None,
        affiliate=found if kind == "affiliate" else None,
        lead=lead,
    )


def _channel_from(kind: str, utm: dict, referrer: str) -> str:
    if kind == "referral":
        return Attribution.Channel.REFERRAL
    if kind == "affiliate":
        return Attribution.Channel.AFFILIATE

    medium = str(utm.get("utm_medium", "")).lower()
    source = str(utm.get("utm_source", "")).lower()
    if medium in ("cpc", "ppc", "paid", "ads"):
        return Attribution.Channel.ADS
    if any(s in source for s in ("instagram", "telegram", "twitter", "linkedin")):
        return Attribution.Channel.SOCIAL
    if any(s in source for s in ("google", "bing", "duckduckgo")):
        return Attribution.Channel.SEARCH
    if "/blog" in referrer:
        return Attribution.Channel.CONTENT
    if referrer:
        return Attribution.Channel.OTHER
    return Attribution.Channel.DIRECT


def record_payment(store, amount_toman: int) -> list[Reward]:
    """The shop paid. Mark it, and record what that owes anyone.

    Only the *first* payment creates a referral reward, and commission accrues
    only inside the affiliate's window. Both limits exist because open-ended
    payouts on a customer who stayed four years are a liability nobody modelled
    when they signed the agreement.
    """
    attribution = Attribution.objects.filter(store=store).first()
    if attribution is None:
        return []

    first = attribution.became_paying_at is None
    if first:
        attribution.became_paying_at = timezone.now()
        attribution.first_payment_toman = amount_toman
        attribution.save(update_fields=[
            "became_paying_at", "first_payment_toman", "updated_at",
        ])

    rewards = []

    if first and attribution.referral and attribution.referral.reward_toman:
        rewards.append(Reward.objects.create(
            kind=Reward.Kind.REFERRAL,
            amount_toman=attribution.referral.reward_toman,
            user=attribution.referral.owner,
            attribution=attribution,
            because=f"فروشگاه «{store.name}» با کد {attribution.referral.code} آمد و پرداخت کرد",
        ))

    affiliate = attribution.affiliate
    if affiliate and affiliate.usable:
        window = timedelta(days=30 * affiliate.commission_months)
        if timezone.now() - attribution.created_at <= window:
            rewards.append(Reward.objects.create(
                kind=Reward.Kind.COMMISSION,
                amount_toman=amount_toman * affiliate.commission_percent // 100,
                affiliate=affiliate,
                attribution=attribution,
                because=(
                    f"{affiliate.commission_percent}٪ از پرداخت "
                    f"{amount_toman:,} تومانی «{store.name}»"
                ),
            ))

    return rewards


def redeem(code: DiscountCode, store, plan, price_toman: int) -> Redemption:
    """Use a discount. Assumes `unusable_because` already returned None."""
    discount = code.discount_on(price_toman)
    row = Redemption.objects.create(
        code=code, store=store, plan=plan,
        price_toman=price_toman, discount_toman=discount,
    )
    # F() rather than read-modify-write: two shops redeeming the last use of a
    # code at the same moment would otherwise both succeed.
    DiscountCode.objects.filter(pk=code.pk).update(
        used_count=models.F("used_count") + 1,
    )
    return row

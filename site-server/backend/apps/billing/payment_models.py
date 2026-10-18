"""Payments and the audit trail.

A `Payment` is one attempt, not one success. Failed and abandoned attempts are
kept on purpose: "why did this customer not subscribe" is answerable from the
row that says the gateway declined them, and unanswerable if we only store
what worked.

The same row is the invoice and the transaction-history entry. A separate
Invoice model would be a second source of truth for the same money, and those
drift.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.stores.models import Store

from .models import Plan, Subscription


class Payment(TimeStampedModel):
    """One attempt to pay for a plan."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "در انتظار پرداخت"
        PAID = "PAID", "پرداخت‌شده"
        FAILED = "FAILED", "ناموفق"
        # The customer left the gateway and never came back. Distinct from
        # FAILED, which means the gateway actively said no.
        ABANDONED = "ABANDONED", "رها‌شده"
        REFUNDED = "REFUNDED", "بازگردانده‌شده"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="payments")
    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="payments")

    # Frozen at creation. The plan's price may change later; what this customer
    # owed is what it cost on the day, and an invoice must not move.
    amount_toman = models.PositiveIntegerField()

    provider = models.CharField(max_length=24)
    #: gateway-side id for this attempt
    token = models.CharField(max_length=120, blank=True, db_index=True)
    #: bank reference, for a customer who disputes the charge
    reference = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    #: human-readable invoice number, shown to the customer
    invoice_number = models.CharField(max_length=24, unique=True, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_reason = models.CharField(max_length=300, blank=True)

    #: who confirmed a manual transfer, if that is how this was paid
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="confirmed_payments",
    )

    #: whatever the gateway said, kept verbatim for disputes
    gateway_response = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        verbose_name = "پرداخت"
        verbose_name_plural = "پرداخت‌ها"

    def __str__(self) -> str:
        return f"{self.invoice_number or self.pk} — {self.amount_toman:,} تومان ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._new_invoice_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _new_invoice_number() -> str:
        """Date-prefixed so a human can place it, random so it cannot collide.

        An earlier version used the clock down to the second, which collided
        the moment two customers paid within the same second — and two
        customers paying at once is the normal case on a launch day, not an
        edge case.

        Ambiguous characters are left out of the alphabet: these numbers get
        read aloud on support calls.
        """
        import secrets

        alphabet = "ACDEFGHJKLMNPQRTUVWXY34679"
        stamp = timezone.now().strftime("%y%m%d")
        suffix = "".join(secrets.choice(alphabet) for _ in range(6))
        return f"UM-{stamp}-{suffix}"

    @property
    def is_final(self) -> bool:
        return self.status in (
            self.Status.PAID, self.Status.FAILED,
            self.Status.ABANDONED, self.Status.REFUNDED,
        )


class BillingEvent(TimeStampedModel):
    """Append-only record of everything that changed a subscription.

    Billing disputes are answered from history, not from current state. When a
    customer says "I never upgraded", the useful answer is a row saying when it
    happened, who did it, and what it was before.

    Nothing here is ever updated or deleted.
    """

    class Kind(models.TextChoices):
        SUBSCRIPTION_CREATED = "SUB_CREATED", "ایجاد اشتراک"
        PLAN_CHANGED = "PLAN_CHANGED", "تغییر پلن"
        PAYMENT_STARTED = "PAY_STARTED", "شروع پرداخت"
        PAYMENT_PAID = "PAY_PAID", "پرداخت موفق"
        PAYMENT_FAILED = "PAY_FAILED", "پرداخت ناموفق"
        PAYMENT_REFUNDED = "PAY_REFUNDED", "بازگشت وجه"
        ACTIVATED = "ACTIVATED", "فعال‌سازی"
        RENEWED = "RENEWED", "تمدید"
        CANCELLED = "CANCELLED", "لغو"
        EXPIRED = "EXPIRED", "انقضا"
        GRACE_STARTED = "GRACE", "شروع مهلت ارفاقی"
        CREDIT_REFUNDED = "CREDIT_BACK", "برگشت اعتبار (کیفیت)"

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="billing_events"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    #: free-form, written for a person reading the history
    summary = models.CharField(max_length=300)
    #: who did it; null means the system did
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="billing_events",
    )
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events",
    )
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "-created_at"])]
        verbose_name = "رویداد صورتحساب"
        verbose_name_plural = "رویدادهای صورتحساب"

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.summary}"

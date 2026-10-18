"""Payment tests.

Weighted toward the ways money code goes wrong rather than the happy path:
double callbacks, amount tampering, a gateway that says paid for the wrong
sum, and activation arithmetic that throws away days the customer paid for.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.stores.models import Store

from .models import Plan, Subscription
from .payment_models import BillingEvent, Payment
from .payment_services import PaymentError, confirm_manual, refund, start_payment, verify_payment
from .payments import available_providers, get_provider
from .payments.base import VerifyResult

CALLBACK = "http://testserver/api/v1/payments/callback/"


@override_settings(
    DEBUG=True,
    UPMARKET_PAYMENT={
        "PERIOD_DAYS": 30,
        "GRACE_DAYS": 3,
        "CALLBACK_BASE": "http://testserver",
        "PANEL_URL": "http://panel",
        "MANUAL_ACCOUNT_INFO": "IR-TEST-ACCOUNT",
        "ZARINPAL_MERCHANT_ID": "",
    },
)
class PaymentFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("shopkeeper", password="x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه تست")
        self.plan = Plan.objects.create(
            slug="pro", name="حرفه‌ای", price_toman=1_490_000, is_public=True
        )
        self.cheap = Plan.objects.create(
            slug="start", name="استارت", price_toman=690_000, is_public=True
        )

    def _start(self, plan=None):
        return start_payment(
            store=self.store, plan=plan or self.plan,
            provider_key="sandbox", callback_url=CALLBACK, actor=self.user,
        )

    # ------------------------------------------------------------- basics

    def test_start_creates_pending_payment_with_plan_price(self):
        payment, url = self._start()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.amount_toman, self.plan.price_toman)
        self.assertTrue(payment.invoice_number)
        self.assertIn("Authority=", url)

    def test_client_cannot_choose_the_amount(self):
        """Price is read from the plan row, never proposed by the caller."""
        payment, _ = self._start()
        self.assertEqual(payment.amount_toman, 1_490_000)

    def test_free_plan_cannot_be_paid_for(self):
        free = Plan.objects.create(slug="free", name="رایگان", price_toman=0, is_public=True)
        with self.assertRaises(PaymentError):
            self._start(free)

    def test_successful_payment_activates_subscription(self):
        payment, _ = self._start()
        verified = verify_payment(token=payment.token)

        self.assertEqual(verified.status, Payment.Status.PAID)
        self.assertTrue(verified.reference)

        sub = Subscription.objects.get(store=self.store)
        self.assertEqual(sub.plan, self.plan)
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertTrue(sub.is_usable)

    # ------------------------------------------------------ idempotency

    def test_verifying_twice_does_not_extend_twice(self):
        """Gateways retry and users refresh the callback. Once is once."""
        payment, _ = self._start()
        verify_payment(token=payment.token)
        first_end = Subscription.objects.get(store=self.store).period_end

        verify_payment(token=payment.token)
        second_end = Subscription.objects.get(store=self.store).period_end

        self.assertEqual(first_end, second_end)
        self.assertEqual(
            BillingEvent.objects.filter(
                store=self.store, kind=BillingEvent.Kind.PAYMENT_PAID
            ).count(),
            1,
        )

    def test_unknown_token_is_rejected(self):
        with self.assertRaises(PaymentError):
            verify_payment(token="never-existed")

    # ---------------------------------------------------------- failure

    def test_declined_payment_does_not_activate(self):
        payment, _ = self._start()
        # the sandbox treats a -fail suffix as a decline
        payment.token = payment.token + "-fail"
        payment.save(update_fields=["token"])

        verified = verify_payment(token=payment.token)
        self.assertEqual(verified.status, Payment.Status.FAILED)
        self.assertFalse(Subscription.objects.filter(store=self.store).exists())

    def test_amount_mismatch_is_refused_even_when_gateway_says_paid(self):
        """A gateway confirming a different sum is never quietly accepted."""
        payment, _ = self._start()

        wrong = VerifyResult(paid=True, reference="X1", amount=1, raw={}, message="")
        with patch(
            "apps.billing.payments.sandbox.SandboxProvider.verify", return_value=wrong
        ):
            verified = verify_payment(token=payment.token)

        self.assertEqual(verified.status, Payment.Status.FAILED)
        self.assertIn("مبلغ", verified.error)
        self.assertFalse(Subscription.objects.filter(store=self.store).exists())

    def test_failed_payment_is_not_retried_into_success(self):
        payment, _ = self._start()
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        again = verify_payment(token=payment.token)
        self.assertEqual(again.status, Payment.Status.FAILED)

    # -------------------------------------------------------- activation

    def test_renewing_early_extends_rather_than_truncates(self):
        """Paying again mid-period must not throw away days already bought."""
        payment, _ = self._start()
        verify_payment(token=payment.token)
        first_end = Subscription.objects.get(store=self.store).period_end

        second, _ = self._start()
        verify_payment(token=second.token)
        second_end = Subscription.objects.get(store=self.store).period_end

        self.assertGreater(second_end, first_end)
        self.assertAlmostEqual(
            (second_end - first_end).days, 30, delta=1
        )

    def test_upgrade_records_the_plan_change(self):
        first, _ = self._start(self.cheap)
        verify_payment(token=first.token)
        second, _ = self._start(self.plan)
        verify_payment(token=second.token)

        self.assertEqual(Subscription.objects.get(store=self.store).plan, self.plan)
        self.assertTrue(
            BillingEvent.objects.filter(
                store=self.store, kind=BillingEvent.Kind.PLAN_CHANGED
            ).exists()
        )

    # ------------------------------------------------------------- grace

    def test_expired_subscription_still_works_during_grace(self):
        payment, _ = self._start()
        verify_payment(token=payment.token)
        sub = Subscription.objects.get(store=self.store)

        sub.period_end = timezone.now() - timedelta(days=1)
        sub.save(update_fields=["period_end"])
        sub.refresh_from_db()

        self.assertTrue(sub.in_grace)
        self.assertTrue(sub.is_usable)

    def test_grace_eventually_runs_out(self):
        payment, _ = self._start()
        verify_payment(token=payment.token)
        sub = Subscription.objects.get(store=self.store)

        sub.period_end = timezone.now() - timedelta(days=10)
        sub.save(update_fields=["period_end"])
        sub.refresh_from_db()

        self.assertFalse(sub.in_grace)
        self.assertFalse(sub.is_usable)

    def test_a_trial_that_lapses_gets_no_grace(self):
        """Grace is for customers who have paid before, not for free trials."""
        sub = Subscription.objects.create(
            store=self.store, plan=self.plan,
            status=Subscription.Status.TRIALING,
            period_end=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(sub.is_usable)

    # ------------------------------------------------------------ manual

    def test_manual_transfer_never_self_confirms(self):
        payment, url = start_payment(
            store=self.store, plan=self.plan, provider_key="manual",
            callback_url=CALLBACK, actor=self.user,
        )
        self.assertEqual(url, "")

        verified = verify_payment(token=payment.token)
        self.assertNotEqual(verified.status, Payment.Status.PAID)
        self.assertFalse(Subscription.objects.filter(store=self.store).exists())

    def test_manual_transfer_activates_when_a_human_confirms(self):
        payment, _ = start_payment(
            store=self.store, plan=self.plan, provider_key="manual",
            callback_url=CALLBACK, actor=self.user,
        )
        staff = User.objects.create_user("admin2", password="x", is_staff=True)
        confirm_manual(payment, actor=staff, reference="BANK-123")

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(payment.confirmed_by, staff)
        self.assertTrue(Subscription.objects.get(store=self.store).is_usable)

    # ------------------------------------------------------------ refund

    def test_refund_requires_a_paid_payment(self):
        payment, _ = self._start()
        with self.assertRaises(PaymentError):
            refund(payment, actor=self.user, reason="nope")

    def test_refund_is_recorded_with_a_reason(self):
        payment, _ = self._start()
        # verify_payment returns the fresh row; the local one is now stale
        paid = verify_payment(token=payment.token)
        refund(paid, actor=self.user, reason="خروجی بی‌کیفیت")

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertTrue(
            BillingEvent.objects.filter(
                store=self.store, kind=BillingEvent.Kind.PAYMENT_REFUNDED
            ).exists()
        )

    # ----------------------------------------------------------- history

    def test_first_payment_on_a_trial_reads_as_activation_not_renewal(self):
        """The audit trail is read during disputes; calling a first payment a
        renewal there is simply wrong."""
        Subscription.objects.create(
            store=self.store, plan=self.cheap,
            status=Subscription.Status.TRIALING,
            period_end=timezone.now() + timedelta(days=5),
        )
        payment, _ = self._start()
        verify_payment(token=payment.token)

        kinds = list(
            BillingEvent.objects.filter(store=self.store).values_list("kind", flat=True)
        )
        self.assertIn(BillingEvent.Kind.ACTIVATED, kinds)
        self.assertNotIn(BillingEvent.Kind.RENEWED, kinds)

    def test_second_payment_reads_as_renewal(self):
        first, _ = self._start()
        verify_payment(token=first.token)
        second, _ = self._start()
        verify_payment(token=second.token)

        kinds = list(
            BillingEvent.objects.filter(store=self.store).values_list("kind", flat=True)
        )
        self.assertIn(BillingEvent.Kind.ACTIVATED, kinds)
        self.assertIn(BillingEvent.Kind.RENEWED, kinds)

    def test_paying_early_keeps_the_days_already_bought(self):
        """Extending must not silently reset the clock."""
        Subscription.objects.create(
            store=self.store, plan=self.cheap,
            status=Subscription.Status.TRIALING,
            period_end=timezone.now() + timedelta(days=10),
        )
        payment, _ = self._start()
        verify_payment(token=payment.token)

        sub = Subscription.objects.get(store=self.store)
        # 10 remaining trial days + a fresh 30-day period
        self.assertGreaterEqual(sub.days_left, 38)

    def test_every_step_leaves_an_audit_trail(self):
        payment, _ = self._start()
        verify_payment(token=payment.token)
        kinds = set(
            BillingEvent.objects.filter(store=self.store).values_list("kind", flat=True)
        )
        self.assertIn(BillingEvent.Kind.PAYMENT_STARTED, kinds)
        self.assertIn(BillingEvent.Kind.PAYMENT_PAID, kinds)
        self.assertIn(BillingEvent.Kind.ACTIVATED, kinds)


@override_settings(DEBUG=False, UPMARKET_PAYMENT={"MANUAL_ACCOUNT_INFO": "IR-X"})
class ProviderAvailabilityTests(TestCase):
    def test_sandbox_is_not_offered_in_production(self):
        """A test gateway reachable in production is a way to get free plans."""
        keys = {p.key for p in available_providers()}
        self.assertNotIn("sandbox", keys)

    def test_unconfigured_gateway_is_refused_rather_than_half_working(self):
        with self.assertRaises(PaymentError):
            get_provider("zarinpal")

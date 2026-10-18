"""Lead → Customer → Onboarding → Support → Retention, as one thing. Phase 26.

The two properties this page is built on, and what breaks without them.

**Stages move backwards.** A paying customer who stopped using the product is
not "converted" — they are the most important row on the page. A funnel that
only counts forwards shows them as a success right up until they cancel.

**Risk is evidence with a date, never a score.** Every test below asserts on the
*sentence*, not on a number, because the sentence is what a founder can act on.
There is deliberately no churn probability: a model that produced one would need
history we do not have, and a number between 0 and 1 invites you to sort by it
and stop reading the reasons.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Plan, Subscription
from apps.content.models import GeneratedImage
from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store

from . import crm
from .gtm import record_signup
from .models import Lead


class StageTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("crm-owner", password="x")
        self.plan = Plan.objects.create(
            slug="crm-pro", name="حرفه‌ای", price_toman=500_000,
        )

    def _store(self, name="فروشگاه", *, products=0, outputs=0, days_old=1,
               quiet_days=0, status=None):
        store = Store.objects.create(owner=self.owner, name=name)
        Store.objects.filter(pk=store.pk).update(
            created_at=timezone.now() - timedelta(days=days_old),
        )
        for index in range(products):
            product = Product.objects.create(
                store=store, name=f"محصول {index}", price=1000,
            )
        for index in range(outputs):
            GeneratedImage.objects.create(
                store=store, product=product,
                kind=GeneratedImage.Kind.POSTER, image="x.png",
            )
        if quiet_days:
            job = Job.objects.create(store=store, type=Job.Type.CAPTION_GENERATION)
            Job.objects.filter(pk=job.pk).update(
                created_at=timezone.now() - timedelta(days=quiet_days),
            )
        if status is not None:
            Subscription.objects.update_or_create(
                store=store,
                defaults={
                    "plan": self.plan,
                    "status": status,
                    "period_end": timezone.now() + timedelta(days=30),
                },
            )
        return store

    def _row(self, store):
        return next(r for r in crm.customers() if r.store_id == store.pk)

    def test_an_account_with_no_products_is_only_signed_up(self):
        store = self._store()
        self.assertEqual(self._row(store).stage, crm.Stage.SIGNED_UP)

    def test_products_but_nothing_made_is_onboarding(self):
        store = self._store(products=2)
        self.assertEqual(self._row(store).stage, crm.Stage.ONBOARDING)

    def test_making_things_is_active(self):
        store = self._store(products=1, outputs=4)
        self.assertEqual(self._row(store).stage, crm.Stage.ACTIVE)

    def test_an_active_customer_who_went_quiet_moves_backwards(self):
        """The whole reason to look at this page. A funnel that only counts
        forwards shows them as a success right up until they cancel."""
        store = self._store(products=1, outputs=4, quiet_days=20)
        self.assertEqual(self._row(store).stage, crm.Stage.SLIPPING)

    def test_a_cancelled_subscription_is_lapsed(self):
        store = self._store(
            products=1, outputs=4, status=Subscription.Status.CANCELLED,
        )
        self.assertEqual(self._row(store).stage, crm.Stage.LAPSED)

    def test_every_stage_has_a_persian_title(self):
        for stage in crm.ORDER:
            self.assertTrue(crm.TITLES[stage])


class RiskTests(StageTests):
    def test_a_paying_customer_who_got_nothing_is_the_loudest_risk(self):
        """They are paying and have not yet received what they paid for, and it
        is the easiest thing on the page to miss."""
        store = self._store(products=1, status=Subscription.Status.ACTIVE)
        row = self._row(store)
        keys = {r.key for r in row.risks}
        self.assertIn("not_activated", keys)
        self.assertEqual(row.worst, "high")

    def test_a_trial_about_to_end_is_flagged_as_a_trial(self):
        store = self._store(products=1, outputs=4)
        Subscription.objects.update_or_create(
            store=store,
            defaults={
                "plan": self.plan,
                "status": Subscription.Status.TRIALING,
                "period_end": timezone.now() + timedelta(days=1),
            },
        )
        risk = next(r for r in self._row(store).risks if r.key == "ending")
        self.assertIn("آزمایشی", risk.what)
        self.assertEqual(risk.level, "high")

    def test_a_paid_subscription_about_to_end_is_worded_differently(self):
        store = self._store(products=1, outputs=4)
        Subscription.objects.update_or_create(
            store=store,
            defaults={
                "plan": self.plan,
                "status": Subscription.Status.ACTIVE,
                "period_end": timezone.now() + timedelta(days=1),
            },
        )
        risk = next(r for r in self._row(store).risks if r.key == "ending")
        self.assertIn("اشتراک", risk.what)

    def test_going_quiet_matters_more_when_they_are_paying(self):
        free = self._store("رایگان", products=1, outputs=4, quiet_days=20)
        paid = self._store(
            "پولی", products=1, outputs=4, quiet_days=20,
            status=Subscription.Status.ACTIVE,
        )
        free_risk = next(r for r in self._row(free).risks if r.key == "quiet")
        paid_risk = next(r for r in self._row(paid).risks if r.key == "quiet")
        self.assertEqual(free_risk.level, "watch")
        self.assertEqual(paid_risk.level, "high")

    def test_every_risk_carries_a_number_of_days(self):
        """Evidence with a date. "at risk" is not something anyone can act on."""
        store = self._store(products=1, outputs=4, quiet_days=20)
        for risk in self._row(store).risks:
            self.assertTrue(any(ch.isdigit() for ch in risk.what), risk.what)

    def test_a_healthy_customer_has_no_risks(self):
        store = self._store(products=1, outputs=5)
        self.assertEqual(self._row(store).worst, "ok")

    def test_open_tickets_are_a_watch_not_an_alarm(self):
        """An inbox where everything is urgent is one nobody reads."""
        from apps.customers.models import SupportTicket

        store = self._store(products=1, outputs=5)
        SupportTicket.objects.create(store=store, subject="مشکل")
        row = self._row(store)
        self.assertEqual(row.open_tickets, 1)
        self.assertEqual(row.worst, "watch")

    def test_a_resolved_ticket_is_not_counted(self):
        from apps.customers.models import SupportTicket

        store = self._store(products=1, outputs=5)
        SupportTicket.objects.create(
            store=store, subject="حل شد", status=SupportTicket.Status.RESOLVED,
        )
        self.assertEqual(self._row(store).open_tickets, 0)


class LeadTests(TestCase):
    def test_a_lead_nobody_answered_is_flagged(self):
        """The cheapest customer we will ever lose."""
        lead = Lead.objects.create(
            name="مهدی", email="m@x.ir", message="سؤال", status=Lead.Status.NEW,
        )
        Lead.objects.filter(pk=lead.pk).update(
            created_at=timezone.now() - timedelta(days=4),
        )
        row = crm.leads()[0]
        self.assertTrue(row["unanswered"])
        self.assertEqual(row["days_waiting"], 4)

    def test_a_lead_answered_today_is_not(self):
        Lead.objects.create(
            name="مهدی", email="m@x.ir", message="سؤال",
            status=Lead.Status.CONTACTED,
        )
        self.assertFalse(crm.leads()[0]["unanswered"])

    def test_spam_is_not_shown(self):
        Lead.objects.create(
            name="bot", email="b@x.ir", message="spam", status=Lead.Status.SPAM,
        )
        self.assertEqual(crm.leads(), [])


class BoardTests(StageTests):
    def test_the_board_answers_what_to_do_today(self):
        """The only reason to open this page."""
        self._store("در خطر", products=1, status=Subscription.Status.ACTIVE)
        lead = Lead.objects.create(
            name="مهدی", email="m@x.ir", message="سؤال", status=Lead.Status.NEW,
        )
        Lead.objects.filter(pk=lead.pk).update(
            created_at=timezone.now() - timedelta(days=5),
        )

        board = crm.board()
        self.assertTrue(board["today"]["at_risk"])
        self.assertTrue(board["today"]["unanswered_leads"])

    def test_riskiest_customers_come_first(self):
        self._store("سالم", products=1, outputs=5)
        self._store("خطر", products=1, status=Subscription.Status.ACTIVE)
        self.assertEqual(crm.customers()[0].name, "خطر")

    def test_the_channel_travels_with_the_customer(self):
        store = self._store("از تبلیغات", products=1, outputs=5)
        record_signup(store, utm={"utm_medium": "cpc"})
        self.assertEqual(self._row(store).channel, "تبلیغات")

    def test_the_page_says_why_there_is_no_churn_score(self):
        """The absence of a number is a design choice people would otherwise
        read as an oversight."""
        self.assertIn("احتمال ریزش", crm.board()["note"])

    def test_it_runs_on_an_empty_database(self):
        Store.objects.all().delete()
        board = crm.board()
        self.assertEqual(board["totals"]["customers"], 0)
        self.assertEqual(len(board["stages"]), len(crm.ORDER))


class CRMAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("crm-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")

    def test_the_crm_is_staff_only(self):
        """It spans every customer and names the ones about to leave."""
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/v1/marketing/crm/").status_code, 403)

    def test_staff_can_read_it(self):
        staff = User.objects.create_user("crm-staff", password="x", is_staff=True)
        self.client.force_login(staff)
        body = self.client.get("/api/v1/marketing/crm/").json()
        self.assertIn("stages", body)
        self.assertIn("today", body)

    def test_it_is_read_only(self):
        """A CRM that quietly changes subscription state is a CRM that fights
        with billing."""
        staff = User.objects.create_user("crm-staff2", password="x", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(
            "/api/v1/marketing/crm/", {}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)

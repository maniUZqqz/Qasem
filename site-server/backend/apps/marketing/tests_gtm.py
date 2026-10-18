"""GTM: attribution that does not move, and payouts nothing automatic touches.

The two properties these tests exist to hold down:

**History does not change.** A store that arrived through a referral in March is
still a referral after that code is deleted. Several tests below delete or
rename things and check the attribution says what it always said — because a
report that rewrites its own past is one nobody can act on.

**Money is never moved by an event.** `record_payment` writes down what is
owed; a person pays it. There is no code path here from "someone signed up" to
"someone got paid", and that is deliberate: an automatic payout on a signup is
a fraud surface whose remedy is clawing money back from customers.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Plan
from apps.stores.models import Store

from . import intelligence
from .gtm import (
    Affiliate,
    Attribution,
    DiscountCode,
    ReferralCode,
    Reward,
    make_code,
    record_payment,
    record_signup,
    redeem,
    resolve_code,
)


class CodeTests(TestCase):
    def test_codes_avoid_characters_people_mistype(self):
        """Read over the phone and written by hand. 0/O and 1/I are the two
        pairs that generate support tickets."""
        code = make_code(length=200)
        for confusable in "01OIl":
            self.assertNotIn(confusable, code)

    def test_two_codes_are_never_the_same(self):
        self.assertNotEqual(make_code(), make_code())

    def test_a_code_is_generated_when_none_is_given(self):
        owner = User.objects.create_user("code-owner", password="x")
        self.assertTrue(ReferralCode.objects.create(owner=owner).code)

    def test_discount_codes_are_stored_upper_case(self):
        """So "welcome10" and "WELCOME10" are the same code, which is what a
        customer typing it assumes."""
        code = DiscountCode.objects.create(code="welcome10", value=10)
        self.assertEqual(code.code, "WELCOME10")


class DiscountTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(slug="pro", name="حرفه‌ای", price_toman=500_000)
        self.other = Plan.objects.create(slug="lite", name="سبک", price_toman=100_000)
        owner = User.objects.create_user("disc-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه تخفیف")
        self.code = DiscountCode.objects.create(code="OFF20", value=20)

    def test_a_live_code_is_usable(self):
        self.assertIsNone(self.code.unusable_because(plan=self.plan, store=self.store))

    def test_each_refusal_says_which_one_it_is(self):
        """"Expired" and "not for this plan" lead to completely different next
        actions; «کد نامعتبر است» for both sends someone to support."""
        self.code.ends_at = timezone.now() - timedelta(days=1)
        self.assertIn("منقضی", self.code.unusable_because())

        self.code.ends_at = None
        self.code.starts_at = timezone.now() + timedelta(days=1)
        self.assertIn("شروع نشده", self.code.unusable_because())

        self.code.starts_at = None
        self.code.is_active = False
        self.assertIn("فعال نیست", self.code.unusable_because())

    def test_a_code_limited_to_one_plan_is_refused_on_another(self):
        self.code.save()
        self.code.plans.add(self.plan)
        self.assertIsNone(self.code.unusable_because(plan=self.plan))
        self.assertIn("حرفه‌ای", self.code.unusable_because(plan=self.other))

    def test_a_full_code_is_refused(self):
        self.code.max_uses = 2
        self.code.used_count = 2
        self.assertIn("ظرفیت", self.code.unusable_because())

    def test_the_same_store_cannot_use_a_code_twice(self):
        redeem(self.code, self.store, self.plan, 500_000)
        self.assertIn("قبلاً", self.code.unusable_because(store=self.store))

    def test_a_percentage_comes_off_correctly(self):
        self.assertEqual(self.code.discount_on(500_000), 100_000)

    def test_a_fixed_amount_never_exceeds_the_price(self):
        """A 200,000 code on a 100,000 plan is free, not a refund."""
        big = DiscountCode.objects.create(
            code="BIG", kind=DiscountCode.Kind.AMOUNT, value=200_000,
        )
        self.assertEqual(big.discount_on(100_000), 100_000)

    def test_over_a_hundred_percent_is_still_only_free(self):
        silly = DiscountCode.objects.create(code="OOPS", value=250)
        self.assertEqual(silly.discount_on(100_000), 100_000)

    def test_redeeming_counts_against_the_limit(self):
        redeem(self.code, self.store, self.plan, 500_000)
        self.code.refresh_from_db()
        self.assertEqual(self.code.used_count, 1)


class ResolveTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("res-owner", password="x")

    def test_one_box_recognises_all_three_kinds(self):
        """Making a customer know whether they hold a referral, an affiliate or
        a discount code is asking them to understand our business model."""
        referral = ReferralCode.objects.create(owner=self.owner, code="REF-AAA")
        affiliate = Affiliate.objects.create(
            name="شریک", code="AFF-BBB", status=Affiliate.Status.ACTIVE,
        )
        discount = DiscountCode.objects.create(code="OFF10", value=10)

        self.assertEqual(resolve_code("REF-AAA"), ("referral", referral))
        self.assertEqual(resolve_code("AFF-BBB"), ("affiliate", affiliate))
        self.assertEqual(resolve_code("OFF10"), ("discount", discount))

    def test_case_and_spaces_do_not_matter(self):
        DiscountCode.objects.create(code="OFF10", value=10)
        self.assertEqual(resolve_code("  off10 ")[0], "discount")

    def test_an_unknown_code_is_not_an_error(self):
        self.assertEqual(resolve_code("NOPE"), ("unknown", None))

    def test_an_empty_code_is_its_own_answer(self):
        self.assertEqual(resolve_code("")[0], "none")

    def test_a_paused_affiliate_code_is_not_resolved(self):
        Affiliate.objects.create(
            name="شریک", code="AFF-OFF", status=Affiliate.Status.PAUSED,
        )
        self.assertEqual(resolve_code("AFF-OFF")[0], "unknown")


class AttributionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("attr-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه منبع")

    def test_a_signup_with_no_code_is_direct(self):
        row = record_signup(self.store)
        self.assertEqual(row.channel, Attribution.Channel.DIRECT)

    def test_a_referral_code_sets_the_channel(self):
        code = ReferralCode.objects.create(owner=self.owner, code="REF-XYZ")
        row = record_signup(self.store, code="REF-XYZ")
        self.assertEqual(row.channel, Attribution.Channel.REFERRAL)
        self.assertEqual(row.referral, code)

    def test_utm_decides_the_channel_when_there_is_no_code(self):
        row = record_signup(self.store, utm={"utm_medium": "cpc"})
        self.assertEqual(row.channel, Attribution.Channel.ADS)

    def test_a_social_source_is_recognised(self):
        row = record_signup(self.store, utm={"utm_source": "instagram"})
        self.assertEqual(row.channel, Attribution.Channel.SOCIAL)

    def test_arriving_from_the_blog_counts_as_content(self):
        row = record_signup(self.store, referrer="https://upmarket.ir/blog/x")
        self.assertEqual(row.channel, Attribution.Channel.CONTENT)

    def test_signing_up_twice_does_not_create_two_attributions(self):
        """Signup can be retried, and two rows would let one shop be counted
        for two channels."""
        first = record_signup(self.store, code="")
        second = record_signup(self.store, utm={"utm_medium": "cpc"})
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.channel, Attribution.Channel.DIRECT)

    def test_the_campaign_name_survives_the_campaign_being_renamed(self):
        """A copy, not a link. A report that re-derives attribution rewrites
        its own history every time somebody tidies up."""
        row = record_signup(self.store, utm={"utm_campaign": "nowruz-1404"})
        self.assertEqual(row.campaign, "nowruz-1404")

    def test_history_survives_the_referral_code_being_deleted(self):
        ReferralCode.objects.create(owner=self.owner, code="REF-GONE")
        row = record_signup(self.store, code="REF-GONE")
        ReferralCode.objects.all().delete()
        row.refresh_from_db()
        self.assertEqual(row.channel, Attribution.Channel.REFERRAL)


class PayoutTests(TestCase):
    def setUp(self):
        self.referrer = User.objects.create_user("pay-referrer", password="x")
        self.owner = User.objects.create_user("pay-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه پرداخت")

    def test_a_referral_reward_is_recorded_when_they_pay_not_when_they_sign_up(self):
        """Counting signups rewards whoever can create the most accounts, which
        is the failure mode of every referral programme."""
        ReferralCode.objects.create(
            owner=self.referrer, code="REF-PAY", reward_toman=100_000,
        )
        record_signup(self.store, code="REF-PAY")
        self.assertEqual(Reward.objects.count(), 0)

        record_payment(self.store, 500_000)
        self.assertEqual(Reward.objects.count(), 1)
        self.assertEqual(Reward.objects.first().amount_toman, 100_000)

    def test_a_referral_reward_is_paid_once_however_often_they_renew(self):
        ReferralCode.objects.create(
            owner=self.referrer, code="REF-ONCE", reward_toman=100_000,
        )
        record_signup(self.store, code="REF-ONCE")
        record_payment(self.store, 500_000)
        record_payment(self.store, 500_000)
        self.assertEqual(
            Reward.objects.filter(kind=Reward.Kind.REFERRAL).count(), 1,
        )

    def test_commission_accrues_on_every_payment_inside_the_window(self):
        Affiliate.objects.create(
            name="شریک", code="AFF-PAY", status=Affiliate.Status.ACTIVE,
            commission_percent=20,
        )
        record_signup(self.store, code="AFF-PAY")
        record_payment(self.store, 500_000)
        record_payment(self.store, 500_000)
        rewards = Reward.objects.filter(kind=Reward.Kind.COMMISSION)
        self.assertEqual(rewards.count(), 2)
        self.assertEqual(rewards.first().amount_toman, 100_000)

    def test_commission_stops_at_the_end_of_its_window(self):
        """Open-ended commission on a customer who stayed four years is a
        liability nobody modelled when signing."""
        Affiliate.objects.create(
            name="شریک", code="AFF-OLD", status=Affiliate.Status.ACTIVE,
            commission_months=1,
        )
        attribution = record_signup(self.store, code="AFF-OLD")
        Attribution.objects.filter(pk=attribution.pk).update(
            created_at=timezone.now() - timedelta(days=200),
        )
        record_payment(self.store, 500_000)
        self.assertEqual(
            Reward.objects.filter(kind=Reward.Kind.COMMISSION).count(), 0,
        )

    def test_a_banned_affiliate_earns_nothing(self):
        Affiliate.objects.create(
            name="شریک", code="AFF-BAD", status=Affiliate.Status.ACTIVE,
        )
        record_signup(self.store, code="AFF-BAD")
        Affiliate.objects.update(status=Affiliate.Status.BANNED)
        record_payment(self.store, 500_000)
        self.assertEqual(Reward.objects.count(), 0)

    def test_a_reward_starts_unpaid_and_nothing_automatic_pays_it(self):
        """The whole reason Reward is a row rather than a transfer."""
        ReferralCode.objects.create(
            owner=self.referrer, code="REF-Q", reward_toman=50_000,
        )
        record_signup(self.store, code="REF-Q")
        reward = record_payment(self.store, 500_000)[0]
        self.assertEqual(reward.state, Reward.State.PENDING)
        self.assertIsNone(reward.paid_at)

    def test_paying_records_who_did_it(self):
        ReferralCode.objects.create(
            owner=self.referrer, code="REF-W", reward_toman=50_000,
        )
        record_signup(self.store, code="REF-W")
        reward = record_payment(self.store, 500_000)[0]
        staff = User.objects.create_user("pay-staff", password="x", is_staff=True)
        reward.pay(staff)
        self.assertEqual(reward.paid_by, staff)
        self.assertIsNotNone(reward.paid_at)

    def test_a_payment_from_an_unattributed_store_is_not_an_error(self):
        self.assertEqual(record_payment(self.store, 500_000), [])

    def test_every_reward_says_why_it_exists(self):
        ReferralCode.objects.create(
            owner=self.referrer, code="REF-E", reward_toman=50_000,
        )
        record_signup(self.store, code="REF-E")
        self.assertTrue(record_payment(self.store, 500_000)[0].because)


class IntelligenceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("intel-owner", password="x")

    def _store(self, name, **signup):
        store = Store.objects.create(owner=self.owner, name=name)
        return store, record_signup(store, **signup)

    def test_signups_and_paying_customers_are_counted_separately(self):
        """A dashboard that ranks channels by signup makes the cheapest traffic
        look like the best traffic."""
        store, _ = self._store("الف", utm={"utm_medium": "cpc"})
        self._store("ب", utm={"utm_medium": "cpc"})
        record_payment(store, 500_000)

        ads = next(
            c for c in intelligence.acquisition()["channels"] if c["channel"] == "ADS"
        )
        self.assertEqual(ads["signups"], 2)
        self.assertEqual(ads["paying"], 1)
        self.assertEqual(ads["conversion"], 50.0)

    def test_only_money_we_have_seen_is_counted(self):
        """No projected lifetime value. Assumptions end up quoted as facts."""
        store, _ = self._store("ج", utm={"utm_medium": "cpc"})
        record_payment(store, 400_000)
        self.assertEqual(intelligence.acquisition()["revenue_toman"], 400_000)

    def test_a_channel_with_no_signups_has_no_conversion_rate(self):
        """None, not 0٪. Zero says it converts badly rather than that nobody
        came."""
        self.assertIsNone(intelligence._rate(0, 0))

    def test_unnamed_traffic_is_left_out_of_the_campaign_report(self):
        """A campaign report whose top row is everything that was not a
        campaign answers a different question than it was asked."""
        self._store("د")
        self._store("ه", utm={"utm_campaign": "nowruz"})
        rows = intelligence.campaigns()
        self.assertEqual([r["campaign"] for r in rows], ["nowruz"])

    def test_the_report_states_what_it_cannot_know(self):
        """Better a stated gap than a number someone quotes in a meeting."""
        self.assertIn("هزینه", intelligence.report()["caveat"])

    def test_the_report_runs_on_an_empty_database(self):
        report = intelligence.report()
        self.assertEqual(report["acquisition"]["signups"], 0)
        self.assertIsNone(report["acquisition"]["conversion"])


class GTMAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("gtm-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه GTM")
        self.client.force_login(self.owner)

    def _check(self, code):
        return self.client.post(
            "/api/v1/codes/check/", {"code": code}, content_type="application/json",
        ).json()

    def test_an_unknown_code_is_reported_as_unknown(self):
        self.assertFalse(self._check("NOPE")["valid"])

    def test_a_disabled_code_looks_the_same_as_a_nonexistent_one(self):
        """The difference tells someone whether they guessed a real prefix."""
        ReferralCode.objects.create(
            owner=self.owner, code="REF-OFF", is_active=False,
        )
        self.assertEqual(self._check("REF-OFF"), self._check("REF-NOSUCH"))

    def test_a_referral_code_never_reveals_who_owns_it(self):
        """A signup form is not a place to learn who our customers are."""
        ReferralCode.objects.create(
            owner=self.owner, code="REF-OK", friend_discount_percent=10,
        )
        answer = self._check("REF-OK")
        self.assertTrue(answer["valid"])
        self.assertNotIn("gtm-api", str(answer))
        self.assertNotIn("فروشگاه GTM", str(answer))

    def test_checking_a_code_needs_no_account(self):
        self.client.logout()
        self.assertEqual(
            self.client.post(
                "/api/v1/codes/check/", {"code": "X"}, content_type="application/json",
            ).status_code,
            200,
        )

    def test_a_shop_can_make_its_own_referral_code(self):
        response = self.client.post(f"/api/v1/stores/{self.store.pk}/referral/")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["code"])

    def test_asking_twice_returns_the_same_code(self):
        first = self.client.post(f"/api/v1/stores/{self.store.pk}/referral/").json()
        second = self.client.post(f"/api/v1/stores/{self.store.pk}/referral/").json()
        self.assertEqual(first["code"], second["code"])

    def test_the_report_is_staff_only(self):
        """It spans every customer, so it is ours, not any one shop's."""
        self.assertEqual(self.client.get("/api/v1/marketing/report/").status_code, 403)

    def test_a_staff_user_can_read_the_report(self):
        staff = User.objects.create_user("gtm-staff", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/api/v1/marketing/report/").status_code, 200)

    def test_a_shop_cannot_edit_its_own_attribution(self):
        """A customer who could change their attribution could change what we
        owe somebody."""
        record_signup(self.store, utm={"utm_medium": "cpc"})
        response = self.client.post(
            f"/api/v1/stores/{self.store.pk}/attribution/",
            {"channel": "REFERRAL"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)

    def test_a_stranger_sees_no_referral_code(self):
        stranger = User.objects.create_user("gtm-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(
            self.client.get(f"/api/v1/stores/{self.store.pk}/referral/").status_code,
            404,
        )


class ReferralOwnershipTests(TestCase):
    """A shop has one referral code, not one per colleague.

    Keying the code on whoever pressed the button gave a shop with two admins
    two codes, split its referral count between them, and paid the reward to
    the faster clicker rather than to the account that pays the bills.
    """

    def setUp(self):
        from apps.stores.models import Membership

        self.owner = User.objects.create_user("ref-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه دو مدیر")
        self.admin = User.objects.create_user("ref-admin", password="x")
        Membership.objects.create(
            store=self.store, user=self.admin, role=Membership.Role.ADMIN,
        )
        self.url = f"/api/v1/stores/{self.store.pk}/referral/"

    def test_two_colleagues_get_the_same_code(self):
        self.client.force_login(self.owner)
        first = self.client.post(self.url).json()["code"]
        self.client.force_login(self.admin)
        second = self.client.post(self.url).json()["code"]
        self.assertEqual(first, second)
        self.assertEqual(ReferralCode.objects.filter(store=self.store).count(), 1)

    def test_the_reward_goes_to_the_account_that_pays_the_bills(self):
        self.client.force_login(self.admin)
        self.client.post(self.url)
        self.assertEqual(ReferralCode.objects.get(store=self.store).owner, self.owner)

    def test_a_colleague_sees_the_shops_numbers_not_their_own(self):
        self.client.force_login(self.owner)
        self.client.post(self.url)
        self.client.force_login(self.admin)
        self.assertIsNotNone(self.client.get(self.url).json()["code"])


class RefusalOrderTests(TestCase):
    """Which refusal a customer sees when more than one is true.

    Found by a real run, not by the suite: a shop that used the last of a
    code's capacity themselves was told «ظرفیت پر شده است», which sounds like
    they missed out on something. «قبلاً استفاده شده» is equally true and
    actually explains what happened.
    """

    def setUp(self):
        owner = User.objects.create_user("order-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه ترتیب")
        self.plan = Plan.objects.create(slug="ord", name="پلن", price_toman=100_000)
        self.code = DiscountCode.objects.create(code="LAST1", value=10, max_uses=1)

    def test_using_the_last_use_yourself_says_you_already_used_it(self):
        redeem(self.code, self.store, self.plan, 100_000)
        self.code.refresh_from_db()
        self.assertIn("قبلاً", self.code.unusable_because(store=self.store))

    def test_someone_else_using_the_last_one_is_told_it_is_full(self):
        other_owner = User.objects.create_user("order-other", password="x")
        other = Store.objects.create(owner=other_owner, name="فروشگاه دیگر")
        redeem(self.code, other, self.plan, 100_000)
        self.code.refresh_from_db()
        self.assertIn("ظرفیت", self.code.unusable_because(store=self.store))

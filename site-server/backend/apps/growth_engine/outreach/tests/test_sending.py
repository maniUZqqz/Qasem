"""The send job: what is posted, what is never posted, and every limit. Local fixture forms and a fake web only."""
from datetime import timedelta
from unittest import mock

import httpx
from django.test import TestCase
from django.utils import timezone

from apps.growth_engine.compliance.models import AuditEntry, GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.leads.models import Lead, LeadActivity
from apps.growth_engine.outreach.models import Campaign, ItemStatus, OutreachItem, OutreachJob, SendAttempt
from apps.growth_engine.outreach.services import approval, campaigns, items, sending
from apps.growth_engine.outreach.services.form_analysis import FormPlan

from .helpers import FakeSleep, MidRng, Site, approved_item, configure, make_campaign, make_lead, page, use_site


class SendBase(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.campaign = make_campaign(user=self.staff)
        self.site = Site()
        self.n = 0

    def approve(self, host=None, **kw):
        """Another approved item on its own cooperative site."""
        self.n += 1
        host = host or f"shop{self.n}.ir"
        self.site.shop(host)
        return approved_item(self.site, self.campaign, host, staff=self.staff, **kw)

    def run_job(self, sleep=None, rng=None, start=True):
        """Start the campaign (creating the send job) and run it in-process with an injected sleep / rng."""
        if start:
            _, job, created = campaigns.start(self.campaign, self.staff)
        else:
            job = self.campaign.jobs.filter(kind="send").first()
        sleep = sleep if sleep is not None else FakeSleep()
        with use_site(self.site):
            status = sending.run_send(job.pk, sleep=sleep, rng=rng or MidRng())
        job.refresh_from_db()
        return job, status, sleep

    def state(self, item):
        return OutreachItem.objects.get(pk=item.pk)


class ExactSendTests(SendBase):
    def test_the_posted_form_is_exactly_the_approved_dry_run(self):
        item = self.approve("shop-a.ir", name="گل‌سرخ", city="شیراز")
        dry_run = dict(FormPlan.from_dict(item.plan).payload_pairs())
        self.site.token = "TOKEN-FRESH"  # the page hands out a new CSRF token on the next load
        job, status, sleep = self.run_job()
        self.assertEqual((status, job.status, job.items_sent), ("completed", "completed", 1))
        self.assertEqual(len(self.site.posts()), 1)
        posted = dict(self.site.post_fields())
        self.assertEqual(posted.pop("_token"), "TOKEN-FRESH")
        dry_run.pop("_token")
        self.assertEqual(posted, dry_run, "every visible field equals what the marketer approved")
        self.assertEqual(posted["message"], item.rendered_text)
        self.assertTrue(posted["message"].endswith("«لغو»."))
        self.assertIn("علی رضایی | آپ‌مارکت", posted["message"])
        self.assertIn("گل‌سرخ", posted["message"])
        post = self.site.posts()[0]
        self.assertEqual(post.url.path, "/send-message")
        self.assertEqual(post.headers["referer"], "https://shop-a.ir/contact")
        self.assertIn("NMarketingBot", post.headers["user-agent"])
        self.assertEqual(sleep.calls, [], "nothing to wait for after the only item")

    def test_everything_is_recorded(self):
        item = self.approve("shop-a.ir")
        job, _, _ = self.run_job()
        item = self.state(item)
        self.assertEqual(item.status, "sent")
        attempt = item.attempt
        self.assertEqual((attempt.status_code, attempt.success_guess, attempt.outcome, attempt.method), (200, "likely_success", "ok", "POST"))
        self.assertEqual(attempt.url, "https://shop-a.ir/send-message")
        payload = {p["name"]: p["value"] for p in attempt.payload}
        self.assertEqual(payload["_token"], "***", "hidden page tokens are not stored")
        self.assertEqual((payload["email"], payload["message"]), ("ali@upmarket.ir", item.rendered_text))
        self.assertIn("با تشکر", attempt.response_snippet)
        activity = LeadActivity.objects.get(lead=item.lead, kind="queue_outcome")
        self.assertEqual(activity.data["message_text"], item.rendered_text)
        self.assertEqual((activity.data["outcome"], activity.data["http_status"], activity.data["success_guess"], activity.data["channel"]), ("sent", 200, "likely_success", "contact_form"))
        self.assertEqual(activity.data["payload"], attempt.payload)
        self.assertEqual((activity.data["item_id"], activity.data["campaign_id"]), (item.pk, self.campaign.pk))
        self.assertEqual(activity.actor_id, self.staff.pk)
        self.assertEqual(Lead.objects.get(pk=item.lead_id).status, "contacted")
        self.assertTrue(AuditEntry.objects.filter(kind="send_attempt", data__item_id=item.pk, data__http_status=200).exists())
        self.assertEqual(Campaign.objects.get(pk=self.campaign.pk).status, "completed")

    def test_only_approved_items_are_sent(self):
        approved = self.approve("a.ir")
        self.site.shop("b.ir")
        from .helpers import ready_item

        ready = ready_item(self.site, self.campaign, "b.ir")
        self.run_job()
        self.assertEqual((self.state(approved).status, self.state(ready).status), ("sent", "ready"))
        self.assertEqual(len(self.site.posts()), 1)

    def test_a_second_job_sends_nothing_again(self):
        item = self.approve("a.ir")
        self.run_job()
        extra = OutreachJob.objects.create(campaign=self.campaign, kind="send", created_by=self.staff)
        Campaign.objects.filter(pk=self.campaign.pk).update(status="active")
        with use_site(self.site):
            sending.run_send(extra.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertEqual(len(self.site.posts()), 1)
        self.assertEqual(self.state(item).status, "sent")


class AtMostOnceTests(SendBase):
    def test_two_claims_one_winner(self):
        item = self.approve("a.ir")
        self.assertTrue(sending.claim(item.pk))
        self.assertFalse(sending.claim(item.pk))
        self.assertEqual(self.state(item).status, "sending")

    def test_claim_next_hands_each_item_out_once(self):
        a, b = self.approve("a.ir"), self.approve("b.ir")
        first = sending.claim_next(self.campaign.pk)
        second = sending.claim_next(self.campaign.pk)
        third = sending.claim_next(self.campaign.pk)
        self.assertEqual((first.pk, second.pk, third), (a.pk, b.pk, None))

    def test_a_claimed_item_is_not_sent_by_a_second_job(self):
        item = self.approve("a.ir")
        sending.claim(item.pk)  # another worker holds it
        job = OutreachJob.objects.create(campaign=self.campaign, kind="send", created_by=self.staff)
        Campaign.objects.filter(pk=self.campaign.pk).update(status="active")
        with use_site(self.site):
            self.assertEqual(sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng()), "completed")
        self.assertEqual(self.site.posts(), [])
        self.assertEqual(self.state(item).status, "sending")


class SuccessHeuristicTests(SendBase):
    def send_to(self, post_route):
        self.n += 1
        host = f"h{self.n}.ir"
        self.site.robots(host).form_page(host)
        post_route(host)
        item = approved_item(self.site, self.campaign, host, staff=self.staff)
        self.run_job_again()
        return self.state(item)

    def run_job_again(self):
        job = OutreachJob.objects.create(campaign=self.campaign, kind="send", created_by=self.staff)
        Campaign.objects.filter(pk=self.campaign.pk).update(status="active")
        with use_site(self.site):
            sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng())

    def test_thank_you_text_is_a_likely_success(self):
        item = self.send_to(lambda h: self.site.accept_posts(h, fixture="thanks.html"))
        self.assertEqual((item.status, item.attempt.success_guess), ("sent", "likely_success"))

    def test_a_redirect_to_a_thank_you_page_is_read_and_counts(self):
        def route(h):
            self.site.add("POST", h, "/send-message", "", status=302, headers={"location": "/thanks"})
            self.site.add("GET", h, "/thanks", page("thanks.html"))

        item = self.send_to(route)
        self.assertEqual((item.status, item.attempt.status_code, item.attempt.success_guess), ("sent", 302, "likely_success"))
        self.assertEqual([r.method for r in self.site.requests if r.url.path in ("/send-message",)], ["POST"] * len(self.site.posts()))

    def test_an_unclear_2xx_is_sent_but_marked_unclear(self):
        item = self.send_to(lambda h: self.site.accept_posts(h, fixture="neutral.html"))
        self.assertEqual((item.status, item.attempt.success_guess), ("sent", "unclear"))

    def test_a_2xx_page_that_shows_an_error_is_a_failure(self):
        item = self.send_to(lambda h: self.site.accept_posts(h, fixture="rejected.html"))
        self.assertEqual((item.status, item.attempt.success_guess, item.skip_reason), ("failed", "likely_failure", "send_failed"))
        self.assertIn("خطا", item.skip_reason_text)
        self.assertEqual(Lead.objects.get(pk=item.lead_id).status, "new", "a failed attempt does not mark the lead contacted")
        activity = LeadActivity.objects.get(lead=item.lead, kind="queue_outcome")
        self.assertEqual(activity.data["outcome"], "failed")

    def test_the_form_label_alone_is_not_a_success(self):
        item = self.send_to(lambda h: self.site.add("POST", h, "/send-message", page("contact_ok.html").replace("{token}", "x")))  # the form again
        self.assertEqual(item.attempt.success_guess, "unclear")


class NeverRetriedTests(SendBase):
    def test_a_server_error_is_final(self):
        item = self.approve("a.ir")
        self.site.accept_posts("a.ir", status=503, fixture="neutral.html")
        job, status, _ = self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.attempt.status_code, item.attempt.success_guess, job.items_failed), ("failed", 503, "likely_failure", 1))
        self.assertEqual(len(self.site.posts()), 1, "no retry inside the fetcher either")
        # a new job, a new day, a restart: still no second POST
        extra = OutreachJob.objects.create(campaign=self.campaign, kind="send")
        Campaign.objects.filter(pk=self.campaign.pk).update(status="active")
        with use_site(self.site):
            sending.run_send(extra.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertEqual(len(self.site.posts()), 1)

    def test_a_timeout_is_final_because_the_message_may_have_arrived(self):
        item = self.approve("a.ir")
        self.site.add("POST", "a.ir", "/send-message", error=httpx.ReadTimeout("slow"))
        self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.attempt.outcome, item.attempt.status_code), ("failed", "timeout", 0))
        self.assertEqual(len(self.site.posts()), 1)

    def test_a_refusal_is_final_and_a_failed_lead_cannot_be_queued_again(self):
        item = self.approve("a.ir")
        self.site.accept_posts("a.ir", status=403, fixture="rejected.html")
        self.run_job()
        self.assertEqual(self.state(item).status, "failed")
        other = make_campaign(self.campaign.template, name="x")
        self.assertEqual(campaigns.add_leads(other, [item.lead_id]).skipped[0]["reason"], "already_contacted")

    def test_a_failed_item_is_never_approved_or_claimed_again(self):
        item = self.approve("a.ir")
        self.site.accept_posts("a.ir", status=500, fixture="neutral.html")
        self.run_job()
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk])["refused"][0]["code"], "not_ready")
        self.assertFalse(sending.claim(item.pk))


class FormChangedTests(SendBase):
    def test_a_captcha_that_appears_after_approval_stops_the_send(self):
        item = self.approve("a.ir")
        self.site.form_page("a.ir", fixture="contact_captcha.html")
        job, _, _ = self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.skip_reason, item.approved_record), ("needs_manual", "captcha", None))
        self.assertEqual(self.site.posts(), [])
        self.assertEqual(job.items_blocked, 1)
        self.assertEqual(FormPlan.from_dict(item.plan).detected["captcha"], True, "the plan on the item shows what was found now")

    def test_a_new_field_voids_the_approval_and_nothing_is_posted(self):
        item = self.approve("a.ir")
        old_fp = item.fingerprint
        self.site.form_page("a.ir", fixture="contact_extra_field.html")
        self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.approved_record), ("ready", None))
        self.assertNotEqual(item.fingerprint, old_fp)
        self.assertIn("tracking", [f["name"] for f in item.plan["fields"]])
        self.assertEqual(self.site.posts(), [])
        self.assertTrue(AuditEntry.objects.filter(kind="approval", summary__contains="فرم عوض شده").exists())
        # the marketer approves the NEW form and only then does it go out
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)["approved"], 1)
        self.run_job()
        self.assertEqual(self.state(item).status, "sent")
        self.assertIn(("tracking", ""), self.site.post_fields())

    def test_a_changed_message_between_approval_and_send_cannot_slip_through(self):
        item = self.approve("a.ir")
        OutreachItem.objects.filter(pk=item.pk).update(rendered_text=item.rendered_text + "\nتبلیغِ اضافه")  # bypassing the service on purpose
        self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.skip_reason), ("ready", "approval_invalid"))
        self.assertEqual(self.site.posts(), [])

    def test_the_action_url_becoming_forbidden_by_robots(self):
        item = self.approve("a.ir")
        self.site.robots("a.ir", "User-agent: *\nDisallow: /send-message\n")
        self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.skip_reason), ("needs_manual", "robots_blocked"))
        self.assertEqual(self.site.posts(), [])

    def test_the_page_disappearing_sends_nothing(self):
        item = self.approve("a.ir")
        self.site.routes.pop(("GET", "a.ir", "/contact"))
        self.run_job()
        self.assertEqual((self.state(item).status, self.state(item).skip_reason), ("needs_manual", "fetch_failed"))
        self.assertEqual(self.site.posts(), [])

    def test_a_post_that_the_fetcher_refuses_sends_nothing_and_uses_no_allowance(self):
        from apps.growth_engine.integrations import safe_http as sh

        item = self.approve("a.ir")
        refused = sh.FetchResult(url="https://a.ir/send-message", outcome=sh.ROBOTS_BLOCKED)
        with mock.patch("apps.growth_engine.integrations.safe_http.SafeFetcher.post_form", return_value=refused):
            self.run_job()
        self.assertEqual(self.site.posts(), [])
        self.assertEqual(SendAttempt.objects.count(), 0)
        item = self.state(item)
        self.assertEqual((item.status, item.skip_reason), ("needs_manual", "robots_blocked"))


class GuardAtSendTests(SendBase):
    def test_suppressed_after_approval_is_never_sent(self):
        item = self.approve("a.ir")
        suppression.suppress_lead(item.lead, "opt_out", "", self.staff)
        job, _, _ = self.run_job()
        item = self.state(item)
        self.assertEqual((item.status, item.skip_reason), ("skipped", "suppressed"))
        self.assertEqual(self.site.posts(), [])
        self.assertEqual(job.items_blocked, 1)

    def test_contacted_elsewhere_after_approval_is_never_sent(self):
        item = self.approve("a.ir")
        other = make_campaign(self.campaign.template, name="other")
        OutreachItem.objects.create(campaign=other, lead=item.lead, status=ItemStatus.MANUAL_SENT, domain="")
        self.run_job()
        self.assertEqual((self.state(item).status, self.state(item).skip_reason), ("skipped", "already_contacted"))
        self.assertEqual(self.site.posts(), [])

    def test_an_item_with_an_attempt_is_never_sent_again(self):
        item = self.approve("a.ir")
        SendAttempt.objects.create(item=item, url="x")
        self.run_job()
        self.assertEqual((self.state(item).status, self.state(item).skip_reason), ("skipped", "already_attempted"))
        self.assertEqual(self.site.posts(), [])

    def test_the_opt_out_line_missing_is_refused_at_send_time(self):
        item = self.approve("a.ir")
        configure(opt_out_line="جملهٔ لغوِ تازه که در پیام نیست.")
        self.run_job()
        self.assertEqual((self.state(item).status, self.state(item).skip_reason), ("needs_manual", "opt_out_missing"))
        self.assertEqual(self.site.posts(), [])


class LimitTests(SendBase):
    def test_the_daily_cap_stops_the_job_and_leaves_the_campaign_active(self):
        configure(daily_cap=2)
        batch = [self.approve() for _ in range(3)]
        job, status, sleep = self.run_job()
        self.assertEqual((status, job.status, job.items_sent), ("completed", "completed", 2))
        self.assertIn("سقفِ روزانه", job.note)
        self.assertEqual(len(self.site.posts()), 2)
        self.assertEqual([self.state(i).status for i in batch], ["sent", "sent", "approved"])
        self.assertEqual(Campaign.objects.get(pk=self.campaign.pk).status, "active")
        # the same day: starting again is refused
        with self.assertRaises(campaigns.CampaignError) as ctx:
            campaigns.start(self.campaign, self.staff)
        self.assertIn("سقفِ روزانه", ctx.exception.message)
        # tomorrow: the allowance is back and «ادامهٔ ارسال» sends the rest
        SendAttempt.objects.update(attempted_at=timezone.now() - timedelta(days=1))
        job2, _, _ = self.run_job()
        self.assertEqual((job2.items_sent, len(self.site.posts())), (1, 3))
        self.assertEqual(Campaign.objects.get(pk=self.campaign.pk).status, "completed")

    def test_the_default_cap_is_forty(self):
        self.assertEqual(GrowthSettings.load().daily_cap, 40)

    def test_the_cap_counts_every_campaign(self):
        configure(daily_cap=2)
        elsewhere = make_campaign(self.campaign.template, name="other")
        for i in range(2):
            SendAttempt.objects.create(item=OutreachItem.objects.create(campaign=elsewhere, lead=make_lead(f"o{i}.ir"), status=ItemStatus.SENT), url="u")
        item = self.approve("mine.ir")
        # the cap is already used up: the campaign cannot even start
        with self.assertRaises(campaigns.CampaignError):
            campaigns.start(self.campaign, self.staff)
        self.assertEqual(self.state(item).status, "approved")

    def test_spacing_is_slept_between_sends_inside_the_range_and_not_after_the_last(self):
        configure(spacing_min_seconds=60, spacing_max_seconds=120)
        batch = [self.approve() for _ in range(3)]
        sleep = FakeSleep()
        calls = []

        class Rng:
            def uniform(self, low, high):
                calls.append((low, high))
                return 75.0

        job, _, _ = self.run_job(sleep=sleep, rng=Rng())
        self.assertEqual(calls, [(60, 120), (60, 120)], "two waits for three messages")
        self.assertEqual(sleep.total, 150.0)
        self.assertTrue(all(0 < c <= 1.0 for c in sleep.calls), "slept in slices of at most one second")
        self.assertEqual(len(self.site.posts()), 3)

    def test_the_mid_range_wait(self):
        configure(spacing_min_seconds=60, spacing_max_seconds=120)
        self.approve(), self.approve()
        job, _, sleep = self.run_job(rng=MidRng())
        self.assertEqual(sleep.total, 90.0)

    def test_a_blocked_item_costs_no_waiting(self):
        a, b = self.approve("a.ir"), self.approve("b.ir")
        suppression.suppress_lead(a.lead, "opt_out", "", self.staff)
        job, _, sleep = self.run_job()
        self.assertEqual((self.state(a).status, self.state(b).status), ("skipped", "sent"))
        self.assertEqual(sleep.calls, [])


class StopTests(SendBase):
    def test_an_emergency_stop_during_the_spacing_ends_the_job_and_leaves_the_rest_approved(self):
        batch = [self.approve() for _ in range(3)]
        sleep = FakeSleep(after=5, callback=lambda: configure(emergency_stop=True))
        job, status, _ = self.run_job(sleep=sleep)
        self.assertEqual((status, job.status), ("cancelled", "cancelled"))
        self.assertIn("توقفِ اضطراری", job.error)
        self.assertEqual(len(self.site.posts()), 1)
        self.assertEqual([self.state(i).status for i in batch], ["sent", "approved", "approved"])
        self.assertEqual(len(sleep.calls), 5, "it stopped waiting at once")

    def test_a_stop_set_before_the_job_runs_sends_nothing(self):
        self.approve()
        _, job, _ = campaigns.start(self.campaign, self.staff)
        configure(emergency_stop=True)
        with use_site(self.site):
            self.assertEqual(sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng()), "cancelled")
        self.assertEqual(self.site.posts(), [])
        self.assertEqual(OutreachItem.objects.filter(status="approved").count(), 1)

    def test_a_stop_that_arrives_while_the_page_is_being_read_prevents_the_post(self):
        item = self.approve("a.ir")

        def stop_during_fetch(request):
            configure(emergency_stop=True)
            return page("contact_ok.html").replace("{token}", "T")

        self.site.add("GET", "a.ir", "/contact", stop_during_fetch)
        self.run_job()
        self.assertEqual(self.site.posts(), [])
        self.assertEqual(self.state(item).status, "approved")

    def test_pausing_the_campaign_stops_the_job(self):
        batch = [self.approve() for _ in range(2)]
        sleep = FakeSleep(after=3, callback=lambda: campaigns.pause(self.campaign, self.staff))
        job, status, _ = self.run_job(sleep=sleep)
        self.assertEqual((status, len(self.site.posts())), ("cancelled", 1))
        self.assertEqual([self.state(i).status for i in batch], ["sent", "approved"])
        self.assertEqual(Campaign.objects.get(pk=self.campaign.pk).status, "paused")

    def test_switching_automatic_sending_off_stops_the_job(self):
        batch = [self.approve() for _ in range(2)]
        sleep = FakeSleep(after=2, callback=lambda: configure(sending_enabled=False))
        job, status, _ = self.run_job(sleep=sleep)
        self.assertEqual((status, len(self.site.posts())), ("cancelled", 1))
        self.assertEqual(self.state(batch[1]).status, "approved")

    def test_cancelling_the_campaign_stops_the_job_and_cancels_what_is_left(self):
        batch = [self.approve() for _ in range(2)]
        sleep = FakeSleep(after=2, callback=lambda: campaigns.cancel(self.campaign, self.staff))
        job, status, _ = self.run_job(sleep=sleep)
        self.assertEqual((status, len(self.site.posts())), ("cancelled", 1))
        self.assertEqual([self.state(i).status for i in batch], ["sent", "cancelled"])

    def test_cancelling_the_job_itself(self):
        batch = [self.approve() for _ in range(2)]
        holder = {}
        sleep = FakeSleep(after=2, callback=lambda: sending.request_cancel(holder["job"]))
        _, job, _ = campaigns.start(self.campaign, self.staff)
        holder["job"] = job
        with use_site(self.site):
            status = sending.run_send(job.pk, sleep=sleep, rng=MidRng())
        self.assertEqual((status, len(self.site.posts()), self.state(batch[1]).status), ("cancelled", 1, "approved"))

    def test_the_stop_is_checked_before_every_single_item(self):
        a, b = self.approve("a.ir"), self.approve("b.ir")
        calls = {"n": 0}
        real = sending.stop_reason

        def stop_on_second(job):
            calls["n"] += 1
            return "تست" if calls["n"] >= 4 else real(job)

        with mock.patch.object(sending, "stop_reason", stop_on_second):
            job, status, _ = self.run_job()
        self.assertEqual(status, "cancelled")
        self.assertLessEqual(len(self.site.posts()), 1)


class CrashTests(SendBase):
    def test_a_failure_before_the_post_sends_nothing_and_the_job_goes_on(self):
        a, b = self.approve("a.ir"), self.approve("b.ir")
        real = sending.preparing.analyse
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("boom")
            return real(*args, **kwargs)

        with mock.patch.object(sending.preparing, "analyse", flaky):
            job, status, _ = self.run_job()
        self.assertEqual((status, self.state(a).status, self.state(a).skip_reason, self.state(b).status), ("completed", "needs_manual", "fetch_failed", "sent"))
        self.assertEqual(len(self.site.posts()), 1)
        self.assertEqual(SendAttempt.objects.filter(item=a).count(), 0)

    def test_an_exception_after_the_post_marks_failed_and_still_counts_the_attempt(self):
        a, b = self.approve("a.ir"), self.approve("b.ir")
        calls = {"n": 0}
        real = sending.history.log_activity

        def broken_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db hiccup")
            return real(*args, **kwargs)

        with mock.patch.object(sending.history, "log_activity", broken_once):
            job, status, _ = self.run_job()
        a = self.state(a)
        self.assertEqual((status, a.status, a.skip_reason), ("completed", "failed", "internal_error"))
        self.assertTrue(SendAttempt.objects.filter(item=a).exists(), "the cap and the duplicate rules still see it")
        self.assertEqual(self.state(b).status, "sent")
        self.assertEqual(len(self.site.posts()), 2)

    def test_an_exception_inside_the_poster_is_treated_as_maybe_delivered(self):
        item = self.approve("a.ir")
        with mock.patch("apps.growth_engine.integrations.safe_http.SafeFetcher.post_form", side_effect=RuntimeError("weird")):
            job, status, _ = self.run_job()
        item = self.state(item)
        self.assertEqual((status, item.status), ("completed", "failed"))
        self.assertTrue(SendAttempt.objects.filter(item=item).exists())

    def test_an_infrastructure_failure_fails_the_job_and_can_be_resumed(self):
        item = self.approve("a.ir")
        with mock.patch.object(sending, "claim_next", side_effect=RuntimeError("db gone")):
            job, status, _ = self.run_job()
        self.assertEqual((status, job.status), ("failed", "failed"))
        self.assertIn("RuntimeError", job.error)
        self.assertNotIn("db gone", job.error)
        self.assertTrue(sending.prepare_resume(job))
        with use_site(self.site):
            self.assertEqual(sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng()), "completed")
        self.assertEqual(self.state(item).status, "sent")
        self.assertEqual(len(self.site.posts()), 1)


class ResumeTests(SendBase):
    def test_a_stalled_job_is_resumable_and_a_stuck_sending_item_is_never_resent(self):
        stuck, waiting = self.approve("a.ir"), self.approve("b.ir")
        _, job, _ = campaigns.start(self.campaign, self.staff)
        sending.claim(stuck.pk)  # a worker took it, then died
        old = timezone.now() - timedelta(minutes=30)
        OutreachJob.objects.filter(pk=job.pk).update(status="running", heartbeat_at=old)
        OutreachItem.objects.filter(pk=stuck.pk).update(updated_at=old)
        job.refresh_from_db()
        self.assertTrue(job.is_stalled)
        self.assertTrue(sending.can_resume(job))
        self.assertTrue(sending.prepare_resume(job))
        self.assertEqual((self.state(stuck).status, self.state(stuck).skip_reason), ("failed", "unknown_outcome"))
        with use_site(self.site):
            self.assertEqual(sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng()), "completed")
        self.assertEqual(self.state(waiting).status, "sent")
        self.assertEqual(len(self.site.posts()), 1, "only the second item was posted")

    def test_a_healthy_running_job_cannot_be_resumed_and_a_finished_one_neither(self):
        self.approve()
        _, job, _ = campaigns.start(self.campaign, self.staff)
        OutreachJob.objects.filter(pk=job.pk).update(status="running", heartbeat_at=timezone.now())
        job.refresh_from_db()
        self.assertFalse(sending.prepare_resume(job))
        OutreachJob.objects.filter(pk=job.pk).update(status="completed")
        job.refresh_from_db()
        self.assertFalse(sending.prepare_resume(job))

    def test_cancel_a_queued_job(self):
        self.approve()
        _, job, _ = campaigns.start(self.campaign, self.staff)
        self.assertEqual(sending.request_cancel(job).status, "cancelled")
        with use_site(self.site):
            self.assertEqual(sending.run_send(job.pk, sleep=FakeSleep()), "cancelled")
        self.assertEqual(self.site.posts(), [])

    def test_missing_job(self):
        self.assertEqual(sending.run_send(999999), "missing")


class ManualCampaignNeverAutoSendsTests(SendBase):
    def test_a_manual_campaign_has_no_send_job(self):
        manual = make_campaign(mode="manual", name="m")
        lead = make_lead("m.ir")
        item = campaigns.add_leads(manual, [lead.pk]).added[0]
        _, job, created = campaigns.start(manual, self.staff)
        self.assertIsNone(job)
        self.assertEqual(OutreachItem.objects.get(pk=item.pk).status, "pending")
        self.assertEqual(self.site.requests, [])

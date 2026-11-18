"""اجرای برنامه: «اول می‌پذیرد، بعد می‌سازد»، تکرارپذیری، وضعیتِ زنده از روی پیوندها، تصمیمِ مالک، پولیشِ هوش مصنوعی."""
import datetime as dt
import uuid

from django.test import TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.tasks_board import CampaignTask
from apps.compute.models import ComputeJob
from apps.inbox.models import Broadcast, CannedReply

from . import ai as plan_ai
from . import clock, drafts, facts as facts_mod, planner, producers, refs, runner
from .models import PlanItem
from .testkit import make_store, old_campaigns

S = PlanItem.Status


def _run(plan, **kw):
    return runner.run_plan(plan, force=True, **kw)


class AdoptionTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.tasks = old_campaigns(self.store, self.prod)
        self.plan, _ = planner.ensure_plan(self.store, self.owner, start=clock.today_tehran() + dt.timedelta(days=1))

    def test_existing_content_is_linked_and_retimed_not_duplicated(self):
        before = CampaignTask.objects.filter(store=self.store).count()
        _run(self.plan, kinds_only={"carousel", "reel", "story", "post"})
        # فقط اولین کاروسل/ریلز/استوری/پست با کارِ قدیمی جفت می‌شود؛ بقیه کارِ تازه می‌گیرند
        carousel = self.plan.items.get(key="d02.carousel.1")
        self.assertEqual(refs.of_type(carousel, "campaign_task")[0]["id"], self.tasks["کاروسل"].pk)
        self.assertTrue(carousel.meta["adopted"])
        t = CampaignTask.objects.get(pk=self.tasks["کاروسل"].pk)
        self.assertGreater(t.due_at, timezone.now())
        self.assertNotIn("۱۴۰۵/۰۸/۲۳", t.detail)
        self.assertIn(clock.jalali(self.plan.start_date + dt.timedelta(days=1)), t.detail)
        # موعدی که مالک دستی گذاشته با اجرای دوباره پاک نمی‌شود
        mine = timezone.now() + dt.timedelta(days=40)
        CampaignTask.objects.filter(pk=self.tasks["کاروسل"].pk).update(due_at=mine)
        _run(self.plan, kinds_only={"carousel"})
        self.assertEqual(CampaignTask.objects.get(pk=self.tasks["کاروسل"].pk).due_at, mine)
        # ولی اگر تاریخِ برنامه عوض شود (شروعِ دوباره) موعد به برنامه برمی‌گردد
        planner.ensure_plan(self.store, self.owner, start=clock.today_tehran() + dt.timedelta(days=9))
        _run(self.plan, kinds_only={"carousel"})
        self.assertNotEqual(CampaignTask.objects.get(pk=self.tasks["کاروسل"].pk).due_at, mine)
        # دوباره اجرا ⇒ هیچ کارِ تازه‌ای ساخته نمی‌شود
        n = CampaignTask.objects.filter(store=self.store).count()
        _run(self.plan, kinds_only={"carousel", "reel", "story", "post"})
        self.assertEqual(CampaignTask.objects.filter(store=self.store).count(), n)
        self.assertGreaterEqual(n, before)

    def test_reserved_real_testimonial_task_is_not_taken_by_a_reel(self):
        _run(self.plan, kinds_only={"reel", "testimonial"})
        reels = [r["id"] for i in self.plan.items.filter(kind="reel") for r in refs.of_type(i, "campaign_task")]
        self.assertNotIn(self.tasks["نظر"].pk, reels)
        testi = self.plan.items.get(kind="testimonial")
        self.assertEqual(refs.of_type(testi, "campaign_task")[0]["id"], self.tasks["نظر"].pk)
        self.assertEqual(testi.status, S.NEEDS_YOU)
        self.assertIn("نظر", testi.meta["needs_you"])

    def test_profile_adopts_profile_campaign_and_is_never_taken_as_a_post(self):
        _run(self.plan, kinds_only={"profile", "post"})
        prof = self.plan.items.get(kind="profile")
        self.assertEqual([r["id"] for r in refs.of_type(prof, "campaign_task")], [self.tasks["بایو"].pk])
        for i in self.plan.items.filter(kind="post"):
            self.assertNotIn(self.tasks["بایو"].pk, [r["id"] for r in refs.of_type(i, "campaign_task")])

    def test_new_work_goes_into_a_plan_campaign_with_placeholders_not_invented_facts(self):
        _owner, store, _p = make_store(name="فروشگاه بی‌کمپین")
        plan, _ = planner.ensure_plan(store, self.owner)
        _run(plan, kinds_only={"carousel"})
        it = plan.items.get(key="d02.carousel.1")
        t = CampaignTask.objects.get(pk=refs.of_type(it, "campaign_task")[0]["id"])
        self.assertEqual(t.campaign.store_id, store.pk)
        self.assertIn("برنامهٔ بازاریابی", t.campaign.name)
        self.assertIn("[", it.draft)                                  # جای‌گیرِ داده‌ای که فقط مالک دارد
        self.assertIn("کپشنِ پیشنهادی", it.draft)
        self.assertIn("#فروشگاه", it.draft)                            # هشتگ فقط از نامِ خودِ فروشگاه
        self.assertNotIn("تومان", it.draft)
        self.assertTrue(it.ai_wait)                                   # منتظرِ بازنویسیِ هوشمند
        self.assertEqual(it.status, S.DRAFTED)
        n = CampaignTask.objects.filter(store=store).count()
        _run(plan, kinds_only={"carousel"})
        self.assertEqual(CampaignTask.objects.filter(store=store).count(), n)

    def test_store_without_product_asks_the_owner_instead_of_crashing(self):
        _owner, store, _ = make_store(products=False, name="بی‌محصول")
        plan, _ = planner.ensure_plan(store, self.owner)
        res = _run(plan, kinds_only={"post"})
        self.assertEqual(res["failed"], 0)
        it = plan.items.get(key="d04.post.1")
        self.assertEqual(it.status, S.NEEDS_YOU)
        self.assertIn("محصول", it.message)


class DraftOnlyTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)

    def test_sms_is_only_a_draft_broadcast_with_opt_out(self):
        _run(self.plan, kinds_only={"sms"})
        it = self.plan.items.get(kind="sms")
        b = Broadcast.objects.get(pk=refs.of_type(it, "broadcast")[0]["id"])
        self.assertEqual(b.status, Broadcast.Status.DRAFT)
        self.assertEqual(b.channels, ["SMS"])
        self.assertIn("لغو", b.text)
        self.assertEqual(it.status, S.DRAFTED)
        _run(self.plan, kinds_only={"sms"})
        self.assertEqual(Broadcast.objects.filter(store=self.store).count(), 1)

    def test_email_draft_has_subject_body_and_opt_out_and_no_prices(self):
        _run(self.plan, kinds_only={"email"})
        it = self.plan.items.get(key="d07.email.1")
        self.assertIn("موضوع:", it.draft)
        self.assertIn("لغو", it.draft)
        self.assertNotIn("تومان", it.draft)
        self.assertEqual(it.status, S.DRAFTED)

    def test_inbox_creates_three_canned_replies_once_and_asks_for_channels(self):
        _run(self.plan, kinds_only={"inbox"})
        it = self.plan.items.get(kind="inbox")
        self.assertEqual(CannedReply.objects.filter(store=self.store).count(), 3)
        self.assertEqual(it.status, S.NEEDS_YOU)
        self.assertIn("کانال", it.meta["needs_you"])
        _run(self.plan, kinds_only={"inbox"})
        self.assertEqual(CannedReply.objects.filter(store=self.store).count(), 3)

    def test_review_counts_decisions_and_needs_owner(self):
        self.plan.items.filter(day=3).update(decision="approved")
        _run(self.plan, kinds_only={"review"})
        wk1 = self.plan.items.get(key="d07.review.week1")
        self.assertIn("تأیید", wk1.draft)
        self.assertEqual(wk1.status, S.NEEDS_YOU)

    def test_a_decided_item_is_never_touched_again(self):
        it = self.plan.items.get(key="d07.email.1")
        it.decision = "skipped"
        it.save()
        res = _run(self.plan, kinds_only={"email"})
        it.refresh_from_db()
        self.assertEqual(it.draft, "")
        self.assertGreaterEqual(res["skipped"], 1)

    def test_pre_existing_failure_of_one_producer_does_not_stop_the_rest(self):
        orig = producers.PRODUCERS["email"]
        producers.PRODUCERS["email"] = lambda ctx, item: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            res = _run(self.plan, kinds_only={"email", "sms"})
        finally:
            producers.PRODUCERS["email"] = orig
        self.assertEqual(res["failed"], 2)                           # دو ایمیلِ برنامه
        self.assertEqual(res["ok"], 1)                               # پیامک ساخته شد
        bad = self.plan.items.get(key="d07.email.1")
        self.assertEqual(bad.status, S.FAILED)
        self.assertIn("boom", bad.last_error)


class StatusDerivationTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        self.item = self.plan.items.get(key="d03.motion.reel1")

    def _job(self, state):
        return ComputeJob.objects.create(uid=uuid.uuid4(), kind="motion.render", state=state, store=self.store)

    def test_status_follows_the_linked_compute_job(self):
        job = self._job(ComputeJob.State.QUEUED)
        refs.add(self.item, refs.make("compute_job", str(job.uid), "رندر"))
        runner.sync_item(self.item)
        self.assertEqual(self.item.status, S.WAITING_NODE)
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.RUNNING)
        runner.sync_item(self.item)
        self.assertEqual(self.item.status, S.RUNNING)
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.COMPLETED)
        runner.sync_item(self.item)
        self.assertEqual(self.item.status, S.READY)
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.FAILED, error="کارت پر شد")
        runner.sync_item(self.item)
        self.assertEqual(self.item.status, S.FAILED)
        self.assertIn("کارت", self.item.message)

    def test_needs_you_beats_a_plain_draft_but_not_a_finished_output(self):
        self.item.draft = "متن"
        self.item.meta = {"needs_you": "فقط شما"}
        self.assertEqual(runner.derive(self.item)[0], S.NEEDS_YOU)
        job = self._job(ComputeJob.State.COMPLETED)
        refs.add(self.item, refs.make("compute_job", str(job.uid), "رندر"))
        self.assertEqual(runner.derive(self.item)[0], S.READY)

    def test_waiting_node_without_refs_comes_from_the_producer_flag(self):
        self.item.meta = {"waiting_node": "گره خاموش"}
        self.assertEqual(runner.derive(self.item), (S.WAITING_NODE, "گره خاموش"))

    def test_missing_ref_is_ignored_and_empty_item_is_planned(self):
        refs.add(self.item, refs.make("motion_render", 999999, "پاک‌شده"))
        self.assertEqual(runner.derive(self.item)[0], S.PLANNED)

    def test_counts_and_public_payload_are_consistent(self):
        runner.sync_plan(self.plan)
        c = runner.counts(self.plan)
        self.assertEqual(c["total"], len(planner.SLOTS))
        pub = runner.plan_public(self.plan)
        self.assertEqual(len(pub["items"]), c["total"])
        self.assertIn("node", pub)
        first = pub["items"][0]
        self.assertTrue(first["url"].startswith("/stores/") or first["url"].startswith("/"))
        self.assertTrue(first["date_fa"])


class PolishTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()
        self.plan, _ = planner.ensure_plan(self.store, self.owner)
        _run(self.plan, kinds_only={"carousel", "email"})
        self.f = facts_mod.store_facts(self.store)
        self.item = self.plan.items.get(key="d02.carousel.1")

    def test_polish_rewrites_draft_and_the_campaign_task(self):
        new_text = self.item.draft.replace("قلاب (جملهٔ اول)", "قلاب (جملهٔ نخست)")
        res = runner.polish_item(self.plan, self.item, self.f, ask=lambda store, prompt: {"draft": new_text})
        self.assertEqual(res, "ok")
        self.item.refresh_from_db()
        self.assertFalse(self.item.ai_wait)
        self.assertTrue(self.item.meta["polished"])
        task = CampaignTask.objects.get(pk=refs.of_type(self.item, "campaign_task")[0]["id"])
        self.assertIn("جملهٔ نخست", task.detail)

    def test_polish_that_drops_a_bracket_slot_is_rejected(self):
        old = self.item.draft
        res = runner.polish_item(self.plan, self.item, self.f, ask=lambda s, p: {"draft": old.replace("[", "(").replace("]", ")")})
        self.assertIn("جای‌گیر", res)
        self.item.refresh_from_db()
        self.assertEqual(self.item.draft, old)
        self.assertTrue(self.item.ai_wait)

    def test_polish_that_invents_a_price_is_rejected(self):
        old = self.item.draft
        res = runner.polish_item(self.plan, self.item, self.f, ask=lambda s, p: {"draft": old + "\nفقط ۹۹۹٬۰۰۰ تومان!"})
        self.assertIn("ادعا", res)
        self.item.refresh_from_db()
        self.assertEqual(self.item.draft, old)

    def test_no_ai_means_the_rule_draft_stays_and_item_keeps_waiting(self):
        new, why = plan_ai.polish(self.store, self.f, self.item.draft, "کاروسل")      # زیرِ آزمون هوشِ واقعی صدا زده نمی‌شود
        self.assertIsNone(new)
        self.assertTrue(why)
        self.assertTrue(PlanItem.objects.get(pk=self.item.pk).ai_wait)

    def test_tick_polishes_waiting_items_when_ai_is_back(self):
        # tick با ask تزریقی: همان رفتارِ «هوش مصنوعی برگشت». بقیهٔ کارها «رد‌شده» می‌شوند تا آزمون فقط همین مسیر را بسنجد.
        self.plan.items.exclude(kind__in=("carousel", "email")).update(decision="skipped")
        res = runner.tick(self.plan.pk, ask=lambda store, prompt: {"draft": self.item.draft + "\nدعوتِ آخر."})
        self.assertGreaterEqual(res["polished"], 1)
        self.item.refresh_from_db()
        self.assertFalse(self.item.ai_wait)

    def test_tick_reruns_planned_items_and_syncs(self):
        self.plan.items.exclude(kind__in=("sms", "email")).update(decision="skipped")
        sms = self.plan.items.get(kind="sms")
        self.assertEqual(sms.status, S.PLANNED)
        res = runner.tick(self.plan.pk)
        self.assertEqual(res["plans"], 1)
        self.assertGreaterEqual(res["rerun"], 1)
        sms.refresh_from_db()
        self.assertEqual(sms.status, S.DRAFTED)

    def test_tick_leaves_a_failed_item_alone_after_too_many_tries(self):
        self.plan.items.exclude(key="d07.email.1").update(decision="skipped")
        it = self.plan.items.get(key="d07.email.1")
        it.status, it.last_error, it.meta = S.FAILED, "x", {"tries": runner.MAX_TRIES}
        it.save()
        self.assertFalse(runner._needs_rerun(it, node_on=True))
        it.meta = {"tries": 1}
        self.assertTrue(runner._needs_rerun(it, node_on=True))

    def test_drafts_check_flags_a_banned_word_and_a_fresh_number(self):
        f = dict(self.f, dont_words=["تضمین"])
        flagged = drafts.check("نتیجه تضمین است و ۵۰٪ تخفیف", f)
        self.assertTrue(any("تضمین" in x for x in flagged))
        self.assertTrue(len(flagged) >= 2)
        self.assertEqual(drafts.check("یک جملهٔ ساده", f), [])

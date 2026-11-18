"""سازندهٔ برنامه: قالبِ روزها، تکرارپذیری، و این‌که هیچ ادعا یا قیمتی ساخته نمی‌شود."""
import datetime as dt
import re

from django.test import TestCase

from . import clock, kinds, planner, producers
from .models import MarketingPlan, PlanItem
from .testkit import make_store


class SlotTemplateTests(TestCase):
    def test_every_slot_kind_is_known_and_has_a_producer(self):
        for _day, kind, _pillar, _suffix, _companion in planner.SLOTS:
            self.assertIn(kind, kinds.KINDS, kind)
            self.assertIn(kind, producers.PRODUCERS, f"تولیدکننده‌ای برای «{kind}» نیست")

    def test_keys_unique_days_in_range_and_companions_exist(self):
        keys = [f"d{d:02d}.{k}.{s}" for d, k, _p, s, _c in planner.SLOTS]
        self.assertEqual(len(keys), len(set(keys)))
        for d, _k, p, _s, c in planner.SLOTS:
            self.assertTrue(1 <= d <= planner.DAYS)
            if p:
                self.assertIn(p, planner.PILLARS)
            if c:
                self.assertIn(c, keys)

    def test_every_listed_kind_of_the_brief_is_planned(self):
        """هر چیزی که مالک خواست در برنامه یک نوع دارد."""
        planned = {k for _d, k, _p, _s, _c in planner.SLOTS}
        for need in ("post", "story", "reel", "carousel", "thumbnail", "voiceover", "motion", "email", "sms", "finder", "inbox", "landing", "catalog", "deck",
                     "video_edit", "music", "image", "character", "ideas", "trends", "up3d", "dm", "testimonial", "review"):
            self.assertIn(need, planned, need)

    def test_each_day_has_work_and_two_weeks_are_covered(self):
        days = {d for d, *_ in planner.SLOTS}
        self.assertEqual(days, set(range(1, 15)))


class EnsurePlanTests(TestCase):
    def setUp(self):
        self.owner, self.store, self.prod = make_store()

    def test_creates_all_items_with_store_name_and_is_idempotent(self):
        plan, info = planner.ensure_plan(self.store, self.owner)
        self.assertTrue(info["created"])
        self.assertEqual(plan.items.count(), len(planner.SLOTS))
        self.assertTrue(any("باشگاه نمونه" in i.title for i in plan.items.all()))
        again, info2 = planner.ensure_plan(self.store, self.owner)
        self.assertEqual(again.pk, plan.pk)
        self.assertEqual(info2["added"], 0)
        self.assertEqual(PlanItem.objects.filter(plan=plan).count(), len(planner.SLOTS))
        self.assertEqual(MarketingPlan.objects.filter(store=self.store).count(), 1)

    def test_default_start_is_tomorrow_and_items_are_scheduled(self):
        plan, _ = planner.ensure_plan(self.store, self.owner)
        self.assertEqual(plan.start_date, clock.today_tehran() + dt.timedelta(days=1))
        first, last = plan.items.first(), plan.items.last()
        self.assertEqual(first.scheduled_for.astimezone(clock.TEHRAN).date(), plan.start_date)
        self.assertEqual(last.scheduled_for.astimezone(clock.TEHRAN).date(), plan.start_date + dt.timedelta(days=13))

    def test_restart_moves_dates_but_keeps_decisions_and_drafts(self):
        plan, _ = planner.ensure_plan(self.store, self.owner, start=dt.date(2030, 1, 5))
        item = plan.items.get(key="d03.reel.1")
        item.decision, item.draft = "approved", "متنِ ویرایش‌شدهٔ مالک"
        item.save()
        plan2, info = planner.ensure_plan(self.store, self.owner, start=dt.date(2030, 2, 1))
        self.assertTrue(info["restarted"])
        item.refresh_from_db()
        self.assertEqual(plan2.start_date, dt.date(2030, 2, 1))
        self.assertEqual(item.decision, "approved")
        self.assertEqual(item.draft, "متنِ ویرایش‌شدهٔ مالک")
        self.assertEqual(item.scheduled_for.astimezone(clock.TEHRAN).date(), dt.date(2030, 2, 3))

    def test_nothing_in_titles_or_briefs_invents_prices_or_stats(self):
        plan, _ = planner.ensure_plan(self.store, self.owner)
        for i in plan.items.all():
            blob = f"{i.title} {i.brief}"
            self.assertNotIn("تومان", blob, i.key)
            self.assertNotIn("٪", blob, i.key)
            self.assertNotIn("%", blob, i.key)
            self.assertIsNone(re.search(r"\d{2,}", blob), (i.key, blob))          # شماره‌ی هفته (۱ و ۲) هست؛ عددِ آماری نیست

    def test_works_for_a_store_with_an_almost_empty_profile(self):
        from apps.stores.models import Store

        bare = Store.objects.create(owner=self.owner, name="فروشگاهِ خالی")
        plan, _ = planner.ensure_plan(bare, self.owner)
        self.assertEqual(plan.items.count(), len(planner.SLOTS))
        self.assertTrue(plan.summary["facts"]["gaps"])

    def test_background_preset_follows_the_field_and_varies_by_angle(self):
        from . import drafts, facts as facts_mod

        f = facts_mod.store_facts(self.store)                      # «خدمات ورزشی برای مربیان»
        picks = {drafts.bg_preset(f, p) for p in planner.PILLARS}
        self.assertIn("gym_blur", picks)
        self.assertGreater(len(picks), 1)
        from apps.thumbs import aibg

        self.assertTrue(picks <= set(aibg.PRESETS))
        self.assertIn(drafts.bg_preset({"business": "", "about": "", "name": "x"}, "intro"), aibg.PRESETS)

    def test_clock_retimes_only_the_due_line(self):
        when = clock.at(dt.date(2030, 3, 1), 19, 30)
        text = "نوع: ریلز\nموعدِ پیشنهادیِ انتشار: شنبه ۱۴۰۵/۰۸/۲۳ ساعت ۱۹:۳۰ (تهران) — فقط پیشنهاد؛ چیزی خودکار منتشر نمی‌شود.\n\nبدنه"
        out = clock.retime_detail(text, when)
        self.assertIn("بدنه", out)
        self.assertNotIn("۱۴۰۵/۰۸/۲۳", out)
        self.assertIn(clock.jalali(dt.date(2030, 3, 1)), out)
        self.assertEqual(clock.retime_detail("بدونِ خط", when), "بدونِ خط")

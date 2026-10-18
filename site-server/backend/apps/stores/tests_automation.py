"""Standing instructions for content production (`ایده‌ها پنل.md` صفحه ۴).

Three of these are about a failure that would cost a customer rather than a
test run:

**Nothing posts by itself unless somebody chose that.** The default is
"generate and wait for me". A shop owner who finds a post on their Instagram
they never saw does not change the setting, they stop using the product.

**Enabled is not the same as scheduled.** Turning automation on without picking
a day configures nothing, and the panel has to say so — implying a queue that
does not exist is how somebody waits a week for a post that was never coming.

**Video length is a multiple of five.** The renderer works in five-second shots
and stitches them; 17 seconds would be rounded somewhere the owner cannot see.
"""
from datetime import time

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.products.models import Product

from .content_automation import ContentAutomation, automation_for
from .models import Membership, Store


class DefaultsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("auto-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")

    def test_nothing_runs_until_it_is_turned_on(self):
        row = automation_for(self.store)
        self.assertFalse(row.enabled)
        self.assertEqual(row.publish_days, [])
        self.assertFalse(row.is_scheduled)

    def test_the_default_waits_for_a_person(self):
        self.assertEqual(automation_for(self.store).approval, ContentAutomation.Approval.APPROVE)

    def test_enabled_without_a_day_is_not_scheduled(self):
        row = automation_for(self.store)
        row.enabled = True
        row.save()
        self.assertFalse(row.is_scheduled)
        self.assertIn("هیچ روزی انتخاب نشده", row.summary())

    def test_reading_it_twice_does_not_make_two_rows(self):
        automation_for(self.store)
        automation_for(self.store)
        self.assertEqual(ContentAutomation.objects.filter(store=self.store).count(), 1)


class VideoLengthTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("len-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.row = automation_for(self.store)

    def test_must_be_a_multiple_of_five(self):
        self.row.video_seconds = 17
        with self.assertRaises(ValidationError):
            self.row.clean()

    def test_range_is_enforced(self):
        for bad in (0, 125):
            self.row.video_seconds = bad
            with self.assertRaises(ValidationError):
                self.row.clean()

    def test_segment_count_is_the_length_in_shots(self):
        self.row.video_seconds = 25
        self.assertEqual(self.row.segment_count, 5)


class ScheduleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("sched-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.row = automation_for(self.store)

    def test_invalid_weekday_is_rejected(self):
        self.row.publish_days = [9]
        with self.assertRaises(ValidationError):
            self.row.clean()

    def test_next_run_is_none_when_not_scheduled(self):
        self.assertIsNone(self.row.next_run())

    def test_next_run_lands_on_a_chosen_day(self):
        self.row.enabled = True
        self.row.publish_days = [0, 3]  # Monday, Thursday
        self.row.publish_time = time(9, 0)
        self.row.save()
        due = self.row.next_run()
        self.assertIsNotNone(due)
        self.assertIn(due.weekday(), (0, 3))
        self.assertGreater(due, timezone.localtime())

    def test_summary_says_what_will_happen(self):
        self.row.enabled = True
        self.row.publish_days = [5]
        self.row.approval = ContentAutomation.Approval.AUTO
        self.row.save()
        text = self.row.summary()
        self.assertIn("شنبه", text)
        self.assertIn("خودکار منتشر", text)

    def test_summary_notices_nothing_was_chosen_to_make(self):
        self.row.enabled = True
        self.row.publish_days = [5]
        self.row.make_video = self.row.make_image = self.row.make_caption = False
        self.row.save()
        self.assertIn("هیچ نوع محتوایی", self.row.summary())


class ApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("api-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        Product.objects.create(store=self.store, name="کت")
        self.url = f"/api/v1/stores/{self.store.pk}/content-automation/"
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_get_returns_the_labels_the_panel_renders(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("settings", body)
        # The week starts on Saturday, in the order the panel shows.
        self.assertEqual(body["weekdays"][0]["label"], "شنبه")
        self.assertEqual(body["video"]["step"], 5)
        self.assertEqual([p["name"] for p in body["products"]], ["کت"])

    def test_patch_saves(self):
        res = self.client.patch(
            self.url,
            {"enabled": True, "publish_days": [5, 1], "video_seconds": 30},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        row = automation_for(self.store)
        self.assertTrue(row.enabled)
        self.assertEqual(row.video_seconds, 30)

    def test_patch_rejects_a_length_the_renderer_cannot_produce(self):
        res = self.client.patch(self.url, {"video_seconds": 17}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("video_seconds", res.json())

    def test_patching_one_field_keeps_the_rest(self):
        """A partial update must not re-validate against empty defaults."""
        self.client.patch(self.url, {"video_seconds": 30}, format="json")
        res = self.client.patch(self.url, {"notify": False}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(automation_for(self.store).video_seconds, 30)

    def test_another_users_store_is_invisible(self):
        stranger = User.objects.create_user("stranger", password="x")
        client = APIClient()
        client.force_authenticate(stranger)
        self.assertIn(client.get(self.url).status_code, (403, 404))

    def test_a_content_manager_may_change_it(self):
        """It is their page. Making them ask the owner to move a posting day
        is how the setting stops being used."""
        member = User.objects.create_user("content-person", password="x")
        Membership.objects.create(
            store=self.store, user=member, role=Membership.Role.CONTENT_MANAGER,
        )
        client = APIClient()
        client.force_authenticate(member)
        res = client.patch(self.url, {"make_caption": False}, format="json")
        self.assertEqual(res.status_code, 200, res.content)

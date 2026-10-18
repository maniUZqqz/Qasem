"""The campaign board. §29.1

Nearly everything here defends one decision: **a task backed by a job does not
have its own state.** Two rows for one piece of work drift apart within a day —
the render finishes, the task still says "in progress" — and a board the shop
has caught lying once is a board they stop reading. So the state is read from
the job, and the endpoint that would let someone tick it off by hand refuses.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Membership, Store

from .models import Campaign
from .tasks_board import CampaignTask, board, seed


class BoardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("board-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه تخته")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )
        self.campaign = Campaign.objects.create(
            store=self.store, product=self.product, name="کمپین پاییز",
        )

    def _task(self, **kwargs):
        return CampaignTask.objects.create(
            campaign=self.campaign, store=self.store,
            title=kwargs.pop("title", "یک کار"), **kwargs,
        )

    def _job(self, state):
        return Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, state=state,
        )

    # ------------------------------------------------------- job-backed state

    def test_a_plain_task_keeps_its_own_state(self):
        task = self._task()
        task.mark(CampaignTask.State.DONE)
        self.assertEqual(task.effective_state, CampaignTask.State.DONE)

    def test_a_running_job_makes_its_task_in_progress(self):
        task = self._task(job=self._job(Job.State.PROCESSING))
        self.assertEqual(task.effective_state, CampaignTask.State.DOING)

    def test_a_finished_job_makes_its_task_done(self):
        task = self._task(job=self._job(Job.State.COMPLETED))
        self.assertEqual(task.effective_state, CampaignTask.State.DONE)

    def test_a_failed_job_makes_its_task_blocked(self):
        task = self._task(job=self._job(Job.State.FAILED))
        self.assertEqual(task.effective_state, CampaignTask.State.BLOCKED)

    def test_a_job_waiting_for_a_person_is_blocked_not_in_progress(self):
        """Nothing is happening and nothing will until someone looks. Showing
        it as in-progress is how a job waits three days."""
        task = self._task(job=self._job(Job.State.WAITING_APPROVAL))
        self.assertEqual(task.effective_state, CampaignTask.State.BLOCKED)
        self.assertTrue(task.waiting_on_person)

    def test_a_job_backed_task_cannot_be_ticked_off_by_hand(self):
        task = self._task(job=self._job(Job.State.PROCESSING))
        with self.assertRaises(ValueError):
            task.mark(CampaignTask.State.DONE)

    def test_the_stored_state_is_ignored_when_a_job_disagrees(self):
        """The bug this design prevents, stated directly."""
        task = self._task(state=CampaignTask.State.DONE, job=self._job(Job.State.PROCESSING))
        self.assertEqual(task.effective_state, CampaignTask.State.DOING)

    # ------------------------------------------------------------- lateness

    def test_an_overdue_task_is_late(self):
        task = self._task(due_at=timezone.now() - timedelta(days=1))
        self.assertTrue(task.is_late)

    def test_a_finished_task_is_never_late(self):
        """It was delivered. Marking it red afterwards tells nobody anything
        they can act on."""
        task = self._task(due_at=timezone.now() - timedelta(days=1))
        task.mark(CampaignTask.State.DONE)
        self.assertFalse(task.is_late)

    def test_a_task_with_no_deadline_is_never_late(self):
        self.assertFalse(self._task().is_late)

    # ---------------------------------------------------------------- board

    def test_the_board_has_a_column_for_every_kind(self):
        """§29.1 names five; a board missing one silently loses those tasks."""
        self.assertEqual(len(board(self.campaign)["columns"]), 5)

    def test_progress_counts_job_backed_tasks_correctly(self):
        self._task(job=self._job(Job.State.COMPLETED))
        self._task()
        self.assertEqual(board(self.campaign)["percent"], 50)

    def test_an_empty_board_is_zero_not_a_crash(self):
        self.assertEqual(board(self.campaign)["percent"], 0)

    def test_the_board_surfaces_what_is_waiting_on_a_person(self):
        self._task(job=self._job(Job.State.WAITING_APPROVAL))
        self.assertEqual(len(board(self.campaign)["waiting"]), 1)

    # ---------------------------------------------------------------- seed

    def test_seeding_fills_an_empty_board(self):
        self.assertTrue(seed(self.campaign))
        self.assertEqual(self.campaign.tasks.count(), 7)

    def test_seeding_twice_does_not_resurrect_deleted_tasks(self):
        """Re-seeding a board someone has worked on brings back rows they
        deliberately removed, and they cannot tell ours from theirs after."""
        seed(self.campaign)
        self.campaign.tasks.first().delete()
        self.assertEqual(seed(self.campaign), [])
        self.assertEqual(self.campaign.tasks.count(), 6)

    def test_every_seeded_task_says_where_it_came_from(self):
        """A board full of tasks nobody remembers asking for is one people
        ignore."""
        for task in seed(self.campaign):
            self.assertTrue(task.because)


class BoardAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("board-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه API")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )
        self.campaign = Campaign.objects.create(
            store=self.store, product=self.product, name="کمپین",
        )
        self.client.force_login(self.owner)
        self.base = f"/api/v1/campaigns/{self.campaign.pk}/board/"

    def test_adding_a_task(self):
        response = self.client.post(
            self.base, {"title": "با عکاس تماس بگیر", "kind": "MARKETING"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["kind"], "MARKETING")

    def test_a_task_needs_a_title(self):
        response = self.client.post(self.base, {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_kind_falls_back_rather_than_failing(self):
        response = self.client.post(
            self.base, {"title": "x", "kind": "SPACESHIP"},
            content_type="application/json",
        )
        self.assertEqual(response.json()["kind"], "OTHER")

    def test_seeding_through_the_api(self):
        response = self.client.post(
            self.base, {"seed": True}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()), 7)

    def test_seeding_a_board_that_already_has_tasks_is_refused_with_a_reason(self):
        self.client.post(self.base, {"title": "x"}, content_type="application/json")
        response = self.client.post(
            self.base, {"seed": True}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("پاک کرده‌اید", response.json()["error"]["message"])

    def test_ticking_off_a_job_backed_task_is_refused(self):
        job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION,
            state=Job.State.PROCESSING,
        )
        task = CampaignTask.objects.create(
            campaign=self.campaign, store=self.store, title="ویدیو", job=job,
        )
        response = self.client.patch(
            f"{self.base}{task.pk}/", {"state": "DONE"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "machine_owned")

    def test_the_panel_is_told_which_tasks_it_may_not_edit(self):
        job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION,
            state=Job.State.PROCESSING,
        )
        CampaignTask.objects.create(
            campaign=self.campaign, store=self.store, title="ویدیو", job=job,
        )
        column = next(
            c for c in self.client.get(self.base).json()["columns"]
            if c["tasks"]
        )
        self.assertTrue(column["tasks"][0]["machine_owned"])

    def test_assigning_to_someone_outside_the_store_is_refused(self):
        stranger = User.objects.create_user("board-stranger", password="x")
        task = CampaignTask.objects.create(
            campaign=self.campaign, store=self.store, title="x",
        )
        response = self.client.patch(
            f"{self.base}{task.pk}/", {"assigned_to": stranger.username},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_assigning_to_a_colleague_works(self):
        colleague = User.objects.create_user("board-mate", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.MARKETING,
        )
        task = CampaignTask.objects.create(
            campaign=self.campaign, store=self.store, title="x",
        )
        response = self.client.patch(
            f"{self.base}{task.pk}/", {"assigned_to": colleague.username},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assigned_username"], "board-mate")

    def test_deleting_a_task(self):
        task = CampaignTask.objects.create(
            campaign=self.campaign, store=self.store, title="x",
        )
        self.assertEqual(
            self.client.delete(f"{self.base}{task.pk}/").status_code, 204,
        )

    def test_a_stranger_cannot_see_the_board(self):
        stranger = User.objects.create_user("board-nobody", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.base).status_code, 404)

    def test_a_support_member_cannot_change_the_board(self):
        colleague = User.objects.create_user("board-support", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.SUPPORT,
        )
        self.client.force_login(colleague)
        response = self.client.post(
            self.base, {"title": "x"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

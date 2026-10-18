"""The state machine, and the two moves it exists to prevent.

Those two are worth naming, because everything else here is bookkeeping:

* WAITING_APPROVAL → COMPLETED would charge a customer for output nobody
  approved.
* RENDERING → RENDERING would spend the GPU minutes twice.
"""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.stores.models import Store

from . import machine
from .models import Job


class TableTests(SimpleTestCase):
    def test_the_roadmap_chain_is_walkable_end_to_end(self):
        """ROADMAP §11 phase 20 draws one path. It has to actually exist."""
        chain = [
            machine.QUEUED, machine.PROCESSING, machine.PREVIEW,
            machine.WAITING_APPROVAL, machine.APPROVED, machine.RENDERING,
            machine.QC, machine.COMPLETED,
        ]
        for current, target in zip(chain, chain[1:]):
            self.assertTrue(
                machine.can(current, target),
                f"{current} → {target} باید مجاز باشد",
            )

    def test_approval_cannot_be_skipped(self):
        self.assertFalse(machine.can(machine.WAITING_APPROVAL, machine.COMPLETED))
        self.assertFalse(machine.can(machine.WAITING_APPROVAL, machine.RENDERING))

    def test_a_job_cannot_re_enter_rendering(self):
        self.assertFalse(machine.can(machine.RENDERING, machine.RENDERING))

    def test_anything_can_fail_or_be_cancelled(self):
        for state in (machine.QUEUED, machine.PROCESSING, machine.PREVIEW,
                      machine.WAITING_APPROVAL, machine.APPROVED,
                      machine.RENDERING, machine.QC):
            self.assertTrue(machine.can(state, machine.FAILED))
            self.assertTrue(machine.can(state, machine.CANCELLED))

    def test_nothing_leaves_a_terminal_state(self):
        for state in machine.TERMINAL:
            self.assertEqual(machine.allowed(state), frozenset())
            self.assertFalse(machine.can(state, machine.PROCESSING))
            self.assertFalse(machine.can(state, machine.CANCELLED))

    def test_waiting_for_a_human_does_not_count_as_holding_hardware(self):
        """Counting a parked job as GPU-busy would idle the card for as long as
        the owner is at lunch."""
        self.assertNotIn(machine.WAITING_APPROVAL, machine.BUSY)
        self.assertNotIn(machine.PREVIEW, machine.BUSY)
        self.assertIn(machine.RENDERING, machine.BUSY)

    def test_the_legacy_state_still_works(self):
        """Old rows use RUNNING. Rewriting history to tidy a diagram is how you
        lose the ability to explain last month's invoice."""
        self.assertTrue(machine.can(machine.RUNNING, machine.COMPLETED))
        self.assertTrue(machine.can(machine.QUEUED, machine.RUNNING))

    def test_every_state_has_a_persian_label(self):
        for state in list(machine.ACTIVE) + list(machine.TERMINAL):
            self.assertNotEqual(machine.label(state), state, f"«{state}» ترجمه ندارد")


class AdvanceTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("machine-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه ماشین حالت")

    def _job(self, state=Job.State.QUEUED):
        return Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, state=state,
        )

    def test_a_legal_move_is_saved(self):
        job = self._job()
        job.advance(Job.State.PROCESSING, label="شروع شد")
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.PROCESSING)
        self.assertEqual(job.current_step_label, "شروع شد")

    def test_an_illegal_move_raises_and_changes_nothing(self):
        job = self._job(Job.State.WAITING_APPROVAL)
        with self.assertRaises(machine.IllegalTransition):
            job.advance(Job.State.COMPLETED)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.WAITING_APPROVAL)

    def test_the_preview_payload_travels_with_the_move(self):
        job = self._job(Job.State.PROCESSING)
        job.advance(Job.State.PREVIEW, preview={"segment_index": 1})
        job.refresh_from_db()
        self.assertEqual(job.preview["segment_index"], 1)

    def test_awaiting_human_is_derived_not_guessed(self):
        self.assertTrue(self._job(Job.State.WAITING_APPROVAL).awaiting_human)
        self.assertFalse(self._job(Job.State.RENDERING).awaiting_human)

    def test_cancel_request_is_a_flag_a_worker_can_read(self):
        """A Celery task cannot be killed reliably, so it has to be asked."""
        job = self._job(Job.State.PROCESSING)
        self.assertTrue(job.request_cancel("لغو شد"))
        self.assertTrue(job.cancel_pending())

    def test_a_finished_job_cannot_be_asked_to_stop(self):
        job = self._job(Job.State.COMPLETED)
        self.assertFalse(job.request_cancel())
        self.assertFalse(job.cancel_pending())

    def test_default_mode_is_the_cautious_one(self):
        """A shop owner's first video should fail after five seconds of GPU,
        not after forty."""
        self.assertEqual(self._job().mode, Job.Mode.SAFE)


class RestartSurvivalTests(TestCase):
    """A job waiting for a person must survive a server restart.

    `reap_on_start` sweeps non-terminal jobs in synchronous mode, on the
    reasoning that their worker died with the process. A parked job has no
    worker *by design* — it is waiting for a human, and approving it dispatches
    fresh work. Sweeping it throws away a finished five-second render and the
    approval its owner was about to give.
    """

    def setUp(self):
        owner = User.objects.create_user("restart-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه ری‌استارت")

    def _job(self, state):
        return Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, state=state,
        )

    def test_a_parked_job_survives(self):
        from django.test import override_settings

        from . import staleness

        parked = self._job(Job.State.WAITING_APPROVAL)
        preview = self._job(Job.State.PREVIEW)

        with override_settings(CELERY_TASK_ALWAYS_EAGER=True):
            staleness.reap_on_start()

        parked.refresh_from_db()
        preview.refresh_from_db()
        self.assertEqual(parked.state, Job.State.WAITING_APPROVAL)
        self.assertEqual(preview.state, Job.State.PREVIEW)

    def test_a_genuinely_orphaned_job_is_still_swept(self):
        """The sweep still has to do its job — an eternal spinner is the bug it
        was written for."""
        from django.test import override_settings

        from . import staleness

        orphan = self._job(Job.State.PROCESSING)

        with override_settings(CELERY_TASK_ALWAYS_EAGER=True):
            staleness.reap_on_start()

        orphan.refresh_from_db()
        self.assertEqual(orphan.state, Job.State.FAILED)

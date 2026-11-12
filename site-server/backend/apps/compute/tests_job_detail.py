# -*- coding: utf-8 -*-
"""۱۴۰۵/۰۸/۲۱ — پس از شبِ ۰۸/۲۰: هر لغو علتش را می‌گوید، کار با شناسه‌اش پیدا می‌شود، خروجی و ورودیِ هر کار در جزئیات است،
و کارهای منتظر فقط به‌اندازهٔ جای خالیِ سرور بیدار می‌شوند و بی‌پایان دوباره پارک نمی‌شوند."""
import types
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from . import park, queue as QV, services as SV
from .models import ComputeJob, ComputeNode


def _job(**kw):
    base = dict(kind="ollama.generate", payload={"model": "qwen3:8b", "prompt": "یک کپشن برای چغر بنویس"}, state="QUEUED")
    base.update(kw)
    return ComputeJob.objects.create(**base)


class CancelReasonTests(TestCase):
    def test_a_cancel_keeps_its_reason(self):
        j = _job()
        SV.cancel(j, "مهلتِ اجرا تمام شد: سرورِ پردازش در ۴۲۰ ثانیه کار را تمام نکرد.")
        j.refresh_from_db()
        self.assertEqual(j.state, "CANCELLED")
        self.assertIn("مهلتِ اجرا", j.message)
        self.assertIn("مهلتِ اجرا", j.error)
        self.assertEqual(QV.status_text(j, ""), "لغو شد — " + j.message)

    def test_without_a_reason_it_is_the_old_text(self):
        j = _job()
        SV.cancel(j)
        j.refresh_from_db()
        self.assertEqual(j.message, "لغو شد")
        self.assertEqual(QV.status_text(j, ""), "لغو شد")

    def test_a_running_job_on_a_live_node_keeps_the_reason_until_the_node_stops(self):
        node = ComputeNode.objects.create(name="gpu-r", last_seen=timezone.now(), capabilities={"ollama": True})
        j = _job(state="RUNNING", node=node, claimed_at=timezone.now())
        SV.cancel(j, "کاربر از «صفِ پردازش» لغو کرد (admin).")
        j.refresh_from_db()
        self.assertTrue(j.cancel_requested)
        self.assertIn("کاربر", j.message)


class SearchAndDetailTests(TestCase):
    def test_find_a_job_by_the_id_the_node_log_prints(self):
        j = _job()
        _job(payload={"prompt": "دیگری"})
        rows = QV.listing(q=str(j.uid)[:8])["jobs"]
        self.assertEqual([r["uid"] for r in rows], [str(j.uid)])
        rows = QV.listing(q="#" + str(j.uid)[:6])["jobs"]
        self.assertIn(str(j.uid), [r["uid"] for r in rows])

    def test_the_row_has_the_id_the_input_and_the_outputs(self):
        j = _job(state="COMPLETED", result={"outputs": [
            {"name": "ollama.json", "path": "out/ollama.json", "size": 812, "media": ""},
            {"name": "frame 1.png", "path": "out/frame 1.png", "size": 20480},
            {"name": "clip.mp4", "size": 900000}]})
        row = QV.listing(state="all")["jobs"][0]
        self.assertEqual(row["short_id"], str(j.uid)[:8])
        self.assertEqual(row["input"]["model"], "qwen3:8b")
        self.assertIn("چغر", row["input"]["text"])
        self.assertEqual([(o["name"], o["media"]) for o in row["outputs"]],
                         [("ollama.json", "text"), ("frame 1.png", "image"), ("clip.mp4", "video")])
        self.assertEqual(row["outputs"][1]["url"], "/api/v1/compute/jobs/%s/outputs/frame%%201.png" % j.uid)

    def test_chat_style_input(self):
        j = _job(payload={"model": "qwen3-vl:30b", "messages": [{"role": "system", "content": "s"},
                                                                 {"role": "user", "content": "این عکس را تحلیل کن"}]})
        self.assertEqual(QV.job_input(j)["text"], "این عکس را تحلیل کن")


class WakeAndRoundsTests(TestCase):
    def test_free_slots_of_an_online_single_slot_server(self):
        ComputeNode.objects.create(name="gpu-1", last_seen=timezone.now(), capabilities={"ollama": True, "slots": 1})
        self.assertEqual(park._free_slots("ollama", {}), 1)
        _job()                                               # one already waiting for the server
        self.assertEqual(park._free_slots("ollama", {}), 0)
        ComputeJob.objects.create(kind=park.PARK_KIND, payload={"capability": "ollama"}, state="QUEUED")
        self.assertEqual(park._free_slots("ollama", {}), 0)  # a parked placeholder is not a running job

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_a_job_gives_up_after_too_many_busy_rounds(self):
        node = ComputeNode.objects.create(name="gpu-2", last_seen=timezone.now(), capabilities={"ollama": True})
        created = timezone.now()
        fake = types.SimpleNamespace(pk=7, created_at=created, store=None, cancel_pending=lambda: False,
                                     context={"node_wait": {"busy_rounds": park.MAX_BUSY_ROUNDS,
                                                            "rounds_for": created.isoformat()}},
                                     get_type_display=lambda: "x")
        err = RuntimeError("busy")
        err.node_waiting = "ollama"
        task = types.SimpleNamespace(name="t", request=types.SimpleNamespace(args=(), kwargs={}, delivery_info={}, id="1",
                                                                              called_directly=False))
        with mock.patch.object(park, "_current_task", return_value=task), \
                mock.patch.object(SV, "known_nodes", return_value=[node]), \
                mock.patch.object(SV, "online_nodes", return_value=[node]):
            self.assertFalse(park.maybe_park(fake, err))
        self.assertIn("پشتِ سرِ هم", fake._park_note)


class SingleSlotWakeTests(TestCase):
    def test_a_single_slot_server_gets_one_waiting_job_at_a_time(self):
        from django.contrib.auth import get_user_model
        from apps.jobs.models import Job
        from apps.stores.models import Store
        user = get_user_model().objects.create_user("owner-ss", "ss@x.io", "pw")
        store = Store.objects.create(owner=user, name="shop-ss")
        ComputeNode.objects.create(name="gpu-ss", capabilities={"ollama": True, "slots": 1}, last_seen=timezone.now())
        for _ in range(5):
            row = Job.objects.create(store=store, type=Job.Type.IMAGE_GENERATION, state="QUEUED")
            ComputeJob.objects.create(kind=park.PARK_KIND, state="QUEUED", queued_at=timezone.now(), timeout_s=0, request_hash="",
                                      payload={"capability": "ollama", "task": "t", "args": [row.pk], "kwargs": {},
                                               "ref": {"model": "jobs.Job", "id": row.pk}})
        with mock.patch.object(park, "_dispatch", return_value=True):
            self.assertEqual(park.wake_parked(), 1, "یک جا ⇒ یک کار")
        _job()                                                  # the woken one is now waiting for the server
        with mock.patch.object(park, "_dispatch", return_value=True):
            self.assertEqual(park.wake_parked(), 0, "تا جای خالی نشده، بقیه منتظر می‌مانند (نه لغو و پارکِ دوباره)")

"""زمان‌بندیِ دانلودها (۱۴۰۵/۰۸): parser ِ `when`، دانلودِ مدلِ هوش مصنوعی و مدل‌های صدا با زمان، رعایتِ زمان در claim،
و کلیدهای تازهٔ heartbeat/claim برای عامل. هیچ‌چیز به گره یا اینترنتِ واقعی وصل نمی‌شود."""
import shutil
import tempfile
from datetime import datetime, timedelta, timezone as dt_tz
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from services.ai import model_pull

from . import queue as QV
from . import schedule, services as SV
from . import voice_models as vm
from .models import ComputeJob, ComputeNode, ComputeSettings

GEMMA = "gemma3:12b"


def at_tehran(hour, minute=0, day=0):
    """لحظهٔ UTC ای که ساعتِ دیواریِ تهران آن لحظه hour:minute است (روزِ ثابت، برای آزمونِ بی‌ابهام)."""
    base = datetime(2026, 11, 7, hour, minute, tzinfo=dt_tz.utc) + timedelta(days=day)
    return base - SV.TEHRAN_OFFSET


class Cfg:
    def __init__(self, mode="now", window="02:00-07:00"):
        self.download_mode, self.download_window = mode, window


# ───────────────────────────── parser

class ParserTests(SimpleTestCase):
    NOW = at_tehran(14, 5)

    def test_default_follows_the_global_setting(self):
        self.assertEqual(schedule.schedule_from_when(None, Cfg("now"), self.NOW), {"not_before": None, "window": ""})
        self.assertEqual(schedule.schedule_from_when({"mode": "default"}, Cfg("now"), self.NOW), {"not_before": None, "window": ""})
        self.assertEqual(schedule.schedule_from_when("", Cfg("window", "01:30-06:00"), self.NOW),
                         {"not_before": None, "window": "01:30-06:00"})
        self.assertEqual(schedule.schedule_from_when({"mode": "default"}, Cfg("window"), self.NOW)["window"], "02:00-07:00")

    def test_a_broken_global_window_never_blocks_downloads(self):
        self.assertEqual(schedule.schedule_from_when(None, Cfg("window", "garbage"), self.NOW)["window"], schedule.DEFAULT_WINDOW)
        self.assertEqual(schedule.schedule_from_when({"mode": "window"}, Cfg("now", ""), self.NOW)["window"], schedule.DEFAULT_WINDOW)

    def test_now_ignores_the_global_window(self):
        self.assertEqual(schedule.schedule_from_when({"mode": "now"}, Cfg("window"), self.NOW), {"not_before": None, "window": ""})
        self.assertEqual(schedule.schedule_from_when("now", Cfg("window"), self.NOW), {"not_before": None, "window": ""})

    def test_at_is_the_next_clock_time_in_tehran(self):
        r = schedule.schedule_from_when({"mode": "at", "time": "15:30"}, Cfg(), self.NOW)
        self.assertEqual((r["not_before"], r["window"]), (at_tehran(15, 30), ""))
        tomorrow = schedule.schedule_from_when({"mode": "at", "time": "03:30"}, Cfg(), self.NOW)["not_before"]
        self.assertEqual(tomorrow, at_tehran(3, 30, day=1))                      # ساعتِ امروز گذشته ⇒ فردا
        same = schedule.schedule_from_when({"mode": "at", "time": "14:05"}, Cfg(), self.NOW)["not_before"]
        self.assertEqual(same, at_tehran(14, 5, day=1))                           # دقیقاً همین لحظه ⇒ فردا، نه «گذشته»
        self.assertEqual(schedule.schedule_from_when("03:30", Cfg(), self.NOW)["not_before"], at_tehran(3, 30, day=1))

    def test_at_accepts_persian_and_arabic_digits(self):
        self.assertEqual(schedule.schedule_from_when({"mode": "at", "time": "۱۵:۳۰"}, Cfg(), self.NOW)["not_before"], at_tehran(15, 30))
        self.assertEqual(schedule.schedule_from_when({"mode": "at", "time": "١٥:٣٠"}, Cfg(), self.NOW)["not_before"], at_tehran(15, 30))

    def test_window_uses_the_global_window_or_its_own(self):
        self.assertEqual(schedule.schedule_from_when({"mode": "window"}, Cfg("now", "03:00-05:00"), self.NOW),
                         {"not_before": None, "window": "03:00-05:00"})
        self.assertEqual(schedule.schedule_from_when({"mode": "window", "window": "22:00-04:00"}, Cfg(), self.NOW)["window"], "22:00-04:00")

    def test_bad_input_gives_persian_validation_errors(self):
        from rest_framework.exceptions import ValidationError
        for bad, hint in (({"mode": "at"}, "ساعتِ شروع"), ({"mode": "at", "time": "25:00"}, "ساعت را مثل"),
                          ({"mode": "at", "time": "abc"}, "ساعت را مثل"), ({"mode": "at", "time": "12:61"}, "ساعت را مثل"),
                          ({"mode": "later"}, "درست انتخاب"), ({"mode": "window", "window": "7-8"}, "بازه را مثل"),
                          ({"mode": "window", "window": "07:00-07:00"}, "بازه را مثل"), (["x"], "درست انتخاب"), (5, "درست انتخاب")):
            with self.assertRaises(ValidationError, msg=repr(bad)) as cm:
                schedule.schedule_from_when(bad, Cfg(), self.NOW)
            self.assertIn(hint, cm.exception.message, repr(bad))

    def test_text_says_when_it_starts(self):
        now = self.NOW
        self.assertEqual(schedule.schedule_text(None, "", now), "")
        self.assertEqual(schedule.schedule_text(at_tehran(3, 0, day=1), "", now), "زمان‌بندی‌شده — شروع فردا ۰۳:۰۰ (وقتِ تهران)")
        self.assertEqual(schedule.schedule_text(at_tehran(15, 0), "", now), "زمان‌بندی‌شده — شروع امروز ۱۵:۰۰ (وقتِ تهران)")
        self.assertEqual(schedule.schedule_text(None, "02:00-07:00", now), "زمان‌بندی‌شده — شروع فردا ۰۲:۰۰ (وقتِ تهران)")
        self.assertEqual(schedule.schedule_text(None, "02:00-07:00", at_tehran(3, 0)), "")            # بازه الان باز است
        self.assertEqual(schedule.schedule_text(at_tehran(1, 0), "", now), "")                          # زمانش گذشته
        both = schedule.start_moment(at_tehran(1, 0, day=1), "02:00-07:00", now)                       # هر دو شرط: دیرتر
        self.assertEqual(both, at_tehran(2, 0, day=1))
        self.assertEqual(schedule.clock_text(at_tehran(14, 5, day=3), now), "۳ روزِ دیگر، ۱۴:۰۵")

    def test_payload_fields_always_carry_window(self):
        self.assertEqual(schedule.payload_fields({"not_before": None, "window": ""}), {"window": "", "not_before": ""})
        nb = at_tehran(3, 30, day=1)
        self.assertEqual(schedule.payload_fields({"not_before": nb, "window": "02:00-07:00"}),
                         {"window": "02:00-07:00", "not_before": nb.isoformat()})


# ───────────────────────────── دانلودِ مدلِ هوش مصنوعی

class Base(TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="nm-sched-test-")
        self.addCleanup(shutil.rmtree, self.data, True)
        override = override_settings(NM_DATA_DIR=Path(self.data), AI_ROUTE_FORCE=True, IS_TEST=True)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_user("sched-admin", "a@x.ir", "pw-12345", is_staff=True, is_superuser=True)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def pull_node(self, online=True, name="gpu-1"):
        return ComputeNode.objects.create(
            name=name, enabled=True, capabilities={"agent": "2.6", "ollama": True, "ollama_pull": True, "ollama_models": ["qwq:32b"]},
            last_seen=timezone.now() if online else timezone.now() - timedelta(hours=5))

    def voice_node(self, online=True):
        return ComputeNode.objects.create(
            name="vn-1", enabled=True, last_seen=timezone.now() if online else timezone.now() - timedelta(hours=5),
            capabilities={"voice": True, "agent": "2.6", "models": {"running": False, "packages": {
                "moss-tts": {"installed": False, "optional": False, "missing_mb": 15000, "total_mb": 15800}}}})

    def as_node(self, node):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Node " + node.token)
        return c

    def pull(self, **extra):
        return self.api.post("/api/v1/ai/models/pull/", {"tag": GEMMA, **extra}, format="json")


class PullScheduleTests(Base):
    def test_default_global_now_has_no_schedule(self):
        self.pull_node()
        r = self.pull()
        self.assertEqual(r.status_code, 200, r.content)
        job = ComputeJob.objects.get(kind="ollama.pull")
        self.assertIsNone(job.not_before)
        self.assertEqual((job.window, job.category), ("", "download"))
        self.assertEqual((job.payload["window"], job.payload["not_before"]), ("", ""))
        self.assertEqual(r.data["pull"]["scheduled_text"], "")
        self.assertIn("در صف", r.data["pull"]["text"])

    def test_default_follows_a_global_window(self):
        node = self.pull_node()
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "window", "download_window": "01:00-05:00"})
        r = self.pull()
        self.assertEqual(r.status_code, 200, r.content)
        job = ComputeJob.objects.get(kind="ollama.pull")
        self.assertEqual((job.window, job.category, job.payload["window"]), ("01:00-05:00", "download", "01:00-05:00"))
        self.assertIsNone(job.not_before)
        self.assertEqual(r.data["pull"]["window"], "01:00-05:00")
        if not SV.in_window("01:00-05:00"):
            self.assertIn("زمان‌بندی‌شده — شروع", r.data["pull"]["text"])
            self.assertIsNone(SV.claim(node))                                # گره (آنلاین) هم در بسته بودنِ بازه کار را نمی‌گیرد
        # «الان» روی همان دانلودِ منتظر آن را از بازه درمی‌آورد
        r = self.pull(when={"mode": "now"})
        self.assertEqual(ComputeJob.objects.filter(kind="ollama.pull").count(), 1)
        job.refresh_from_db()
        self.assertEqual((job.window, job.payload["window"]), ("", ""))
        self.assertEqual(SV.claim(node).pk, job.pk)

    def test_at_time_sets_not_before_and_the_node_waits_for_it(self):
        node = self.pull_node()
        r = self.pull(when={"mode": "at", "time": "03:30"})
        self.assertEqual(r.status_code, 200, r.content)
        job = ComputeJob.objects.get(kind="ollama.pull")
        self.assertEqual(job.window, "")
        self.assertEqual(job.category, "download")
        t = SV.tehran_now(job.not_before)
        self.assertEqual((t.hour, t.minute), (3, 30))
        self.assertGreater(job.not_before, timezone.now())
        self.assertLessEqual(job.not_before, timezone.now() + timedelta(days=1, minutes=1))
        self.assertEqual(job.payload["not_before"], job.not_before.isoformat())
        self.assertTrue(r.data["pull"]["scheduled_text"].startswith("زمان‌بندی‌شده — شروع "))
        self.assertIn("۰۳:۳۰", r.data["pull"]["scheduled_text"])
        self.assertIn("خودکار شروع می‌شود", r.data["pull"]["text"])
        self.assertIsNone(SV.claim(node), "پیش از زمانش هیچ گره‌ای کار را نمی‌گیرد")
        row = QV.listing("waiting", category="download")["jobs"][0]
        self.assertEqual((row["wait_reason"], row["category"], row["window"]), ("scheduled", "download", ""))
        ComputeJob.objects.filter(pk=job.pk).update(not_before=timezone.now() - timedelta(seconds=1))
        self.assertEqual(SV.claim(node).pk, job.pk)

    def test_window_mode_uses_the_global_window_and_claim_honours_it(self):
        node = self.pull_node()
        now = SV.tehran_now()
        a, b = now + timedelta(hours=2), now + timedelta(hours=3)
        closed = f"{a.hour:02d}:{a.minute:02d}-{b.hour:02d}:{b.minute:02d}"
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "now", "download_window": closed})
        r = self.pull(when={"mode": "window"})
        self.assertEqual(r.status_code, 200, r.content)
        job = ComputeJob.objects.get(kind="ollama.pull")
        self.assertEqual(job.window, closed)
        self.assertIsNone(SV.claim(node))
        self.assertEqual(QV.listing("waiting")["jobs"][0]["wait_reason"], "window")
        c, d = now - timedelta(hours=1), now + timedelta(hours=1)
        ComputeJob.objects.filter(pk=job.pk).update(window=f"{c.hour:02d}:{c.minute:02d}-{d.hour:02d}:{d.minute:02d}")
        self.assertEqual(SV.claim(node).pk, job.pk)

    def test_bad_when_is_a_persian_400_and_creates_nothing(self):
        self.pull_node()
        for bad in ({"mode": "at", "time": "99:99"}, {"mode": "at"}, {"mode": "tomorrow"}):
            r = self.pull(when=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertTrue(r.data["error"])
        self.assertFalse(ComputeJob.objects.filter(kind="ollama.pull").exists())

    def test_asking_again_for_a_running_pull_changes_nothing(self):
        node = self.pull_node()
        self.pull()
        job = ComputeJob.objects.get(kind="ollama.pull")
        SV.claim(node)
        self.pull(when={"mode": "at", "time": "03:30"})
        job.refresh_from_db()
        self.assertEqual(job.state, "CLAIMED")
        self.assertIsNone(job.not_before)

    def test_the_agent_can_pause_for_the_window_and_the_panel_says_so(self):
        node = self.pull_node()
        self.pull(when={"mode": "window"})
        job = ComputeJob.objects.get(kind="ollama.pull")
        ComputeJob.objects.filter(pk=job.pk).update(state="RUNNING", node=node, result={"live": {
            "phase": "window", "done": 100, "total": 1000, "resume_text": "ادامه فردا ۰۲:۰۰"}})
        job.refresh_from_db()
        view = model_pull.job_view(job)
        self.assertIn("منتظرِ بازهٔ دانلود", view["text"])
        self.assertIn("ادامه فردا ۰۲:۰۰", view["text"])


# ───────────────────────────── دانلودِ مدل‌های صدا

class VoiceScheduleTests(Base):
    def url(self, node):
        return f"/api/v1/compute/nodes/{node.pk}/models/download/"

    def test_download_job_carries_the_schedule_and_window_in_the_payload(self):
        node = self.voice_node()
        r = self.api.post(self.url(node), {"packages": ["moss-tts"], "when": {"mode": "at", "time": "04:15"}}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        job = ComputeJob.objects.get(kind="node.models")
        t = SV.tehran_now(job.not_before)
        self.assertEqual((t.hour, t.minute), (4, 15))
        self.assertEqual((job.window, job.category), ("", "download"))
        self.assertEqual(job.payload["packages"], ["moss-tts"])
        self.assertEqual(job.payload["window"], "")
        self.assertEqual(job.payload["not_before"], job.not_before.isoformat())
        sched = r.data["download"]["scheduled"]
        self.assertEqual([s["uid"] for s in sched], [str(job.uid)])
        self.assertIn("۰۴:۱۵", sched[0]["text"])
        self.assertIsNone(SV.claim(node))

    def test_without_when_it_follows_the_global_setting(self):
        node = self.voice_node()
        r = self.api.post(self.url(node), {"packages": ["moss-tts"]}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        job = ComputeJob.objects.get(kind="node.models")
        self.assertEqual((job.window, job.payload["window"], job.category), ("", "", "download"))
        self.assertEqual(r.data["download"]["scheduled"], [])
        ComputeJob.objects.all().delete()
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "window", "download_window": "02:00-07:00"})
        r = self.api.post(self.url(node), {"packages": ["moss-tts"]}, format="json")
        job = ComputeJob.objects.get(kind="node.models")
        self.assertEqual((job.window, job.payload["window"]), ("02:00-07:00", "02:00-07:00"))
        r = self.api.post(self.url(node), {"packages": ["moss-tts"], "when": {"mode": "now"}}, format="json")
        newest = ComputeJob.objects.filter(kind="node.models").order_by("-id").first()
        self.assertEqual((newest.window, newest.payload["window"]), ("", ""))
        self.assertIsNone(newest.not_before)

    def test_bad_when_is_a_400(self):
        node = self.voice_node()
        r = self.api.post(self.url(node), {"packages": ["moss-tts"], "when": {"mode": "at", "time": "7"}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ساعت", r.data["error"])
        self.assertFalse(ComputeJob.objects.filter(kind="node.models").exists())
        with self.assertRaises(vm.VoiceModelsError):
            vm.start_download(node, ["moss-tts"], when={"mode": "nope"})

    def test_card_shows_what_the_agent_says_it_is_waiting_for(self):
        node = self.voice_node()
        until = (timezone.now() + timedelta(hours=5)).isoformat()
        node.capabilities = {**node.capabilities, "models": {**node.capabilities["models"], "waiting": {
            "until": until, "packages": ["moss-tts"], "reason": "window"}}}
        node.save()
        waiting = vm.card(node)["download"]["waiting"]
        self.assertEqual((waiting["reason"], waiting["packages"]), ("window", ["moss-tts"]))
        self.assertIn("بازهٔ شبانه", waiting["text"])
        node.capabilities = {**node.capabilities, "models": {"running": False, "packages": {}, "waiting": {"until": "x"}}}
        node.save()
        self.assertIsNone(vm.card(node)["download"]["waiting"])

    def test_packages_the_agent_holds_for_the_window_count_as_queued(self):
        node = self.voice_node()
        until = (timezone.now() + timedelta(hours=5)).isoformat()
        models = node.capabilities["models"]
        node.capabilities = {**node.capabilities, "models": {**models, "packages": {
            **models["packages"], "fun-inp": {"installed": False, "optional": True, "missing_mb": 4190, "total_mb": 4190}},
            "waiting": {"until": until, "packages": [], "default": True, "reason": "window"}}}
        node.save()
        download = vm.card(node)["download"]
        self.assertEqual(download["queued"], ["moss-tts"], "the default set (not the optional fun-inp) is held")
        node.capabilities = {**node.capabilities, "models": {**node.capabilities["models"], "waiting": {
            "until": until, "packages": ["fun-inp"], "default": False, "reason": "window"}}}
        node.save()
        self.assertEqual(vm.card(node)["download"]["queued"], ["fun-inp"])


# ───────────────────────────── heartbeat / claim

class ControlKeysTests(Base):
    def test_heartbeat_and_claim_carry_the_download_settings_and_site_version(self):
        node = self.voice_node()
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "window", "download_window": "01:30-06:00"})
        c = self.as_node(node)
        with override_settings(NM_VERSION="2.60"):
            hb = c.post("/api/v1/compute/heartbeat/", {}, format="json")
            cl = c.post("/api/v1/compute/claim/", {}, format="json")
        for r in (hb, cl):
            self.assertEqual(r.status_code, 200, r.content)
            d = r.data["downloads"]
            self.assertEqual((d["mode"], d["window"], d["tz_offset_min"]), ("window", "01:30-06:00", 210))
            parsed = datetime.fromisoformat(d["server_time"])
            self.assertLess(abs((parsed - datetime.now(dt_tz.utc)).total_seconds()), 60)
            self.assertEqual(r.data["site_version"], "2.60")
            self.assertIn("desired", r.data)                                 # چیزی از قبل کم نشده
            self.assertIn("auto_switch", r.data)
        self.assertIsNone(cl.data["job"])

    def test_default_settings_are_now(self):
        node = self.voice_node()
        r = self.as_node(node).post("/api/v1/compute/heartbeat/", {}, format="json")
        self.assertEqual((r.data["downloads"]["mode"], r.data["downloads"]["window"]), ("now", "02:00-07:00"))

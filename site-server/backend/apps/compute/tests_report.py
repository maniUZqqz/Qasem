"""«گزارشِ سرورهای پردازش»: نوبت‌های اتصال، نمونه‌های منابع، نگه‌داری (فشرده‌سازی/پاکسازی)، آمارِ کارها، توضیحِ خطا، CSV و دسترسی."""
import csv
import io
import math
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from . import report as RP
from . import services as SV
from . import views_report as VR
from .models import ComputeJob, ComputeNode, ComputeNodeLog, ComputeSettings
from .models_report import ComputeNodeSample, ComputeNodeSession
from .park import PARK_KIND

S = ComputeJob.State
PERSIAN = re.compile(r"[؀-ۿ]")


def mknode(name="gpu-1", **caps):
    return ComputeNode.objects.create(name=name, capabilities=caps, last_seen=timezone.now())


def mkjob(kind="photo.edit", state=S.COMPLETED, node=None, run_s=None, waited_s=None, error="", created=None, **kw):
    now = timezone.now()
    job = ComputeJob.objects.create(kind=kind, state=state, node=node, run_s=run_s, waited_s=waited_s, error=error,
                                    finished_at=now if state in ComputeJob.FINAL else None, **kw)
    if created is not None:
        ComputeJob.objects.filter(pk=job.pk).update(created_at=created, finished_at=created if state in ComputeJob.FINAL else None)
        job.refresh_from_db()
    return job


class ReportCase(TestCase):
    def setUp(self):
        RP.reset_state()
        cache.delete(RP.CACHE_KEY)
        self.staff = get_user_model().objects.create_user("boss", "b@x.io", "pw", is_staff=True)
        self.plain = get_user_model().objects.create_user("pleb", "p@x.io", "pw")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)


# ───────────────────────────────────────────────────────── نوبتِ اتصال

class SessionTests(ReportCase):
    def test_first_heartbeat_opens_a_session_and_the_next_ones_extend_it(self):
        n = mknode(agent="2.6", hostname="PC1", gpu="RTX 3060")
        t0 = timezone.now()
        RP.record_heartbeat(n, now=t0)
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=20))
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=40))
        sessions = list(ComputeNodeSession.objects.filter(node=n))
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual((s.agent, s.hostname, s.gpu), ("2.6", "PC1", "RTX 3060"))
        self.assertIsNone(s.ended_at)
        self.assertEqual(s.started_at, t0)
        self.assertEqual(s.last_beat, t0 + timedelta(seconds=40))

    def test_gap_longer_than_90s_closes_the_session_at_its_last_beat_and_opens_a_new_one(self):
        n = mknode()
        t0 = timezone.now()
        RP.record_heartbeat(n, now=t0)
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=60))
        # دقیقاً ۹۰ ثانیه بعد از آخرین تپش هنوز همان نوبت است؛ ۹۱ ثانیه نه
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=150))
        self.assertEqual(ComputeNodeSession.objects.filter(node=n).count(), 1)
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=241))
        old, new = ComputeNodeSession.objects.filter(node=n).order_by("started_at")
        self.assertEqual(old.ended_at, t0 + timedelta(seconds=150))
        self.assertIsNone(new.ended_at)
        self.assertEqual(new.started_at, t0 + timedelta(seconds=241))

    def test_touch_is_throttled_to_one_write_per_ten_seconds(self):
        n = mknode()
        t0 = timezone.now()
        RP.record_heartbeat(n, now=t0)
        with CaptureQueriesContext(connection) as q:
            RP.record_heartbeat(n, now=t0 + timedelta(seconds=3))      # claim هر چند ثانیه می‌آید
        self.assertEqual(len(q), 0)
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=12))
        self.assertEqual(ComputeNodeSession.objects.get(node=n).last_beat, t0 + timedelta(seconds=12))

    def test_maintenance_closes_silent_sessions_but_not_live_ones(self):
        a, b = mknode("a"), mknode("b")
        now = timezone.now()
        RP.record_heartbeat(a, now=now - timedelta(minutes=10))
        RP.record_heartbeat(b, now=now - timedelta(seconds=20))
        self.assertEqual(RP.close_stale(now), 1)
        sa = ComputeNodeSession.objects.get(node=a)
        self.assertEqual(sa.ended_at, sa.last_beat)
        self.assertIsNone(ComputeNodeSession.objects.get(node=b).ended_at)

    def test_heartbeat_and_claim_api_record_sessions_and_samples(self):
        n = mknode("gpu-api")
        node_client = APIClient()
        node_client.credentials(HTTP_AUTHORIZATION="Node " + n.token)
        r = node_client.post("/api/v1/compute/heartbeat/", {"agent": "2.5", "ram_total_mb": 16000, "ram_free_mb": 4000,
                                                            "vram_used_mb": 3000, "vram_total_mb": 12000, "comfyui": True,
                                                            "disk_free_gb": 120.5, "disk_total_gb": 500, "gpu_util_pct": 33,
                                                            "gpu_temp_c": 61}, format="json")
        self.assertEqual(r.status_code, 200)
        s = ComputeNodeSample.objects.get(node=n)
        self.assertEqual((s.ram_free_mb, s.vram_used_mb, s.disk_free_gb, s.gpu_util_pct, s.gpu_temp_c), (4000, 3000, 120.5, 33, 61))
        self.assertTrue(s.services["comfyui"])
        self.assertEqual(ComputeNodeSession.objects.filter(node=n).count(), 1)
        # heartbeatِ خالی (عامل وقتی چیزی عوض نشده {} می‌فرستد) و claim هم کار می‌کنند و خطا نمی‌دهند
        self.assertEqual(node_client.post("/api/v1/compute/heartbeat/", {}, format="json").status_code, 200)
        self.assertEqual(node_client.post("/api/v1/compute/claim/", {}, format="json").status_code, 200)
        self.assertEqual(ComputeNodeSession.objects.filter(node=n).count(), 1)

    def test_recording_never_raises_even_when_the_tables_are_broken(self):
        n = mknode()
        with mock.patch.object(ComputeNodeSession.objects, "filter", side_effect=RuntimeError("table missing")):
            RP.record_heartbeat(n)                      # بدون خطا
        node_client = APIClient()
        node_client.credentials(HTTP_AUTHORIZATION="Node " + n.token)
        with mock.patch("apps.compute.report._touch_session", side_effect=RuntimeError("boom")):
            self.assertEqual(node_client.post("/api/v1/compute/heartbeat/", {"agent": "2.6"}, format="json").status_code, 200)

    def test_spans_merge_and_uptime(self):
        now = timezone.now()
        h = lambda x: now - timedelta(hours=x)       # noqa: E731
        rows = [(h(10), h(8), h(8)), (h(9), h(7), h(7)), (h(3), h(2), None)]     # دو نوبتِ هم‌پوشان + یک نوبتِ بازِ ساکت
        spans = RP.session_spans(rows, now)
        self.assertEqual([x[2] for x in spans], [False, False, False])
        merged = RP.merge_spans(spans)
        self.assertEqual(len(merged), 2)
        lo, hi = h(12).timestamp(), now.timestamp()
        up = RP.uptime_stats(RP.clip_spans(merged, lo, hi), lo, hi)
        self.assertEqual(up["online_s"], 3 * 3600 + 1 * 3600)
        self.assertAlmostEqual(up["pct"], 33.3, places=1)
        self.assertEqual(up["longest_gap_s"], 4 * 3600)
        # نوبتِ بازِ زنده تا «الان» ادامه دارد
        live = RP.session_spans([(h(1), now - timedelta(seconds=10), None)], now)
        self.assertTrue(live[0][2])
        self.assertAlmostEqual(live[0][1], now.timestamp(), delta=1)


# ───────────────────────────────────────────────────────── نمونه‌های منابع

class SampleTests(ReportCase):
    def test_at_most_one_raw_sample_per_minute_per_node(self):
        n, m = mknode("a"), mknode("b")
        t0 = timezone.now()
        for sec in (0, 20, 40, 59):
            RP.record_heartbeat(n, now=t0 + timedelta(seconds=sec))
        self.assertEqual(ComputeNodeSample.objects.filter(node=n).count(), 1)
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=61))
        self.assertEqual(ComputeNodeSample.objects.filter(node=n).count(), 2)
        RP.record_heartbeat(m, now=t0 + timedelta(seconds=5))
        self.assertEqual(ComputeNodeSample.objects.filter(node=m).count(), 1)

    def test_a_second_process_does_not_double_write(self):
        n = mknode()
        t0 = timezone.now()
        RP.record_heartbeat(n, now=t0)
        RP._LAST_SAMPLE.clear()                           # پردازهٔ دیگر چیزی نمی‌داند ⇒ از پایگاه داده می‌فهمد
        RP.record_heartbeat(n, now=t0 + timedelta(seconds=30))
        self.assertEqual(ComputeNodeSample.objects.filter(node=n).count(), 1)

    def test_junk_values_from_the_node_never_break_or_poison_a_sample(self):
        n = mknode()
        junk = {"ram_free_mb": "abc", "ram_total_mb": True, "vram_used_mb": float("nan"), "vram_total_mb": float("inf"),
                "disk_free_gb": -5, "disk_total_gb": [1], "gpu_util_pct": 250, "gpu_temp_c": {"x": 1}}
        RP.record_heartbeat(n, caps=junk, now=timezone.now())
        s = ComputeNodeSample.objects.get(node=n)
        for f in ("ram_free_mb", "ram_total_mb", "vram_used_mb", "vram_total_mb", "disk_free_gb", "disk_total_gb", "gpu_util_pct", "gpu_temp_c"):
            self.assertIsNone(getattr(s, f), f)
        # متنِ عددی قبول است؛ نامعتبر نه
        vals = RP.sample_values({"ram_free_mb": " 2048 ", "ram_total_mb": "16000", "gpu_util_pct": "nan", "gpu_temp_c": "70.5",
                                 "vram_used_mb": "1e400"})
        self.assertEqual((vals["ram_free_mb"], vals["ram_total_mb"], vals["gpu_temp_c"]), (2048.0, 16000.0, 70.5))
        self.assertIsNone(vals["gpu_util_pct"])
        self.assertIsNone(vals["vram_used_mb"])
        self.assertEqual(RP.sample_values(None)["ram_free_mb"], None)
        self.assertEqual(RP.sample_values("x")["gpu_temp_c"], None)

    def test_old_agent_without_new_fields_still_records(self):
        n = mknode()
        RP.record_heartbeat(n, caps={"agent": "2.4", "ram_total_mb": 8000, "ram_free_mb": 2000}, now=timezone.now())
        s = ComputeNodeSample.objects.get(node=n)
        self.assertEqual(s.ram_free_mb, 2000)
        self.assertIsNone(s.disk_free_gb)
        self.assertIsNone(s.gpu_util_pct)

    def test_percent_helpers_clamp_inconsistent_reports(self):
        self.assertEqual(RP.used_pct(15000, 12000), 100.0)
        self.assertIsNone(RP.used_pct(1, 0))
        self.assertIsNone(RP.used_pct(None, 5))
        self.assertEqual(RP.ram_used_pct(4000, 16000), 75.0)
        self.assertEqual(RP.ram_used_pct(20000, 16000), 0.0)
        self.assertIsNone(RP.ram_used_pct(None, 16000))

    def test_running_jobs_are_counted_on_the_sample(self):
        n = mknode()
        mkjob("comfy.graph", S.RUNNING, node=n)
        mkjob("photo.edit", S.CLAIMED, node=n)
        mkjob("photo.edit", S.QUEUED)
        RP.record_heartbeat(n, now=timezone.now())
        self.assertEqual(ComputeNodeSample.objects.get(node=n).running_jobs, 2)

    def test_downsample_is_bounded_and_averages(self):
        pts = [(1000 + i, float(i % 10)) for i in range(5000)]
        out = RP.downsample(pts, 1000, 6000, buckets=100)
        self.assertLessEqual(len(out), 100)
        self.assertTrue(all(0 <= v <= 9 for _, v in out))
        self.assertEqual(RP.downsample([], 0, 10), [])
        self.assertEqual(RP.downsample([(5, None), (50, 1.0)], 0, 10), [])      # بیرون از بازه و None
        gap = RP.downsample([(1, 1.0), (99, 3.0)], 0, 100, buckets=10)
        self.assertEqual(len(gap), 2)                                           # سطل‌های خالی نقطه ندارند


# ───────────────────────────────────────────────────────── نگه‌داری

def raw(node, at, **kw):
    vals = {"ram_free_mb": 4000.0, "ram_total_mb": 16000.0, "vram_used_mb": 1000.0, "vram_total_mb": 12000.0,
            "disk_free_gb": 100.0, "disk_total_gb": 500.0, "gpu_util_pct": 10.0, "gpu_temp_c": 50.0}
    vals.update(kw)
    return ComputeNodeSample(node=node, at=at, kind="raw", **vals)


def floor15(dt):
    return RP._floor15(dt)


class MaintenanceTests(ReportCase):
    def _old_raw(self, node, hours_ago=60, minutes=45, step=1, base_gpu=10.0):
        start = floor15(timezone.now() - timedelta(hours=hours_ago))
        rows = [raw(node, start + timedelta(minutes=i * step), gpu_util_pct=base_gpu + i, running_jobs=i % 3)
                for i in range(minutes // step)]
        ComputeNodeSample.objects.bulk_create(rows)
        return start

    def test_rollup_turns_old_raw_into_15_minute_averages_and_is_idempotent(self):
        a, b = mknode("a"), mknode("b")
        start = self._old_raw(a)                             # ۴۵ دقیقه = ۳ سطل
        self._old_raw(b, minutes=15)
        recent = timezone.now() - timedelta(hours=1)
        ComputeNodeSample.objects.create(node=a, at=recent, kind="raw", ram_free_mb=1)
        made, removed = RP.rollup(timezone.now())
        self.assertEqual((made, removed), (4, 60))
        rows = list(ComputeNodeSample.objects.filter(kind="15m", node=a).order_by("at"))
        self.assertEqual([r.at for r in rows], [start, start + timedelta(minutes=15), start + timedelta(minutes=30)])
        self.assertAlmostEqual(rows[0].gpu_util_pct, 17.0, places=1)          # میانگینِ ۱۰..۲۴
        self.assertEqual(rows[0].running_jobs, 2)                              # بیشینه
        self.assertEqual(ComputeNodeSample.objects.filter(kind="raw").count(), 1)       # فقط نمونهٔ تازه مانده
        # بار دوم هیچ‌چیز را عوض نمی‌کند
        self.assertEqual(RP.rollup(timezone.now()), (0, 0))
        self.assertEqual(ComputeNodeSample.objects.filter(kind="15m").count(), 4)

    def test_rollup_never_splits_a_bucket_across_batches_and_is_bounded_per_run(self):
        n = mknode()
        start = self._old_raw(n, minutes=60)                  # ۴ سطلِ کامل
        # دستهٔ ۲۰ ردیفی: سطلِ دوم (ردیف‌های ۱۵..۲۹) نیمه‌کاره در دسته می‌افتد و باید به دستهٔ بعد برود
        made, removed = RP.rollup(timezone.now(), batch=20, max_batches=1)
        self.assertEqual((made, removed), (1, 15))
        self.assertEqual(ComputeNodeSample.objects.filter(kind="raw").count(), 45)
        # اجراهای بعدی ادامه می‌دهند؛ نتیجه با اجرای یک‌جا یکی است
        for _ in range(10):
            if RP.rollup(timezone.now(), batch=20, max_batches=1) == (0, 0):
                break
        rows = list(ComputeNodeSample.objects.filter(kind="15m").order_by("at"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(ComputeNodeSample.objects.filter(kind="raw").count(), 0)
        self.assertAlmostEqual(rows[1].gpu_util_pct, 10 + sum(range(15, 30)) / 15, places=1)
        self.assertEqual(rows[0].at, start)

    def test_rollup_keeps_an_existing_15m_row_and_still_removes_the_raw(self):
        n = mknode()
        start = self._old_raw(n, minutes=15)
        ComputeNodeSample.objects.create(node=n, at=start, kind="15m", gpu_util_pct=99.0)
        made, removed = RP.rollup(timezone.now())
        self.assertEqual((made, removed), (0, 15))
        self.assertEqual(ComputeNodeSample.objects.get(kind="15m", node=n).gpu_util_pct, 99.0)

    def test_rollup_respects_its_deadline(self):
        n = mknode()
        self._old_raw(n, minutes=45)
        import time as _t
        self.assertEqual(RP.rollup(timezone.now(), deadline=_t.monotonic() - 1), (0, 0))

    def test_prune_removes_samples_and_closed_sessions_older_than_retention_only(self):
        n = mknode()
        now = timezone.now()
        old, fresh, recent = now - timedelta(days=9), now - timedelta(days=2), now - timedelta(hours=1)
        ComputeNodeSample.objects.bulk_create([raw(n, old), ComputeNodeSample(node=n, at=old, kind="15m"), raw(n, fresh), raw(n, recent)])
        ComputeNodeSession.objects.create(node=n, started_at=old - timedelta(hours=1), last_beat=old, ended_at=old)
        ComputeNodeSession.objects.create(node=n, started_at=fresh, last_beat=fresh, ended_at=fresh)
        ComputeNodeSession.objects.create(node=n, started_at=old, last_beat=now, ended_at=None)        # هنوز باز: می‌ماند
        self.assertEqual(RP.prune(now, 7), (2, 1))
        self.assertEqual(ComputeNodeSample.objects.count(), 2)
        self.assertEqual(ComputeNodeSession.objects.count(), 2)
        self.assertEqual(RP.prune(now, 7), (0, 0))
        # حداقل یک روز نگه داشته می‌شود: ۰ یا منفی همه‌چیز را پاک نمی‌کند
        self.assertEqual(RP.prune(now, 0), (1, 1))
        self.assertEqual(list(ComputeNodeSample.objects.values_list("at", flat=True)), [recent])
        self.assertEqual(ComputeNodeSession.objects.filter(ended_at__isnull=True).count(), 1)

    def test_prune_is_bounded_per_run(self):
        n = mknode()
        old = timezone.now() - timedelta(days=40)
        ComputeNodeSample.objects.bulk_create([raw(n, old + timedelta(seconds=i)) for i in range(50)])
        self.assertEqual(RP.prune(timezone.now(), 30, batch=10, max_batches=2)[0], 20)
        self.assertEqual(ComputeNodeSample.objects.count(), 30)

    def test_maintain_uses_retention_days_setting_and_runs_at_most_every_ten_minutes(self):
        n = mknode()
        now = timezone.now()
        ComputeNodeSample.objects.bulk_create([raw(n, now - timedelta(days=5)), raw(n, now - timedelta(hours=3))])
        cfg = ComputeSettings.get()
        cfg.retention_days = 3
        cfg.save()
        out = RP.maintain(now)
        self.assertEqual(out["samples_pruned"], 1)
        self.assertEqual(ComputeNodeSample.objects.count(), 1)
        self.assertEqual(RP.maintain(now), {"skipped": True})            # ده دقیقه نگذشته
        self.assertNotIn("skipped", RP.maintain(now, force=True))

    def test_maintain_never_raises(self):
        with mock.patch("apps.compute.report.close_stale", side_effect=RuntimeError("db gone")):
            out = RP.maintain(force=True)
        self.assertTrue(out["error"])

    def test_celery_maintenance_task_calls_the_report_maintenance(self):
        from .tasks import maintenance
        out = maintenance()
        self.assertIn("report", out)
        self.assertNotIn("report_error", out)

    def test_growth_is_bounded_for_a_month_of_one_minute_samples(self):
        """۳۰ روز نمونهٔ دقیقه‌ای یک گره ⇒ بعد از نگه‌داری حداکثر ۴۸ ساعت خام + ۱۵ دقیقه‌ای‌ها (نه ۴۳٬۲۰۰ ردیف)."""
        n = mknode()
        now = timezone.now()
        start = floor15(now - timedelta(days=29))
        ComputeNodeSample.objects.bulk_create([raw(n, start + timedelta(minutes=i)) for i in range(0, 29 * 24 * 60, 5)])   # هر ۵ دقیقه، سبک
        for _ in range(10):
            RP.maintain(now, force=True)
        raw_n = ComputeNodeSample.objects.filter(kind="raw").count()
        m15 = ComputeNodeSample.objects.filter(kind="15m").count()
        self.assertLessEqual(raw_n, 48 * 12 + 1)
        self.assertLessEqual(m15, 27 * 96 + 2)
        self.assertEqual(ComputeNodeSample.objects.filter(kind="raw", at__lt=now - timedelta(hours=49)).count(), 0)


# ───────────────────────────────────────────────────────── توضیحِ خطا

EXPLAIN_CASES = [
    ("سرورِ پردازش وسطِ کار بی‌خبر ماند و تلاش‌ها تمام شد.", "lost_node"),
    ("سرورِ پردازشِ gpu-1 وسطِ کار بی‌خبر ماند؛ دوباره در صف", "lost_node"),
    ("lease expired: no heartbeat for 600 s", "lost_node"),
    ("کار بیش از ۱ ساعت منتظرِ روشن شدنِ سرورِ پردازش ماند و مهلتِ انتظار تمام شد.", "wait_limit"),
    ("هیچ سرورِ پردازشی با قابلیتِ «comfyui» آنلاین نیست. روی سرورِ پردازش START.bat را اجرا کنید", "node_offline"),
    ("ComfyUI did not finish within 1800 seconds", "timeout"),
    ("Read timed out. (read timeout=600)", "network"),
    ("job timed out after 1800 s", "timeout"),
    ("ComfyUI is not reachable at http://127.0.0.1:8188: [WinError 10061] No connection could be made because the target machine actively refused it", "comfy_down"),
    ("voice service is not reachable at http://127.0.0.1:5600: [WinError 10061] actively refused", "service_down"),
    ("ComfyUI did not become ready in 120 s; see logs\\service-comfyui.log", "comfy_down"),
    ("ComfyUI execution error: CUDA out of memory. Tried to allocate 2.00 GiB", "gpu_memory"),
    ("torch.cuda.OutOfMemoryError: CUDA out of memory", "gpu_memory"),
    ("ComfyUI rejected the graph (HTTP 400): Value not in list: ckpt_name: 'flux1-dev.safetensors' not in []", "comfy_model"),
    ("DOWNLOADING: the models of video are still being downloaded (3 GB left) - the job is tried again", "models_missing"),
    ("model 'qwen3:8b' not found, try pulling it first (ollama)", "ollama_model"),
    ("pull model manifest: file does not exist", "not_installed"),
    ("Ollama is not running at http://127.0.0.1:11434", "ollama_down"),
    ("OSError: [Errno 28] No space left on device", "disk_full"),
    ("ffmpeg exited with code 1: Invalid data found when processing input", "ffmpeg"),
    ("site unreachable (https://nm.example): <urlopen error [Errno 11001] getaddrinfo failed>", "site_transfer"),
    ("upload failed: HTTP 413 for output.mp4", "site_transfer"),
    ("POST /api/v1/compute/jobs/ab/finish/ -> HTTP 502 Bad Gateway", "site_error"),
    ("HTTP 402 Payment Required: insufficient credit on the Metis account", "credit"),
    ("Cancelled by the panel", "cancelled"),
    ("لغو شد", "cancelled"),
    ("site rejected the node token (HTTP 401). The token was rotated or the node was deleted", "token"),
    ("something nobody ever saw before: 0xDEADBEEF", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
]


class ExplainTests(TestCase):
    def test_every_case_maps_to_the_expected_explanation(self):
        for text, code in EXPLAIN_CASES:
            with self.subTest(text=text):
                got = RP.explain(text)
                self.assertEqual(got["code"], code, text)
                self.assertEqual(got["known"], code != "unknown")

    def test_explanations_are_persian_and_have_advice(self):
        for text, _ in EXPLAIN_CASES:
            got = RP.explain(text)
            self.assertRegex(got["what"], PERSIAN)
            self.assertRegex(got["advice"], PERSIAN)
            self.assertGreater(len(got["advice"]), 10)
        self.assertIn("پشتیبان", RP.explain("zzz")["advice"])

    def test_rule_codes_are_unique_and_unknown_never_in_rules(self):
        codes = [c for c, *_ in RP.EXPLAIN_RULES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn("unknown", codes)

    def test_huge_text_is_handled_fast(self):
        import time
        t = time.monotonic()
        RP.explain("a" * 200_000)
        RP.explain(("ollama " * 20000) + "x")
        self.assertLess(time.monotonic() - t, 1.5)

    def test_technical_names_are_the_only_english_in_the_persian_texts(self):
        allowed = {"ComfyUI", "Ollama", "VRAM", "GPU", "RAM", "START", "bat", "Update", "ffmpeg", "Metis", "AI"}
        for code, _rx, what, advice in RP.EXPLAIN_RULES:
            for word in re.findall(r"[A-Za-z]{2,}", what + " " + advice):
                self.assertIn(word, allowed, f"{code}: {word}")


# ───────────────────────────────────────────────────────── API و آمار

class ReportApiTests(ReportCase):
    def get(self, **params):
        r = self.c.get("/api/v1/compute/report/", params)
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        return r.json()

    def test_endpoints_need_a_staff_user(self):
        plain = APIClient()
        plain.force_authenticate(self.plain)
        for url in ("/api/v1/compute/report/", "/api/v1/compute/report/logs/", "/api/v1/compute/report/export.csv?section=jobs"):
            self.assertIn(APIClient().get(url).status_code, (401, 403), url)
            self.assertEqual(plain.get(url).status_code, 403, url)
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_node_token_cannot_read_the_report(self):
        n = mknode()
        nc = APIClient()
        nc.credentials(HTTP_AUTHORIZATION="Node " + n.token)
        self.assertIn(nc.get("/api/v1/compute/report/").status_code, (401, 403))

    def test_payload_has_every_section_for_a_fresh_install(self):
        data = self.get()
        for key in ("generated_at", "range", "agent_latest", "site_version", "nodes", "jobs", "queue_now", "errors",
                    "error_groups", "downloads", "agent_versions", "logs_note"):
            self.assertIn(key, data)
        self.assertEqual(data["nodes"], [])
        self.assertEqual(data["range"]["days"], 7)
        self.assertEqual(data["range"]["retention_days"], 30)
        self.assertEqual(data["jobs"]["totals"]["count"], 0)
        self.assertEqual(data["jobs"]["totals"]["avg_run_s"], None)

    def test_node_card_has_timeline_resources_models_and_versions(self):
        n = mknode("gpu-1", agent="2.5", hostname="PC1", gpu="RTX 3060", comfyui=True, ollama=False, ram_total_mb=16000, ram_free_mb=4000,
                   vram_used_mb=6000, vram_total_mb=12000, ollama_models=["qwen3:8b", "llama3:8b"], audio={"speech": True, "music": False},
                   models={"packages": {"video": {"title": "ویدیو", "installed": True, "missing_mb": 0, "total_mb": 9000}},
                           "running": False, "error": ""},
                   comfy_models={"checkpoints": ["a.safetensors"]})
        now = timezone.now()
        for k in range(120):
            RP.record_heartbeat(n, now=now - timedelta(minutes=119 - k))        # هر دقیقه یک تپش: یک نوبتِ پیوسته
        RP.reset_state()
        ComputeNodeSample.objects.bulk_create([raw(n, now - timedelta(minutes=k * 10), gpu_util_pct=float(k), ram_free_mb=4000.0 + k * 100) for k in range(1, 7)])
        data = self.get(days=2)
        card = data["nodes"][0]
        self.assertEqual((card["name"], card["agent"], card["gpu"], card["hostname"]), ("gpu-1", "2.5", "RTX 3060", "PC1"))
        self.assertTrue(card["online"])
        self.assertEqual(card["resources"]["ram_used_pct"], 75.0)
        self.assertEqual(card["resources"]["vram_used_pct"], 50.0)
        self.assertEqual(card["models"]["ollama"], ["qwen3:8b", "llama3:8b"])
        self.assertEqual(card["models"]["audio"], {"speech": True, "music": False})
        self.assertEqual(card["models"]["packages"][0]["installed"], True)
        self.assertEqual(card["models"]["comfy_count"], 1)
        self.assertTrue(card["services"]["comfyui"])
        self.assertFalse(card["services"]["ollama"])
        self.assertTrue(card["sessions"][0]["ongoing"])
        self.assertEqual(len(card["segments"]), 1)
        self.assertGreater(card["uptime"]["pct"], 0)
        self.assertTrue(len(card["series"]["gpu_util_pct"]) >= 3)
        self.assertLessEqual(len(card["series"]["gpu_util_pct"]), 240)
        self.assertEqual(card["series"]["gpu_temp_c"][0][1], 50.0)
        self.assertEqual(data["agent_versions"][0]["nodes"], ["gpu-1"])

    def test_stats_exclude_wait_node_placeholders_and_compute_averages(self):
        n1, n2 = mknode("n1"), mknode("n2")
        mkjob("comfy.graph", S.COMPLETED, n1, run_s=100, waited_s=10)
        mkjob("comfy.graph", S.COMPLETED, n1, run_s=300, waited_s=30)
        mkjob("comfy.graph", S.FAILED, n2, run_s=50, waited_s=5, error="CUDA out of memory")
        mkjob("comfy.graph", S.CANCELLED, None)
        mkjob("photo.edit", S.COMPLETED, n2, run_s=20, waited_s=2)
        mkjob("photo.edit", S.QUEUED, None)
        for st in (S.QUEUED, S.COMPLETED, S.FAILED):
            mkjob(PARK_KIND, st, None, run_s=999, waited_s=999)
        data = self.get(days=1)
        kinds = {r["kind"]: r for r in data["jobs"]["per_kind"]}
        self.assertNotIn(PARK_KIND, kinds)
        comfy = kinds["comfy.graph"]
        self.assertEqual((comfy["count"], comfy["success"], comfy["failed"], comfy["cancelled"]), (4, 2, 1, 1))
        self.assertEqual(comfy["avg_run_s"], 200.0)             # فقط تمام‌شده‌ها
        self.assertEqual(comfy["avg_wait_s"], round((10 + 30 + 5) / 3, 1))
        self.assertEqual(comfy["success_rate"], round(100 * 2 / 3, 1))
        self.assertEqual(comfy["kind_label"], "تولیدِ تصویر یا ویدیو (ComfyUI)")
        self.assertEqual((comfy["p50_run_s"], comfy["p95_run_s"]), (100.0, 300.0))
        self.assertEqual(kinds["photo.edit"]["waiting"], 1)
        self.assertEqual(data["jobs"]["totals"]["count"], 6)
        self.assertEqual(data["queue_now"]["waiting"], 1)       # «wait.node»ها در صفِ زنده هم نیستند
        by_node = {x["name"]: x for x in data["nodes"]}
        self.assertEqual(by_node["n1"]["jobs"]["count"], 2)
        self.assertEqual(by_node["n2"]["jobs"]["failed"], 1)
        self.assertEqual({r["kind"]: r["count"] for r in by_node["n2"]["jobs_by_kind"]}, {"comfy.graph": 1, "photo.edit": 1})
        # فیلترِ سرور
        only = self.get(days=1, node=n1.pk)
        self.assertEqual(only["jobs"]["totals"]["count"], 2)
        self.assertEqual([x["name"] for x in only["nodes"]], ["n1"])

    def test_date_range_filters_jobs_errors_and_logs(self):
        n = mknode()
        today = timezone.now()
        mkjob("echo", S.COMPLETED, n, run_s=1)
        mkjob("echo", S.COMPLETED, n, run_s=1, created=today - timedelta(days=3))
        mkjob("echo", S.FAILED, n, error="boom", created=today - timedelta(days=10))
        self.assertEqual(self.get(days=1)["jobs"]["totals"]["count"], 1)
        self.assertEqual(self.get(days=7)["jobs"]["totals"]["count"], 2)
        self.assertEqual(self.get(days=30)["jobs"]["totals"]["count"], 3)
        self.assertEqual(len(self.get(days=7)["errors"]), 0)
        self.assertEqual(len(self.get(days=30)["errors"]), 1)
        # بازهٔ دلخواه (وقتِ تهران، شاملِ روزِ پایان)
        day = lambda d: SV.tehran_now(today - timedelta(days=d)).date().isoformat()          # noqa: E731
        got = self.get(**{"from": day(4), "to": day(2)})
        self.assertEqual(got["jobs"]["totals"]["count"], 1)
        self.assertEqual(got["range"]["days"], 3)
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="old")
        ComputeNodeLog.objects.filter(message="old").update(created_at=today - timedelta(days=20))
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="new")
        self.assertEqual([e["short"] for e in self.get(days=7)["errors"]], ["new"])

    def test_bad_ranges_are_rejected_with_a_persian_message(self):
        today = SV.tehran_now().date()
        for params in ({"from": "2026-13-45"}, {"to": "abc"}, {"from": "۱۴۰۵/۰۸/۰۱"}, {"days": "x"}, {"days": "0"}, {"days": "91"},
                       {"from": (today - timedelta(days=120)).isoformat()}, {"from": today.isoformat(), "to": (today - timedelta(days=2)).isoformat()},
                       {"from": (today + timedelta(days=3)).isoformat()}, {"node": "abc"}):
            r = self.c.get("/api/v1/compute/report/", params)
            self.assertEqual(r.status_code, 400, params)
            self.assertRegex(str(r.json()), PERSIAN)
        self.assertEqual(self.c.get("/api/v1/compute/report/", {"node": 99999}).status_code, 400)
        # «to» در آینده به امروز می‌رسد
        ok = self.get(**{"from": today.isoformat(), "to": (today + timedelta(days=5)).isoformat()})
        self.assertEqual(ok["range"]["to"], today.isoformat())

    def test_errors_list_explains_failed_jobs_and_error_logs_but_not_info_logs(self):
        n = mknode()
        mkjob("comfy.graph", S.FAILED, n, error="ComfyUI execution error: CUDA out of memory")
        mkjob("voice.tts", S.FAILED, n, error="")
        mkjob("echo", S.COMPLETED, n)
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="OSError: No space left on device")
        ComputeNodeLog.objects.create(node=n, level="CRITICAL", message="boom")
        ComputeNodeLog.objects.create(node=n, level="INFO", message="heartbeat ok")
        ComputeNodeLog.objects.create(node=n, level="WARNING", message="slow disk")
        data = self.get(days=1)
        errs = data["errors"]
        self.assertEqual(len(errs), 4)
        by_short = {e["short"]: e for e in errs}
        self.assertEqual(by_short["ComfyUI execution error: CUDA out of memory"]["explain"]["code"], "gpu_memory")
        self.assertIn("CUDA out of memory", by_short["ComfyUI execution error: CUDA out of memory"]["text"])      # متنِ خام می‌ماند
        self.assertEqual(by_short["OSError: No space left on device"]["explain"]["code"], "disk_full")
        self.assertEqual(by_short["OSError: No space left on device"]["source"], "log")
        self.assertEqual(by_short["خطای نامشخص"]["explain"]["known"], False)
        self.assertTrue(all(e["explain"]["advice"] for e in errs))
        self.assertEqual({g["code"]: g["count"] for g in data["error_groups"]}, {"unknown": 2, "gpu_memory": 1, "disk_full": 1})
        self.assertEqual(data["error_groups"][0]["code"], "unknown")

    def test_logs_endpoint_filters_and_pages(self):
        a, b = mknode("a"), mknode("b")
        for i in range(7):
            ComputeNodeLog.objects.create(node=a, level="ERROR" if i % 2 == 0 else "INFO", message=f"line {i} on a")
        ComputeNodeLog.objects.create(node=b, level="WARNING", message="slow disk on b")
        ComputeNodeLog.objects.create(node=b, level="ERROR", message="CUDA out of memory on b")
        get = lambda **p: self.c.get("/api/v1/compute/report/logs/", p).json()            # noqa: E731
        self.assertEqual(get()["total"], 9)
        self.assertEqual(get(node=a.pk)["total"], 7)
        self.assertEqual(get(level="error")["total"], 5)
        self.assertEqual(get(level="warning")["total"], 1)
        self.assertEqual(get(q="slow")["total"], 1)
        self.assertEqual(get(q="LINE 3")["total"], 1)               # بی‌توجه به بزرگی و کوچکیِ حرف
        page1, page2 = get(limit=4, offset=0), get(limit=4, offset=4)
        self.assertEqual((len(page1["lines"]), len(page2["lines"]), page1["total"]), (4, 4, 9))
        self.assertEqual(len({x["id"] for x in page1["lines"]} | {x["id"] for x in page2["lines"]}), 8)
        err = [x for x in get(level="error")["lines"] if "CUDA" in x["message"]][0]
        self.assertEqual(err["explain"]["code"], "gpu_memory")
        self.assertIsNone([x for x in get(level="info")["lines"]][0]["explain"])
        self.assertEqual(get(limit=99999)["limit"], 500)              # سقف
        self.assertEqual(get(**{"from": "2000-01-01", "to": "2000-01-02"})["total"], 0)
        self.assertEqual(get(days=1)["total"], 9)
        self.assertEqual(self.c.get("/api/v1/compute/report/logs/", {"from": "bad"}).status_code, 400)

    def test_downloads_in_progress_history_and_scheduled(self):
        n = mknode("gpu-1", models={"running": True, "packages": {}, "progress": {
            "packages": ["video"], "bytes_done": 500, "bytes_total": 2000, "items_done": 1, "items_total": 4,
            "current": "wan2.2-14b", "current_done": 50, "current_total": 100}})
        m = mknode("gpu-2", models={"running": True, "progress": {"bytes_done": "x", "bytes_total": {"a": 1}, "current": {"id": "a", "title": "T", "done": "?", "total": 10},
                                                                    "failed": [{"id": "z", "reason": "no_progress"}, "junk"], "packages": "oops"}})
        pull = mkjob("ollama.pull", S.RUNNING, n, category="download", payload={"model": "qwen3:8b"})
        ComputeJob.objects.filter(pk=pull.pk).update(result={"live": {"done": 100_000_000, "total": 400_000_000, "speed_mbs": 2, "phase": "pulling", "attempt": 1, "max_attempts": 3}})
        junk = mkjob("ollama.pull", S.RUNNING, m, category="download", payload={"model": "x"})
        ComputeJob.objects.filter(pk=junk.pk).update(result={"live": {"done": "abc", "total": [1], "speed_mbs": "fast", "attempt": {}}})
        mkjob("node.models", S.COMPLETED, n, run_s=60, payload={"packages": ["video"]})
        mkjob("ollama.pull", S.FAILED, n, error="no space left on device", category="download", payload={"model": "big"})
        sched = mkjob("ollama.pull", S.COMPLETED, n, category="download", run_s=100, payload={"model": "nightly"},
                      not_before=timezone.now() - timedelta(hours=5), window="02:00-07:00")
        waiting = mkjob("ollama.pull", S.QUEUED, None, category="download", payload={"model": "later"},
                        not_before=timezone.now() + timedelta(hours=5), window="02:00-07:00")
        mkjob(PARK_KIND, S.COMPLETED, None, category="download")
        mkjob("photo.edit", S.COMPLETED, n)
        data = self.get(days=1)["downloads"]
        titles = [a["title"] for a in data["active"]]
        self.assertIn("دانلودِ مدلِ qwen3:8b", titles)
        pull_item = [a for a in data["active"] if a["title"] == "دانلودِ مدلِ qwen3:8b"][0]
        self.assertEqual((pull_item["percent"], pull_item["bytes_done"], pull_item["eta_s"]), (25.0, 100_000_000.0, 150))
        self.assertEqual(pull_item["speed_bps"], 2_000_000.0)
        node_item = [a for a in data["active"] if a["source"] == "node" and a["node"] == "gpu-1"][0]
        self.assertEqual((node_item["percent"], node_item["items_done"], node_item["message"], node_item["current_done"]), (25.0, 1.0, "wan2.2-14b", 50.0))
        junk_node = [a for a in data["active"] if a["source"] == "node" and a["node"] == "gpu-2"][0]
        self.assertIsNone(junk_node["percent"])
        self.assertEqual(junk_node["message"], "T")
        self.assertEqual(junk_node["failed"][0], "z: no_progress")
        junk_job = [a for a in data["active"] if a["uid"] == str(junk.uid)][0]
        self.assertIsNone(junk_job["percent"])
        self.assertIsNone(junk_job["speed_bps"])
        self.assertEqual([w["uid"] for w in data["waiting"]], [str(waiting.uid)])
        self.assertEqual(data["waiting"][0]["window"], "02:00-07:00")
        hist = {h["uid"]: h for h in data["history"]}
        self.assertIn(str(sched.uid), hist)
        self.assertEqual(hist[str(sched.uid)]["window"], "02:00-07:00")
        self.assertTrue(hist[str(sched.uid)]["scheduled_for"])
        failed = [h for h in data["history"] if h["state"] == "FAILED"][0]
        self.assertEqual(failed["explain"], RP.explain("no space left")["what"])
        self.assertEqual(len([h for h in data["history"] if h["kind"] == "photo.edit"]), 0)
        self.assertFalse([h for h in data["history"] if h["kind"] == PARK_KIND])

    def test_junk_in_node_capabilities_never_breaks_the_report(self):
        for i, caps in enumerate((
            {"ram_total_mb": "x", "ram_free_mb": [], "vram_total_mb": {"a": 1}, "ollama_models": "qwen", "audio": [1], "comfy_models": [1],
             "models": "none", "agent": {"a": 1}, "gpu": 5, "hostname": None, "code": "x"},
            {"models": {"packages": [1, 2], "progress": [], "running": True}, "ollama_models": [None, 5, "ok"], "comfy_models": {"a": "b", "c": [1, None]}},
            {"models": {"packages": {"p": "x", "q": {"title": None, "missing_mb": "ten", "total_mb": "n/a"}}, "running": 1, "progress": {"current": 5}}},
        )):
            mknode(f"junk-{i}", **caps)
        data = self.get(days=1)
        self.assertEqual(len(data["nodes"]), 3)
        self.assertEqual(self.c.get("/api/v1/compute/nodes/").status_code, 200)

    def test_no_n_plus_one_when_nodes_and_rows_grow(self):
        def build(k):
            n = mknode(f"n{k}", ollama_models=["a"], models={"running": True, "progress": {"bytes_done": 1, "bytes_total": 2}})
            RP.record_heartbeat(n, now=timezone.now() - timedelta(minutes=5))
            mkjob("comfy.graph", S.FAILED, n, error="x")
            mkjob("photo.edit", S.COMPLETED, n, run_s=3, waited_s=1)
            ComputeNodeLog.objects.create(node=n, level="ERROR", message="e")
        build(1)
        build(2)
        self.get(days=7)
        with CaptureQueriesContext(connection) as small:
            self.get(days=7)
        for k in range(3, 9):
            build(k)
        with CaptureQueriesContext(connection) as big:
            self.get(days=7)
        self.assertLessEqual(len(big), len(small) + 2, [q["sql"][:80] for q in big.captured_queries][len(small):])
        self.assertLess(len(big), 45)

    def test_retention_setting_roundtrip_through_the_existing_settings_api(self):
        r = self.c.post("/api/v1/compute/settings/", {"retention_days": 45}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.get()["range"]["retention_days"], 45)
        self.assertEqual(self.c.post("/api/v1/compute/settings/", {"retention_days": 0}, format="json").status_code, 400)
        self.assertEqual(self.c.post("/api/v1/compute/settings/", {"retention_days": 999}, format="json").status_code, 400)


# ───────────────────────────────────────────────────────── CSV

def parse_csv(response):
    raw = b"".join(response.streaming_content)
    text = raw.decode("utf-8")
    return raw, list(csv.reader(io.StringIO(text.lstrip("﻿"))))


class CsvTests(ReportCase):
    def fetch(self, **params):
        r = self.c.get("/api/v1/compute/report/export.csv", params)
        self.assertEqual(r.status_code, 200, getattr(r, "content", b"")[:200])
        return r

    def test_csv_is_utf8_with_bom_persian_headers_and_attachment_name(self):
        n = mknode()
        mkjob("comfy.graph", S.FAILED, n, run_s=12.5, waited_s=2, error="CUDA out of memory")
        r = self.fetch(section="jobs", days=1)
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertTrue(re.search(r'filename="compute-jobs-\d{4}-\d\d-\d\d-\d{4}-\d\d-\d\d\.csv"', r["Content-Disposition"]))
        raw, rows = parse_csv(r)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(rows[0][0], "شناسه")
        self.assertIn("زمانِ اجرا (ثانیه)", rows[0])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "تولیدِ تصویر یا ویدیو (ComfyUI)")
        self.assertEqual(rows[1][3], "ناموفق")
        self.assertIn("12.5", rows[1])
        self.assertIn("CUDA out of memory", rows[1][-1])
        self.assertEqual(len(rows[1]), len(rows[0]))

    def test_every_section_downloads_and_has_a_persian_header(self):
        n = mknode()
        RP.record_heartbeat(n, caps={"ram_total_mb": 100, "ram_free_mb": 50}, now=timezone.now())
        mkjob("ollama.pull", S.COMPLETED, n, run_s=5, category="download", payload={"model": "m"})
        mkjob("echo", S.FAILED, n, error="boom")
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="bad thing")
        for section in ("jobs", "sessions", "samples", "logs", "errors", "downloads"):
            raw, rows = parse_csv(self.fetch(section=section, days=1))
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), section)
            self.assertRegex(rows[0][0], PERSIAN, section)
            self.assertGreaterEqual(len(rows), 2, section)
            for row in rows[1:]:
                self.assertEqual(len(row), len(rows[0]), section)

    def test_samples_and_sessions_csv_content(self):
        n = mknode("gpu-1", agent="2.5")
        RP.record_heartbeat(n, caps={"agent": "2.5", "ram_total_mb": 16000, "ram_free_mb": 4000, "gpu_util_pct": 40}, now=timezone.now())
        _, rows = parse_csv(self.fetch(section="samples", days=1))
        self.assertEqual(rows[1][0], "gpu-1")
        self.assertEqual(rows[1][2], "خام")
        self.assertIn("4000", rows[1])      # عددِ صحیح بی «.۰»
        _, rows = parse_csv(self.fetch(section="sessions", days=1))
        self.assertEqual((rows[1][0], rows[1][4], rows[1][5]), ("gpu-1", "بله", "2.5"))

    def test_formula_injection_is_neutralised(self):
        n = mknode()
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="=HYPERLINK(\"http://evil\",\"x\")")
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="-2+3")
        _, rows = parse_csv(self.fetch(section="logs", days=1))
        msgs = {r[3] for r in rows[1:]}
        self.assertIn("'=HYPERLINK(\"http://evil\",\"x\")", msgs)
        self.assertIn("'-2+3", msgs)

    def test_row_cap_adds_a_persian_truncation_note(self):
        n = mknode()
        for i in range(6):
            mkjob("echo", S.COMPLETED, n, run_s=i)
        with mock.patch.object(VR, "MAX_CSV_ROWS", 4):
            _, rows = parse_csv(self.fetch(section="jobs", days=1))
        self.assertEqual(len(rows), 1 + 4 + 1)
        self.assertIn("فقط", rows[-1][0])
        self.assertRegex(rows[-1][0], PERSIAN)
        with mock.patch.object(VR, "MAX_CSV_ROWS", 6):
            _, rows = parse_csv(self.fetch(section="jobs", days=1))
        self.assertEqual(len(rows), 1 + 6)                       # دقیقاً سقف ⇒ یادداشت لازم نیست

    def test_csv_excludes_wait_node_and_respects_range_and_node(self):
        a, b = mknode("a"), mknode("b")
        mkjob("echo", S.COMPLETED, a)
        mkjob("echo", S.COMPLETED, b)
        mkjob(PARK_KIND, S.COMPLETED, a)
        mkjob("echo", S.COMPLETED, a, created=timezone.now() - timedelta(days=5))
        _, rows = parse_csv(self.fetch(section="jobs", days=1))
        self.assertEqual(len(rows) - 1, 2)
        _, rows = parse_csv(self.fetch(section="jobs", days=1, node=a.pk))
        self.assertEqual(len(rows) - 1, 1)
        _, rows = parse_csv(self.fetch(section="jobs", days=7))
        self.assertEqual(len(rows) - 1, 3)

    def test_bad_section_or_range_is_a_persian_400(self):
        for params in ({"section": "nope"}, {}, {"section": "jobs", "days": "x"}, {"section": "jobs", "from": "zzz"}):
            r = self.c.get("/api/v1/compute/report/export.csv", params)
            self.assertEqual(r.status_code, 400, params)
            self.assertRegex(str(r.json()), PERSIAN)

    def test_csv_log_export_honours_the_log_filters(self):
        n = mknode()
        ComputeNodeLog.objects.create(node=n, level="ERROR", message="alpha failure")
        ComputeNodeLog.objects.create(node=n, level="INFO", message="alpha ok")
        _, rows = parse_csv(self.fetch(section="logs", days=1, level="error"))
        self.assertEqual([r[3] for r in rows[1:]], ["alpha failure"])
        _, rows = parse_csv(self.fetch(section="logs", days=1, q="ok"))
        self.assertEqual([r[3] for r in rows[1:]], ["alpha ok"])

"""Measuring renders, so phase 0.5 stops depending on anyone's memory.

The capacity model currently rests on two remembered runs, 15 and 45 minutes
for the same five seconds of video. The gap between those is the gap between a
business that works and one that does not, so the numbers have to come from
rows rather than recollection.

The real numbers need a GPU. What is verified here is that they will be
recorded correctly when one is present, and that the report does not lie when
it has nothing.
"""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from unittest.mock import patch

from apps.stores.models import Store

from . import metrics
from .metrics import RenderMetric
from .models import Job

HARDWARE = "RTX 3060 · 8cpu · Linux"


def _row(**kwargs):
    defaults = dict(
        kind=RenderMetric.Kind.VIDEO_SEGMENT,
        engine="wan22_i2v@v1",
        hardware=HARDWARE,
        duration_s=900.0,     # 15 minutes
        output_units=5.0,     # for 5 seconds of video
    )
    defaults.update(kwargs)
    return RenderMetric.objects.create(**defaults)


class RecordingTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("metric-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه اندازه‌گیری")
        self.job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_GENERATION)

    def test_the_ratio_is_the_number_capacity_planning_needs(self):
        """15 minutes for 5 seconds is 3 minutes per second of video."""
        row = _row()
        self.assertAlmostEqual(row.minutes_per_unit, 3.0, places=2)

    def test_the_slow_run_is_recorded_as_what_it_was(self):
        row = _row(duration_s=2700.0)  # the remembered 45-minute run
        self.assertAlmostEqual(row.minutes_per_unit, 9.0, places=2)

    def test_the_context_manager_times_the_body(self):
        with metrics.measured(
            RenderMetric.Kind.IMAGE, "flux_txt2img@v1", job=self.job, store=self.store,
        ):
            pass
        row = RenderMetric.objects.get()
        self.assertTrue(row.succeeded)
        self.assertEqual(row.job, self.job)
        self.assertEqual(row.store, self.store)

    def test_a_failed_render_is_recorded_too(self):
        """A pipeline that succeeds in 4 minutes but fails a third of the time
        costs 6 minutes per usable output. A table of successes hides that."""
        with self.assertRaises(ValueError):
            with metrics.measured(RenderMetric.Kind.IMAGE, "flux_txt2img@v1"):
                raise ValueError("comfy died")

        row = RenderMetric.objects.get()
        self.assertFalse(row.succeeded)
        self.assertEqual(row.error_kind, "ValueError")

    def test_the_real_exception_is_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            with metrics.measured(RenderMetric.Kind.IMAGE, "x"):
                raise RuntimeError("boom")

    def test_a_broken_measurement_never_breaks_a_render(self):
        """Losing a number is acceptable; losing a render is not."""
        with patch.object(
            RenderMetric.objects, "create", side_effect=Exception("db gone")
        ):
            with metrics.measured(RenderMetric.Kind.IMAGE, "x"):
                pass  # must not raise
        self.assertEqual(RenderMetric.objects.count(), 0)

    def test_model_load_time_is_recorded_separately(self):
        """On a single-GPU machine that swaps Ollama and ComfyUI this is not a
        rounding error — §8.5 wants it in the formula."""
        with metrics.measured(RenderMetric.Kind.VIDEO_SEGMENT, "wan22_i2v@v1") as m:
            m.mark_loaded()
        row = RenderMetric.objects.get()
        self.assertIsNotNone(row.load_s)


class SummaryTests(TestCase):
    def test_the_median_is_used_not_the_mean(self):
        """Render times have a long right tail. A mean dragged up by one
        45-minute outlier describes a machine nobody has."""
        _row(duration_s=900.0)    # 3 min/s
        _row(duration_s=900.0)    # 3
        _row(duration_s=2700.0)   # 9

        summary = metrics.summarise()[0]

        self.assertEqual(summary["minutes_per_unit_median"], 3.0)
        self.assertEqual(summary["minutes_per_unit_max"], 9.0)

    def test_failures_raise_the_effective_cost(self):
        _row(duration_s=900.0)                    # 3 min/s, ok
        _row(duration_s=900.0)                    # 3 min/s, ok
        _row(duration_s=900.0, succeeded=False)   # wasted

        summary = metrics.summarise()[0]

        self.assertAlmostEqual(summary["success_rate"], 0.667, places=2)
        # 3 minutes of work, two thirds of the time → 4.5 per usable second
        self.assertAlmostEqual(summary["effective_minutes_per_unit"], 4.5, places=1)

    def test_machines_are_never_averaged_together(self):
        """A 3060 and a 4090 produce different numbers and their mean
        describes neither."""
        _row(duration_s=900.0)
        _row(duration_s=300.0, hardware="RTX 4090 · 16cpu · Linux")

        summary = metrics.summarise()

        self.assertEqual(len(summary), 2)
        self.assertEqual({r["hardware"] for r in summary}, {HARDWARE, "RTX 4090 · 16cpu · Linux"})

    def test_engines_are_reported_separately(self):
        _row()
        _row(kind=RenderMetric.Kind.IMAGE, engine="flux_txt2img@v1", duration_s=60, output_units=1)

        summary = metrics.summarise()
        self.assertEqual(len(summary), 2)

    def test_nothing_measured_reports_nothing(self):
        self.assertEqual(metrics.summarise(), [])


class BenchmarkCommandTests(TestCase):
    def test_with_no_data_it_says_so_instead_of_printing_zeros(self):
        out = StringIO()
        call_command("benchmark", stdout=out)
        text = out.getvalue()
        self.assertIn("هیچ اندازه‌گیری", text)

    def test_the_report_shows_the_measured_spread(self):
        _row(duration_s=900.0)
        _row(duration_s=2700.0)

        out = StringIO()
        call_command("benchmark", stdout=out)
        text = out.getvalue()

        self.assertIn("wan22_i2v@v1", text)
        self.assertIn("3.0", text)
        self.assertIn("9.0", text)

    def test_the_json_block_is_ready_to_paste_into_data_json(self):
        _row(duration_s=900.0)
        _row(duration_s=2700.0)

        out = StringIO()
        call_command("benchmark", "--json", stdout=out)

        import json

        block = json.loads(out.getvalue())
        self.assertEqual(block["source"], "measured")
        self.assertEqual(block["video_gpu_min_per_second_range"]["fast"], 3.0)
        self.assertEqual(block["video_gpu_min_per_second_range"]["slow"], 9.0)

    def test_the_json_block_carries_the_failure_adjusted_number(self):
        """The one the capacity model should use."""
        _row(duration_s=900.0)
        _row(duration_s=900.0, succeeded=False)

        out = StringIO()
        call_command("benchmark", "--json", stdout=out)

        import json

        block = json.loads(out.getvalue())
        self.assertIn("video_gpu_min_per_second_effective", block)
        self.assertAlmostEqual(block["video_gpu_min_per_second_effective"], 6.0, places=1)

    def test_filtering_by_kind_works(self):
        _row()
        _row(kind=RenderMetric.Kind.IMAGE, engine="flux_txt2img@v1")

        out = StringIO()
        call_command("benchmark", "--kind", "IMAGE", stdout=out)

        self.assertIn("flux_txt2img@v1", out.getvalue())
        self.assertNotIn("wan22_i2v@v1", out.getvalue())


class HardwareProfileTests(TestCase):
    def test_a_machine_with_no_gpu_says_so_rather_than_guessing(self):
        """A capacity model fed a fabricated VRAM figure is worse than one
        that says "unknown", because the first kind of wrong looks like an
        answer."""
        from services import hardware

        with patch.object(hardware, "_nvidia_smi", return_value=[]):
            profile = hardware.profile()

        self.assertFalse(profile["has_gpu"])
        self.assertEqual(profile["gpus"], [])
        self.assertIn("no-gpu", profile["fingerprint"])

    def test_a_gpu_is_parsed_into_real_numbers(self):
        from services import hardware

        row = "NVIDIA GeForce RTX 3060, 12288, 2048, 61, 45"
        with patch.object(hardware, "_nvidia_smi", return_value=[row]):
            cards = hardware.gpus()

        self.assertEqual(cards[0]["name"], "NVIDIA GeForce RTX 3060")
        self.assertEqual(cards[0]["vram_total_mb"], 12288)
        self.assertEqual(cards[0]["vram_free_mb"], 10240)

    def test_a_malformed_line_is_skipped_not_crashed_on(self):
        from services import hardware

        with patch.object(hardware, "_nvidia_smi", return_value=["garbage"]):
            self.assertEqual(hardware.gpus(), [])

    def test_the_fingerprint_names_a_class_of_machine_not_an_installation(self):
        """It groups measurements; it must not identify a host."""
        from services import hardware

        row = "NVIDIA GeForce RTX 3060, 12288, 2048, 61, 45"
        with patch.object(hardware, "_nvidia_smi", return_value=[row]):
            fingerprint = hardware.fingerprint()

        self.assertIn("RTX 3060", fingerprint)
        import socket

        self.assertNotIn(socket.gethostname(), fingerprint)

"""Quality control on generated video, and the repair ladder under it.

Phase 21's DoD: "یک Segment با نقص عمدی (نور بد / لرزش / Flicker) بدون مصرف
دوباره‌ی GPU با کد اصلاح می‌شود؛ یک Segment با تغییر هویت شخصیت، regenerate
می‌شود. هر دو در تست خودکار."

So the frames here are built with deliberate defects — a dark clip, a
flickering one, a frozen one — and the assertions are about which branch of the
ladder each one takes. No GPU is involved in any of it, which is the point.
"""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.stores.models import Store
from services.video import qc, repair


def frame(colour, size=(64, 64)):
    from PIL import Image

    return Image.new("RGB", size, colour)


def write_frames(directory: Path, images) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, image in enumerate(images):
        path = directory / f"qc_{index:02d}.png"
        image.save(path)
        paths.append(path)
    return paths


def noisy(base, seed=0, size=(64, 64)):
    """A frame with structure, so consecutive frames are not byte-identical."""
    from PIL import Image

    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            shift = ((x * 7 + y * 13 + seed * 29) % 40) - 20
            pixels[x, y] = tuple(max(0, min(255, c + shift)) for c in base)
    return image


class CodeAxisTests(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _axes(self, images):
        paths = write_frames(self.dir, images)
        return {a.name: a for a in qc.code_axes(paths)[0]}, qc.code_axes(paths)[1]

    def test_a_healthy_clip_scores_well(self):
        images = [noisy((128, 130, 126), seed=i) for i in range(8)]
        axes, fixable = self._axes(images)
        self.assertGreater(axes["پیوستگی زمانی"].score, 80)
        self.assertGreater(axes["نوردهی"].score, 80)
        self.assertEqual(fixable, [])

    def test_a_dark_clip_is_flagged_and_is_code_fixable(self):
        """The cheap failure: a colour curve away from fine."""
        images = [noisy((18, 18, 20), seed=i) for i in range(8)]
        axes, fixable = self._axes(images)
        self.assertLess(axes["نوردهی"].score, 70)
        self.assertIn("EXPOSURE", fixable)
        self.assertIn("تاریک", axes["نوردهی"].note)

    def test_an_almost_black_clip_scores_near_zero(self):
        images = [noisy((4, 4, 4), seed=i) for i in range(6)]
        axes, _ = self._axes(images)
        self.assertLess(axes["نوردهی"].score, 20)

    def test_flicker_is_detected_between_frames(self):
        """Alternating brightness is flicker; the model does this often."""
        images = [noisy((90, 90, 90) if i % 2 else (170, 170, 170), seed=i) for i in range(8)]
        axes, fixable = self._axes(images)
        self.assertLess(axes["پیوستگی زمانی"].score, 70)
        self.assertIn("FLICKER", fixable)

    def test_a_frozen_clip_loses_motion_points(self):
        """A clip that stops moving reads as broken, not as calm."""
        still = noisy((120, 120, 120), seed=3)
        axes, _ = self._axes([still] * 8)
        self.assertLess(axes["کیفیت حرکت"].score, 70)
        self.assertIn("حرکتی ندارد", axes["کیفیت حرکت"].note)

    def test_colour_drift_from_start_to_end_is_caught(self):
        images = [noisy((40 + i * 30, 90, 90), seed=i) for i in range(8)]
        axes, fixable = self._axes(images)
        self.assertLess(axes["ثبات رنگ"].score, 80)
        self.assertIn("COLOR", fixable)

    def test_one_frame_is_not_enough_to_judge(self):
        paths = write_frames(self.dir, [noisy((120, 120, 120))])
        axes, fixable = qc.code_axes(paths)
        self.assertEqual(fixable, [])
        self.assertIn("فریم", axes[0].note)


class ScoreTests(TestCase):
    def test_object_consistency_outweighs_exposure(self):
        """A beautiful clip of the wrong product is worthless to a shop; a
        slightly dark clip of the right one is a colour curve away from fine."""
        self.assertGreater(qc.WEIGHTS["ثبات محصول"], qc.WEIGHTS["نوردهی"])

    def test_verdicts_follow_the_thresholds(self):
        self.assertEqual(qc.verdict_for(95), "EXCELLENT")
        self.assertEqual(qc.verdict_for(85), "GOOD")
        self.assertEqual(qc.verdict_for(75), "REVIEW")
        self.assertEqual(qc.verdict_for(50), "REGENERATE")

    def test_thresholds_are_configurable_for_phase_zero_five(self):
        """§9.2 says these numbers are placeholders until real renders exist."""
        from django.conf import settings

        merged = {**settings.UPMARKET_AI, "QC_REVIEW": 40}
        with override_settings(UPMARKET_AI=merged):
            self.assertEqual(qc.verdict_for(50), "REVIEW")

    def test_one_catastrophic_axis_caps_the_overall(self):
        """A weighted mean alone scored a nearly-black clip 92 — "excellent" —
        and would have shipped the wrong product at 85. Quality is closer to a
        minimum than an average."""
        axes = [
            qc.Axis("ثبات محصول", 10.0),
            qc.Axis("پیوستگی زمانی", 100.0),
            qc.Axis("کیفیت حرکت", 100.0),
            qc.Axis("نوردهی", 100.0),
        ]
        self.assertLessEqual(qc.combine(axes), 25.0)
        self.assertEqual(qc.verdict_for(qc.combine(axes)), "REGENERATE")

    def test_a_uniformly_good_clip_is_not_punished_by_the_cap(self):
        axes = [qc.Axis(name, 94.0) for name in ("ثبات محصول", "نوردهی", "کیفیت حرکت")]
        self.assertGreaterEqual(qc.combine(axes), 90.0)

    def test_one_slightly_low_axis_does_not_tank_everything(self):
        """A pure minimum would be too harsh to be useful."""
        axes = [
            qc.Axis("ثبات محصول", 95.0),
            qc.Axis("نوردهی", 78.0),
            qc.Axis("کیفیت حرکت", 92.0),
        ]
        self.assertGreater(qc.combine(axes), 85.0)

    def test_the_score_fraction_matches_what_the_pipeline_compares(self):
        """`_should_pause` compares against a 0–1 threshold."""
        report = qc.QCReport(overall=72.0, axes=[qc.Axis("نوردهی", 72.0)])
        self.assertAlmostEqual(report.score_fraction, 0.72, places=3)

    def test_a_report_nobody_could_produce_has_no_score(self):
        """"QC could not open the file" is a system problem, not a quality
        collapse. Turning it into an approval prompt on every segment would
        make a missing ffmpeg look like a broken model."""
        report = qc.QCReport(overall=50.0, error="فریمی استخراج نشد")
        self.assertFalse(report.judged)
        self.assertIsNone(report.score_fraction)

    def test_a_real_verdict_does_have_a_score(self):
        report = qc.QCReport(overall=64.0, axes=[qc.Axis("نوردهی", 64.0)])
        self.assertTrue(report.judged)
        self.assertIsNotNone(report.score_fraction)


class VisionValidationTests(TestCase):
    def test_numbers_are_required(self):
        ok, problems = qc.validate_vision({"notes": "خوب بود"})
        self.assertFalse(ok)
        self.assertIn("object_consistency", problems)

    def test_values_are_clamped_to_the_scale(self):
        parsed = {
            "character_consistency": 140, "object_consistency": -20,
            "anatomy": 80, "artifacts": 90,
        }
        ok, _ = qc.validate_vision(parsed)
        self.assertTrue(ok)
        self.assertEqual(parsed["character_consistency"], 100)
        self.assertEqual(parsed["object_consistency"], 0)

    def test_a_string_number_is_accepted(self):
        """Models return "85" as often as 85."""
        parsed = {
            "character_consistency": "85", "object_consistency": "90",
            "anatomy": "88", "artifacts": "92",
        }
        ok, _ = qc.validate_vision(parsed)
        self.assertTrue(ok)
        self.assertEqual(parsed["character_consistency"], 85.0)


class RepairLadderTests(TestCase):
    """Which branch a failure takes, and why."""

    def test_a_dark_clip_goes_to_the_code_layer(self):
        report = qc.QCReport(
            overall=68, verdict="REGENERATE", code_fixable=["EXPOSURE"],
        )
        self.assertTrue(repair.can_fix_with_code(report))
        self.assertEqual(repair.plan(report)["action"], "CODE_REPAIR")
        self.assertIn("بدون GPU", repair.plan(report)["cost"])

    def test_a_changed_face_goes_to_regeneration(self):
        report = qc.QCReport(
            overall=55, verdict="REGENERATE",
            needs_regeneration=["CHARACTER_CONSISTENCY"],
        )
        self.assertFalse(repair.can_fix_with_code(report))
        plan = repair.plan(report)
        self.assertEqual(plan["action"], "REGENERATE")
        self.assertIn("شخصیت", plan["reason"])

    def test_a_changed_product_is_named_in_plain_words(self):
        """The check that matters most to a shop."""
        report = qc.QCReport(
            overall=40, verdict="REGENERATE",
            needs_regeneration=["OBJECT_CONSISTENCY"],
        )
        self.assertIn("محصول عوض شده", repair.plan(report)["reason"])

    def test_a_mixed_failure_is_not_code_fixable(self):
        """Correcting the colour would produce a well-lit clip of the wrong
        person, and the owner would have paid for the filter pass too."""
        report = qc.QCReport(
            overall=50, verdict="REGENERATE",
            code_fixable=["COLOR"], needs_regeneration=["ANATOMY"],
        )
        self.assertFalse(repair.can_fix_with_code(report))
        self.assertEqual(repair.plan(report)["action"], "REGENERATE")

    def test_a_good_segment_is_simply_accepted(self):
        report = qc.QCReport(overall=91, verdict="EXCELLENT")
        plan = repair.plan(report)
        self.assertEqual(plan["action"], "ACCEPT")
        self.assertEqual(plan["cost"], "هیچ")

    def test_the_regeneration_cost_says_only_one_segment(self):
        """§9.3's rule: never re-render the whole video."""
        report = qc.QCReport(
            overall=30, verdict="REGENERATE", needs_regeneration=["ARTIFACTS"],
        )
        self.assertIn("فقط همین قطعه", repair.plan(report)["cost"])

    def test_deflicker_runs_before_exposure(self):
        """Correcting exposure on a flickering clip bakes the flicker in."""
        self.assertLess(repair.ORDER.index("FLICKER"), repair.ORDER.index("EXPOSURE"))

    def test_nothing_to_fix_reports_honestly(self):
        report = qc.QCReport(overall=50)
        result = repair.repair_with_code("/nonexistent.mp4", report)
        self.assertFalse(result.repaired)
        self.assertEqual(result.applied, [])


class ReportShapeTests(TestCase):
    def test_a_report_says_when_nobody_looked(self):
        """"Vision unavailable" must never be read as "it passed"."""
        report = qc.QCReport(overall=85, vision_checked=False)
        self.assertFalse(report.as_dict()["vision_checked"])

    def test_localized_repair_is_declared_absent_not_faked(self):
        """§9.3 level 2 needs segmentation masks; approximating it with a blur
        turns a wrong hand into a smear."""
        self.assertFalse(qc.QCReport().as_dict()["localized_repair_available"])

    def test_every_axis_carries_its_reason(self):
        """"Motion Quality: 61" tells a shop owner nothing."""
        axis = qc.Axis("کیفیت حرکت", 61.0, "کلیپ وسط کار می‌ایستد")
        self.assertIn("note", axis.as_dict())
        self.assertTrue(axis.as_dict()["note"])


class CheckSegmentTests(TestCase):
    """The whole call, with ffmpeg and the vision model stubbed out."""

    def setUp(self):
        owner = User.objects.create_user("qc-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه کیفیت")
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_dark_segment_produces_a_low_score_and_a_repair_plan(self):
        frames = write_frames(self.dir / "qc", [noisy((16, 16, 18), seed=i) for i in range(6)])

        with patch.object(qc, "sample_frames", return_value=frames):
            report = qc.check_segment(
                "fake.mp4", self.dir, store=self.store, use_vision=False,
            )

        self.assertLess(report.overall, 85)
        self.assertIn("EXPOSURE", report.code_fixable)
        self.assertEqual(repair.plan(report)["action"], "CODE_REPAIR")

    def test_no_frames_is_a_review_not_a_pass(self):
        """A segment nobody could look at is not a segment that passed."""
        with patch.object(qc, "sample_frames", return_value=[]):
            report = qc.check_segment("fake.mp4", self.dir, store=self.store)

        self.assertEqual(report.verdict, "REVIEW")
        self.assertTrue(report.error)

    def test_qc_never_breaks_a_finished_render(self):
        """The segment already exists and already cost GPU minutes."""
        with patch.object(qc, "sample_frames", side_effect=RuntimeError("boom")):
            report = qc.check_segment("fake.mp4", self.dir, store=self.store)

        self.assertEqual(report.verdict, "REVIEW")
        self.assertIn("boom", report.error)

    def test_a_vision_failure_marks_the_report_unchecked(self):
        frames = write_frames(self.dir / "qc", [noisy((128, 128, 128), seed=i) for i in range(4)])

        with patch.object(qc, "sample_frames", return_value=frames), \
             patch("services.ai.gateway.vision_provider", side_effect=RuntimeError("down")):
            report = qc.check_segment("fake.mp4", self.dir, store=self.store)

        self.assertFalse(report.vision_checked)
        # and the code axes still produced a usable number
        self.assertGreater(report.overall, 0)

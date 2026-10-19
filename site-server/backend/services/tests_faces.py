"""Where the people are, and the two decisions that depend on it. §8

Both decisions have an obvious wrong answer that a system without this module
takes by default:

* A subtitle goes bottom-centre — which is exactly where a person standing in
  frame usually is. A caption across a mouth is the one placement everybody
  notices.
* A zoom crops from the centre — so a person standing slightly off-centre loses
  an ear, and nobody asked for that.

The detection itself is not tested against photographs of people: OpenCV's
cascade is OpenCV's problem, not ours. What is tested is every decision made
*from* a set of boxes, plus the one distinction that matters more than accuracy —
**"I could not look" is not "there is nobody there"**, and the two lead to
opposite behaviour.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

import unittest

from django.test import SimpleTestCase

from services.video import faces
from services.video.faces import Box


class AvailabilityTests(SimpleTestCase):
    def test_opencv_is_here(self):
        ok, why = faces.available()
        self.assertTrue(ok, why)

    def test_without_opencv_it_says_what_to_install(self):
        with patch.dict("sys.modules", {"cv2": None}):
            ok, why = faces.available()
        self.assertFalse(ok)
        self.assertIn("opencv", why.lower())

    def test_a_blank_frame_has_nobody_in_it(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.png"
            cv2.imwrite(str(path), np.full((480, 640, 3), 200, dtype=np.uint8))
            self.assertEqual(faces.in_image(path), [])

    def test_an_unreadable_frame_raises_rather_than_reporting_nobody(self):
        """The distinction the whole module turns on."""
        with self.assertRaises(RuntimeError):
            faces.in_image("does-not-exist.png")


class CaptionPlacementTests(SimpleTestCase):
    def test_a_clear_frame_keeps_the_caption_where_it_belongs(self):
        """Bottom-centre is the right answer whenever it is free."""
        self.assertEqual(faces.best_caption_position([]), "bottom")

    def test_somebody_at_the_bottom_moves_the_caption_up(self):
        person = [Box(0.3, 0.55, 0.4, 0.45)]
        self.assertNotEqual(faces.best_caption_position(person), "bottom")

    def test_somebody_at_the_top_leaves_the_caption_alone(self):
        person = [Box(0.35, 0.02, 0.3, 0.30)]
        self.assertEqual(faces.best_caption_position(person), "bottom")

    def test_dicts_work_as_well_as_boxes(self):
        """The analysis layer stores them as dicts on the model row."""
        person = [{"x": 0.3, "y": 0.55, "w": 0.4, "h": 0.45}]
        self.assertNotEqual(faces.best_caption_position(person), "bottom")

    def test_a_frame_full_of_people_still_gets_an_answer(self):
        """A subtitle over a chest is readable; one over a mouth is what people
        complain about. Bottom is the least bad, not a failure."""
        everywhere = [Box(0.0, 0.0, 1.0, 1.0)]
        self.assertEqual(faces.best_caption_position(everywhere), "bottom")

    def test_the_requested_default_is_tried_first(self):
        self.assertEqual(faces.best_caption_position([], default="top"), "top")


class ZoomTests(SimpleTestCase):
    def test_an_empty_frame_zooms_from_the_centre(self):
        self.assertEqual(faces.zoom_window([], 1.3), (0.5, 0.5))

    def test_a_zoom_anchors_on_the_face(self):
        face = [Box(0.55, 0.15, 0.2, 0.25)]
        x, _ = faces.zoom_window(face, 1.3)
        self.assertGreater(x, 0.5)

    def test_the_anchor_sits_above_the_middle_of_the_box(self):
        """Centring on the exact middle puts the crop low and cuts the top of
        the head."""
        face = [Box(0.35, 0.35, 0.2, 0.3)]
        _, y = faces.zoom_window(face, 1.8)
        self.assertLess(y, 0.50)  # the box's own centre is at 0.50

    def test_staying_inside_the_frame_beats_the_lift(self):
        """At a gentle zoom the crop window is nearly the whole frame, so it
        cannot be moved much without leaving it. The clamp wins, and that is
        right: an out-of-frame crop is silently clamped by ffmpeg and the zoom
        ends up somewhere nobody chose."""
        face = [Box(0.4, 0.2, 0.2, 0.4)]
        _, y = faces.zoom_window(face, 1.2)
        half = 1.0 / (2 * 1.2)
        self.assertAlmostEqual(y, half, places=4)

    def test_the_window_never_leaves_the_frame(self):
        """ffmpeg silently clamps an out-of-frame crop and the zoom drifts
        somewhere nobody chose."""
        edge = [Box(0.0, 0.0, 0.1, 0.1)]
        for scale in (1.05, 1.4, 1.6):
            x, y = faces.zoom_window(edge, scale)
            half = 1.0 / (2 * scale)
            self.assertGreaterEqual(round(x, 6), round(half, 6))
            self.assertLessEqual(round(x, 6), round(1 - half, 6))
            self.assertGreaterEqual(round(y, 6), round(half, 6))

    def test_the_biggest_face_wins(self):
        boxes = [Box(0.05, 0.4, 0.08, 0.1), Box(0.7, 0.2, 0.25, 0.3)]
        x, _ = faces.zoom_window(boxes, 1.3)
        self.assertGreater(x, 0.5)


class ZoomSafetyTests(SimpleTestCase):
    def test_an_empty_frame_is_always_safe(self):
        self.assertTrue(faces.safe_to_zoom([], 2.0)[0])

    def test_a_gentle_zoom_on_a_small_face_is_safe(self):
        self.assertTrue(faces.safe_to_zoom([Box(0.55, 0.15, 0.2, 0.25)], 1.15)[0])

    def test_a_hard_zoom_on_a_big_face_is_refused(self):
        ok, why = faces.safe_to_zoom([Box(0.15, 0.10, 0.70, 0.60)], 1.9)
        self.assertFalse(ok)
        self.assertIn("چهره", why)

    def test_two_people_far_apart_cannot_both_be_kept(self):
        ok, _ = faces.safe_to_zoom(
            [Box(0.05, 0.2, 0.2, 0.3), Box(0.75, 0.2, 0.2, 0.3)], 1.5,
        )
        self.assertFalse(ok)

    def test_the_refusal_names_the_scale_and_says_what_to_do(self):
        _, why = faces.safe_to_zoom([Box(0.15, 0.10, 0.70, 0.60)], 1.9)
        self.assertIn("1.9", why)
        self.assertIn("کوچک‌تر", why)


class MergeTests(SimpleTestCase):
    def test_three_sightings_of_one_person_are_one_person(self):
        sightings = [
            Box(0.30, 0.20, 0.20, 0.25),
            Box(0.31, 0.21, 0.20, 0.25),
            Box(0.32, 0.20, 0.20, 0.25),
        ]
        self.assertEqual(len(faces._merge(sightings)), 1)

    def test_the_merged_box_covers_everywhere_they_were(self):
        """The region to protect is the whole path, not one frame of it."""
        merged = faces._merge([
            Box(0.30, 0.20, 0.20, 0.25), Box(0.34, 0.20, 0.20, 0.25),
        ])[0]
        self.assertGreater(merged.w, 0.20)

    def test_two_different_people_stay_two(self):
        self.assertEqual(
            len(faces._merge([Box(0.05, 0.2, 0.15, 0.2), Box(0.75, 0.2, 0.15, 0.2)])),
            2,
        )


class CouldNotLookTests(SimpleTestCase):
    def test_no_opencv_reports_that_it_did_not_look(self):
        """Not the same as "nobody is there" — one falls back to the default,
        the other is free rein."""
        with patch.object(faces, "available", return_value=(False, "no cv2")):
            result = faces.in_video("x.mp4", ".")
        self.assertFalse(result["looked"])
        self.assertEqual(result["boxes"], [])
        self.assertTrue(result["reason"])

    def test_no_frames_reports_that_it_did_not_look(self):
        with patch("services.video.qc.sample_frames", return_value=[]):
            result = faces.in_video("x.mp4", ".")
        self.assertFalse(result["looked"])
        self.assertTrue(result["reason"])

    def test_a_readable_video_with_nobody_in_it_reports_that_it_looked(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "f.png"
            cv2.imwrite(str(frame), np.full((240, 320, 3), 180, dtype=np.uint8))
            with patch("services.video.qc.sample_frames", return_value=[frame]):
                result = faces.in_video("x.mp4", directory)
        self.assertTrue(result["looked"])
        self.assertEqual(result["faces"], 0)

    def test_one_unreadable_frame_does_not_lose_the_others(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "good.png"
            cv2.imwrite(str(good), np.full((240, 320, 3), 180, dtype=np.uint8))
            bad = Path(directory) / "missing.png"
            with patch("services.video.qc.sample_frames", return_value=[bad, good]):
                result = faces.in_video("x.mp4", directory)
        self.assertTrue(result["looked"])
        self.assertEqual(result["frames_sampled"], 1)


def _haar_shipped() -> bool:
    try:
        import cv2

        return (Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml").exists()
    except Exception:  # noqa: BLE001
        return False


#: OpenCV 5 wheels (opencv-python-headless 5.x) no longer ship the Haar cascade
#: XML files. The detector is YuNet, bundled with the project; the cascades
#: are only its fallback.
requires_haar = unittest.skipUnless(
    _haar_shipped(), "this OpenCV ships no Haar cascades (5.x); YuNet is the detector",
)


class ProfileFaceTests(SimpleTestCase):
    """Sideways heads. Somebody filming their own product turns constantly, and
    a missed face means a subtitle lands on it and a zoom crops it."""

    def _frame(self, directory):
        import cv2
        import numpy as np

        path = Path(directory) / "f.png"
        cv2.imwrite(str(path), np.full((480, 640, 3), 180, dtype=np.uint8))
        return path

    @requires_haar
    def test_the_profile_cascade_is_shipped_with_opencv(self):
        import cv2

        self.assertTrue(
            (Path(cv2.data.haarcascades) / "haarcascade_profileface.xml").exists()
        )

    @requires_haar
    def test_the_frame_is_searched_mirrored_as_well(self):
        """The profile cascade only finds one direction; the other side needs
        the mirrored frame. (The Haar fallback path: YuNet is switched off.)"""
        import cv2

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(faces, "_yunet", return_value=None), \
                    patch.object(cv2, "flip", wraps=cv2.flip) as flip:
                faces.in_image(self._frame(directory))
        flip.assert_called()

    def test_a_missing_profile_cascade_does_not_lose_frontal_faces(self):
        real = faces._cascade

        def only_frontal(name="haarcascade_frontalface_default.xml"):
            if "profile" in name:
                raise RuntimeError("cascade missing")
            return real(name)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(faces, "_cascade", side_effect=only_frontal):
                self.assertEqual(faces.in_image(self._frame(directory)), [])

    def test_one_head_found_twice_is_still_one_head(self):
        """Frontal and profile routinely both hit a three-quarter view, and two
        boxes on one head make a zoom think it has two people to keep in."""
        same = [Box(0.3, 0.2, 0.2, 0.25), Box(0.31, 0.21, 0.2, 0.25)]
        self.assertEqual(len(faces._merge(same)), 1)

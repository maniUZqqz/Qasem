"""B-roll — and how often it says no. §8

The interesting behaviour here is refusal. A video cut to a supporting image
every four seconds is a video nobody believes a person made, so most of these
tests check that a cut *does not* happen and that the reason is one a shop can
read.

The other load-bearing rule: **the pictures are the shop's own.** A stock photo
of a generic shoe in a video selling this shoe is the clearest possible signal
that nobody was paying attention.
"""
from django.test import SimpleTestCase

from services.video import broll


def facts(**overrides):
    """A measured video: static camera, someone talking, long enough to cut."""
    base = {
        "readable": True,
        "duration": 60.0,
        "has_audio": True,
        "motion": 1.5,
        "silences": [{"start": 20.0, "end": 24.0}],
    }
    base.update(overrides)
    return base


def images(count=3):
    return [
        {"source": "photo", "reference": f"p{i}.jpg", "url": "", "why": "عکس خودتان"}
        for i in range(count)
    ]


class PlacementTests(SimpleTestCase):
    def test_a_static_shot_with_talking_gets_b_roll(self):
        plan = broll.plan(facts(), images())
        self.assertTrue(plan.shots)

    def test_every_shot_is_long_enough_to_be_a_shot(self):
        """Shorter than MIN_SHOT is a flicker, not a cut."""
        for shot in broll.plan(facts(), images()).shots:
            self.assertGreaterEqual(shot.seconds, broll.MIN_SHOT)

    def test_no_shot_outstays_its_welcome(self):
        for shot in broll.plan(facts(), images()).shots:
            self.assertLessEqual(shot.seconds, broll.MAX_SHOT)

    def test_b_roll_never_covers_most_of_the_video(self):
        """Past a third it is a slideshow with a voice-over, which is a
        different product and a worse one."""
        plan = broll.plan(facts(duration=120.0), images(20))
        self.assertLessEqual(plan.share, broll.MAX_SHARE + 0.01)

    def test_shots_come_back_in_order(self):
        shots = broll.plan(facts(duration=120.0), images(5)).shots
        for earlier, later in zip(shots, shots[1:]):
            self.assertLess(earlier.start, later.start)

    def test_shots_do_not_stutter_on_top_of_each_other(self):
        shots = broll.plan(facts(duration=120.0), images(5)).shots
        for earlier, later in zip(shots, shots[1:]):
            self.assertGreaterEqual(later.start, earlier.end - 0.01)

    def test_a_shot_lands_inside_the_speech_not_on_its_edge(self):
        """Cutting exactly on the first or last word is the cut people
        notice."""
        plan = broll.plan(
            facts(duration=40.0, silences=[{"start": 15.0, "end": 18.0}]),
            images(1),
        )
        for shot in plan.shots:
            self.assertGreater(shot.start, 0.5)

    def test_the_number_of_shots_can_be_capped(self):
        self.assertLessEqual(
            len(broll.plan(facts(duration=180.0), images(10), wanted=2).shots), 2,
        )


class RefusalTests(SimpleTestCase):
    def test_no_pictures_means_no_b_roll_and_says_what_to_do(self):
        plan = broll.plan(facts(), [])
        self.assertEqual(plan.shots, [])
        self.assertIn("آپلود", plan.refusals[0])

    def test_a_moving_camera_is_left_alone(self):
        """The picture is already giving the viewer something; cutting away
        takes away the one thing that was working."""
        plan = broll.plan(facts(motion=20.0), images())
        self.assertEqual(plan.shots, [])
        self.assertIn("حرکت", plan.refusals[0])

    def test_a_very_short_video_is_left_alone(self):
        plan = broll.plan(facts(duration=3.0), images())
        self.assertEqual(plan.shots, [])
        self.assertTrue(plan.refusals)

    def test_a_silent_video_is_left_alone(self):
        """B-roll over silence is silence with a photograph."""
        plan = broll.plan(
            facts(silences=[{"start": 0.0, "end": 60.0}]), images(),
        )
        self.assertEqual(plan.shots, [])
        self.assertIn("حرف", plan.refusals[0])

    def test_short_bursts_of_speech_are_not_worth_cutting(self):
        plan = broll.plan(
            facts(duration=30.0, silences=[
                {"start": 2.0, "end": 8.0}, {"start": 10.0, "end": 16.0},
                {"start": 18.0, "end": 24.0}, {"start": 26.0, "end": 30.0},
            ]),
            images(),
        )
        self.assertEqual(plan.shots, [])
        self.assertTrue(plan.refusals)

    def test_every_refusal_is_a_sentence_not_a_code(self):
        for bad in (broll.plan(facts(), []),
                    broll.plan(facts(motion=20.0), images()),
                    broll.plan(facts(duration=2.0), images())):
            self.assertTrue(bad.refusals)
            self.assertGreater(len(bad.refusals[0]), 25)


class ReasonTests(SimpleTestCase):
    def test_each_shot_says_why_it_is_there(self):
        for shot in broll.plan(facts(), images()).shots:
            self.assertTrue(shot.why)
            self.assertIn("ثانیه", shot.why)

    def test_the_plan_summarises_itself_in_persian(self):
        summary = broll.plan(facts(), images()).as_dict()["summary"]
        self.assertIn("تصویر کمکی", summary)

    def test_an_empty_plan_says_so_rather_than_showing_zero(self):
        summary = broll.plan(facts(motion=20.0), images()).as_dict()["summary"]
        self.assertIn("پیدا نشد", summary)


class SourceTests(SimpleTestCase):
    def test_the_overlay_covers_the_frame_rather_than_sitting_in_a_corner(self):
        """A picture-in-picture on a portrait phone video is too small to read,
        and the point is to show the product."""
        shots = [broll.Shot(start=1, end=3, source="photo", reference="p.jpg")]
        filters = broll.overlay_filters(shots, {"p.jpg": "/tmp/p.jpg"})
        self.assertEqual(len(filters), 1)
        self.assertIn("crop=1080:1920", filters[0]["scale"])

    def test_an_overlay_is_enabled_only_for_its_window(self):
        shots = [broll.Shot(start=2.5, end=5.0, source="photo", reference="p.jpg")]
        filters = broll.overlay_filters(shots, {"p.jpg": "/tmp/p.jpg"})
        self.assertIn("between(t,2.500,5.000)", filters[0]["enable"])

    def test_a_shot_whose_picture_went_missing_is_skipped_not_rendered_blank(self):
        shots = [broll.Shot(start=1, end=3, source="photo", reference="gone.jpg")]
        self.assertEqual(broll.overlay_filters(shots, {}), [])

"""Scoring: interactions, baseline, velocity vs baseline, growth, recency, format detection. Tables of numbers, no database."""
import math

from django.test import SimpleTestCase

from . import scoring as S
from .testkit import NOW


class InteractionTests(SimpleTestCase):
    def test_a_comment_weighs_two_likes(self):
        self.assertEqual(S.interactions(100, 10), (120.0, False))

    def test_hidden_likes_are_estimated_and_flagged(self):
        value, estimated = S.interactions(None, 10, hidden=True)
        self.assertTrue(estimated)
        self.assertEqual(value, 10 * (S.COMMENT_W + S.HIDDEN_LIKES_PER_COMMENT))

    def test_nothing_known_is_zero_and_flagged(self):
        self.assertEqual(S.interactions(None, None), (0.0, True))


class FormatTests(SimpleTestCase):
    def test_formats(self):
        self.assertEqual(S.detect_format("reel"), "reel")
        self.assertEqual(S.detect_format("album", 6), "carousel")
        self.assertEqual(S.detect_format("photo", 3), "carousel", "several slides are a carousel whatever the label")
        self.assertEqual(S.detect_format("video", 1, 1080, 1920), "reel", "a tall feed video is a reel")
        self.assertEqual(S.detect_format("video", 1, 1920, 1080), "video")
        self.assertEqual(S.detect_format("photo", 1, 1080, 1350), "photo")
        self.assertEqual(S.detect_format(None), "photo")
        self.assertEqual(S.detect_format("igtv"), "reel")


class MaturityTests(SimpleTestCase):
    def test_curve(self):
        self.assertAlmostEqual(S.maturity(18), 1 - math.exp(-1), places=3)
        self.assertEqual(S.maturity(0), S.MIN_MATURITY)
        self.assertGreater(S.maturity(100), 0.99)

    def test_recency_halves_in_about_two_days(self):
        self.assertAlmostEqual(S.recency(0), 1.0)
        self.assertLess(abs(S.recency(50) - 0.5), 0.02)


class BaselineTests(SimpleTestCase):
    def posts(self, values, age_h=48, fmt="reel"):
        return [{"taken_at": NOW - (age_h + i) * 3600, "interactions": v, "fmt": fmt} for i, v in enumerate(values)]

    def test_median_of_matured_posts_one_outlier_cannot_move_it(self):
        base = S.baseline(self.posts([100, 110, 90, 105, 5000]), 20000, now_ts=NOW)
        self.assertEqual(base["value"], 105.0)
        self.assertEqual(base["source"], "matured")

    def test_young_posts_are_not_part_of_the_baseline(self):
        rows = self.posts([100, 110, 90]) + [{"taken_at": NOW - 3600, "interactions": 5, "fmt": "reel"}]
        self.assertEqual(S.baseline(rows, 20000, now_ts=NOW)["value"], 100.0)

    def test_same_format_wins_when_there_are_enough(self):
        rows = self.posts([100, 110, 90], fmt="reel") + self.posts([20, 25, 30], fmt="photo")
        self.assertEqual(S.baseline(rows, None, "photo", NOW)["value"], 25.0)
        self.assertEqual(S.baseline(rows, None, "photo", NOW)["source"], "format")

    def test_a_page_with_no_history_gets_a_default_from_its_followers(self):
        base = S.baseline([], 10000, now_ts=NOW)
        self.assertEqual((base["value"], base["source"]), (10000 * S.DEFAULT_ER, "followers"))
        self.assertEqual(S.baseline([], None, now_ts=NOW)["source"], "default")


class VelocityTests(SimpleTestCase):
    def test_a_young_post_is_projected_before_it_is_compared(self):
        # 100 interactions after 6 h is more than 100 after 48 h: the young one will end far higher
        young = S.velocity_ratio(100, 6, 100)
        old = S.velocity_ratio(100, 48, 100)
        self.assertGreater(young, old)
        self.assertAlmostEqual(old, 100 / S.maturity(48) / 100, places=3)

    def test_ratio_is_capped(self):
        self.assertEqual(S.velocity_ratio(10 ** 9, 1, 1), S.MAX_RATIO)

    def test_growth_ratio(self):
        # was 100 after 10 h (avg 10/h); 5 hours later 200 -> 20/h = 2x its earlier pace
        self.assertAlmostEqual(S.growth_ratio(200, 100, 10, 5), 2.0)
        self.assertIsNone(S.growth_ratio(200, 100, 10, 1.0), "two readings an hour apart say nothing")
        self.assertAlmostEqual(S.growth_ratio(100, 100, 10, 5), 0.0)


class PostScoreTests(SimpleTestCase):
    def test_ordinary_post_scores_low_standout_post_scores_high(self):
        ordinary = S.post_score(100, 30, 100)
        standout = S.post_score(1500, 30, 100)
        self.assertLess(ordinary["score"], 15)
        self.assertGreater(standout["score"], 55)
        self.assertGreater(standout["ratio"], ordinary["ratio"])

    def test_recency_matters(self):
        fresh = S.post_score(1500, 12, 100)
        stale = S.post_score(1500, 24 * 12, 100)
        self.assertGreater(fresh["score"], stale["score"] * 2)

    def test_growth_lifts_a_score(self):
        steady = S.post_score(400, 30, 100, growth=1.0)
        surging = S.post_score(400, 30, 100, growth=6.0)
        self.assertGreater(surging["score"], steady["score"])

    def test_reach_beyond_the_followers_is_a_bonus_for_reels(self):
        small = S.post_score(500, 30, 100, views=2000, followers=10000)
        big = S.post_score(500, 30, 100, views=200000, followers=10000)
        self.assertGreater(big["score"], small["score"])
        self.assertLessEqual(big["reach_bonus"], 0.15)

    def test_a_post_minutes_old_is_held_back(self):
        self.assertLess(S.post_score(900, 0.3, 100)["score"], S.post_score(900, 3, 100)["score"])

    def test_score_is_within_bounds_and_explained(self):
        r = S.post_score(10 ** 7, 5, 1, views=10 ** 8, followers=100, growth=25)
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(S.post_score(0, 100, 100)["score"], 0.0)
        for key in ("ratio", "growth", "recency", "baseline", "age_h", "interactions", "reach_bonus"):
            self.assertIn(key, r)

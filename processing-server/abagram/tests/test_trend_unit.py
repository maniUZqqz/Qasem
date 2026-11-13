"""ig_trend (NMarketing node): the recent posts of one page, nothing else. python tests/test_trend_unit.py"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
TMP = tempfile.mkdtemp(prefix="igs-trend-")
os.environ["IGS_DATA"] = TMP

import ig_trend  # noqa: E402
from nm_fixture import post, write_page  # noqa: E402


class RecentTests(unittest.TestCase):
    def test_returns_profile_numbers_and_posts_newest_first(self):
        write_page(TMP, "demo_fit_page", [post("A1", age_h=50), post("A2", age_h=5), post("A3", age_h=20)])
        out = ig_trend.recent("demo_fit_page", TMP)
        self.assertEqual(out["format"], "nm-ig-page")
        self.assertEqual([p["code"] for p in out["posts"]], ["A2", "A3", "A1"])
        self.assertEqual(out["profile"]["followers"], 52000)
        self.assertEqual(out["profile"]["username"], "demo_fit_page")

    def test_only_the_trend_fields_leave(self):
        write_page(TMP, "demo_two", [post("B1", music={"kind": "music", "title": "آهنگ", "artist": "هنرمند"})])
        out = ig_trend.recent("demo_two", TMP)
        one = out["posts"][0]
        for gone in ("mentions", "tagged", "location", "thumb", "items", "url", "coauthors", "sponsors"):
            self.assertNotIn(gone, one)
        self.assertEqual(one["music"], {"kind": "music", "title": "آهنگ", "artist": "هنرمند"})
        self.assertEqual(one["likes"], 900)
        self.assertEqual(one["views"], 15000)

    def test_limit_and_caption_cap(self):
        write_page(TMP, "demo_three", [post(f"C{i}", age_h=i + 1, caption="ک" * 5000) for i in range(30)])
        out = ig_trend.recent("demo_three", TMP, limit=5)
        self.assertEqual(len(out["posts"]), 5)
        self.assertEqual(out["post_count_saved"], 30)
        self.assertEqual(len(out["posts"][0]["caption"]), ig_trend.MAX_CAPTION)

    def test_nothing_saved_or_bad_name_is_none(self):
        self.assertIsNone(ig_trend.recent("never_read_page", TMP))
        self.assertIsNone(ig_trend.recent("../../etc/passwd", TMP))
        self.assertIsNone(ig_trend.recent("", TMP))

    def test_posts_without_code_or_time_are_dropped(self):
        write_page(TMP, "demo_four", [post("D1"), {"caption": "no code", "taken_at": 5}, {"code": "x"}])
        self.assertEqual([p["code"] for p in ig_trend.recent("demo_four", TMP)["posts"]], ["D1"])


if __name__ == "__main__":
    unittest.main()

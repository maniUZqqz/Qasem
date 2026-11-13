"""Topic clustering on synthetic posts (plain dicts): shared topics across pages become clusters, a lone outlier becomes a breakout,
generic words do not, and the same input always gives the same output."""
from django.test import SimpleTestCase

from . import clustering as C
from . import explain, textproc
from .testkit import NOW


def post(i, account, caption, score=40.0, ratio=2.0, age_h=10, fmt="reel", music=None, tags=None):
    tags = textproc.hashtags(caption) if tags is None else tags
    return {"id": i, "code": "P%d" % i, "account": account, "terms": textproc.terms(caption, tags), "tags": tags, "score": score, "ratio": ratio,
            "taken_at": NOW - age_h * 3600, "fmt": fmt, "hook": textproc.extract_hook(caption), "music": music}


class ClusterTests(SimpleTestCase):
    def posts(self):
        return [
            post(1, "a", "تمرین در خانه بدون وسیله #تمرین_در_خانه", 70, 5.0, 6, music={"title": "آهنگ", "artist": "ا", "kind": "music"}),
            post(2, "b", "تمرین در خانه با کش #تمرین_در_خانه", 60, 4.0, 12, music={"title": "آهنگ", "artist": "ا", "kind": "music"}),
            post(3, "c", "ورزش در خانه برای مبتدی #تمرین_در_خانه", 35, 2.0, 40),
            post(4, "a", "رژیم غذایی هفتگی #رژیم_غذایی", 30, 1.5, 20, fmt="carousel"),
            post(5, "b", "چند اشتباه در رژیم غذایی #رژیم_غذایی", 28, 1.4, 30, fmt="carousel"),
            post(6, "c", "یک موضوع کاملاً جدا دربارهٔ خواب شبانه", 15, 1.0, 50),
            post(7, "a", "حرکات کششی بعد از تمرین", 12, 0.9, 60),
        ]

    def test_shared_topics_form_clusters_across_pages(self):
        out = C.cluster_posts(self.posts(), NOW)
        labels = [c["label"] for c in out]
        self.assertTrue(any("تمرین در خانه" in l for l in labels), labels)
        home = next(c for c in out if "تمرین در خانه" in c["label"])
        self.assertEqual(sorted(home["post_ids"]), [1, 2, 3])
        self.assertEqual(home["accounts_count"], 3)
        diet = next(c for c in out if "رژیم" in c["label"])
        self.assertEqual(sorted(diet["post_ids"]), [4, 5])
        self.assertEqual(diet["dominant_format"], "carousel")

    def test_the_hotter_cross_page_topic_ranks_first(self):
        out = C.cluster_posts(self.posts(), NOW)
        self.assertIn("تمرین در خانه", out[0]["label"])
        self.assertGreater(out[0]["score"], out[1]["score"])

    def test_a_post_belongs_to_one_cluster_only(self):
        out = C.cluster_posts(self.posts(), NOW)
        ids = [i for c in out for i in c["post_ids"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_single_post_is_not_a_topic_and_unrelated_posts_stay_out(self):
        out = C.cluster_posts(self.posts(), NOW)
        self.assertFalse(any(6 in c["post_ids"] or 7 in c["post_ids"] for c in out))

    def test_breakout_post_far_above_its_page_gets_its_own_card(self):
        posts = self.posts() + [post(8, "d", "یک ایدهٔ منحصربه‌فرد برای صبح #ایده_صبح", 80, 9.0, 5)]
        out = C.cluster_posts(posts, NOW)
        b = next(c for c in out if c["kind"] == "breakout")
        self.assertEqual(b["post_ids"], [8])
        self.assertIn("یک ایدهٔ منحصربه‌فرد", b["label"])

    def test_a_feature_on_nearly_every_post_is_the_niche_not_a_topic(self):
        posts = [post(i, "a%d" % (i % 3), "ورزش امروز %s #بدنسازی" % w, 30, 1.5) for i, w in enumerate(["الف", "ب", "ج", "د", "ه", "و", "ز", "ح"], 1)]
        out = C.cluster_posts(posts, NOW)
        self.assertEqual([c for c in out if c["term"] in ("ورزش", "#بدنسازی", "امروز")], [])

    def test_audio_and_hooks_are_collected(self):
        home = next(c for c in C.cluster_posts(self.posts(), NOW) if "تمرین در خانه" in c["label"])
        self.assertEqual(home["audio"][0]["title"], "آهنگ")
        self.assertEqual(home["audio"][0]["uses"], 2)
        self.assertTrue(home["hooks"] and home["hooks"][0]["text"])

    def test_deterministic(self):
        a = C.cluster_posts(self.posts(), NOW)
        b = C.cluster_posts(list(reversed(self.posts())), NOW)
        self.assertEqual([(c["label"], c["score"], sorted(c["post_ids"])) for c in a], [(c["label"], c["score"], sorted(c["post_ids"])) for c in b])

    def test_keys_are_stable_for_the_same_topic(self):
        self.assertEqual(C.cluster_key(["#x"]), C.cluster_key(["#x"]))
        self.assertNotEqual(C.cluster_key(["#x"]), C.cluster_key(["#y"]))

    def test_niche_vocabulary_marks_and_lifts_a_matching_topic(self):
        plain = next(c for c in C.cluster_posts(self.posts(), NOW) if "رژیم" in c["label"])
        niche = next(c for c in C.cluster_posts(self.posts(), NOW, niche_terms={"رژیم_غذایی"}) if "رژیم" in c["label"])
        self.assertFalse(plain["in_niche"])
        self.assertTrue(niche["in_niche"])
        self.assertGreater(niche["score"], plain["score"])

    def test_empty_and_tiny_inputs(self):
        self.assertEqual(C.cluster_posts([], NOW), [])
        self.assertEqual(C.cluster_posts([post(1, "a", "فقط یک پست")], NOW), [])

    def test_recent_topics_outrank_old_ones_with_the_same_posts(self):
        fresh = [post(1, "a", "موضوع تازه #موضوع_تازه", 50, 3, 5), post(2, "b", "موضوع تازه #موضوع_تازه", 50, 3, 8)]
        old = [post(3, "a", "موضوع کهنه #موضوع_کهنه", 50, 3, 300), post(4, "b", "موضوع کهنه #موضوع_کهنه", 50, 3, 310)]
        out = C.cluster_posts(fresh + old, NOW)
        self.assertEqual(out[0]["label"].split(" · ")[0], "موضوع تازه")

    def test_the_why_texts_are_persian_and_honest(self):
        home = next(c for c in C.cluster_posts(self.posts(), NOW) if "تمرین در خانه" in c["label"])
        why = explain.why_cluster(home)
        text = " ".join(why)
        self.assertIn("۳ پست از ۳ صفحه", text)
        self.assertIn("برابرِ حدِ معمولِ", text)
        self.assertIn("آهنگِ «آهنگ»", text)
        single = explain.why_cluster({"kind": "breakout", "best_ratio": 9.0, "size": 1, "accounts_count": 1})
        self.assertIn("۹ برابرِ حدِ معمولِ همان صفحه", single[0])

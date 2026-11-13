"""Batches and exports into the database: cleaning, upserting, snapshots, scoring, clusters, seeds. Synthetic data only."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from . import engine, ingest, normalize
from .models import IgAccount, IgAudio, IgHashtag, IgPost, IgPostSnapshot, IgSeed, IgTrendCluster
from .testkit import abagram_export, abagram_post, make_store, node_batch, niche_pages


class NormalizeTests(TestCase):
    def test_export_gives_profile_and_posts_and_never_reads_the_followers(self):
        doc = abagram_export("fit_home_a", [abagram_post("X1"), abagram_post("X2", 30)])
        batch = normalize.from_abagram_page(doc)
        self.assertEqual([a["username"] for a in batch["accounts"]], ["fit_home_a"])
        self.assertEqual({p["code"] for p in batch["posts"]}, {"X1", "X2"})
        self.assertNotIn("follower_a", json.dumps(batch))
        self.assertNotIn("PRIVATE-FOLLOWER-DATA", json.dumps(batch))
        self.assertEqual(batch["per_account"]["fit_home_a"]["status"], "ok")

    def test_a_private_page_export_is_marked(self):
        batch = normalize.from_abagram_page(abagram_export("secret_page", [], is_private=True))
        self.assertEqual(batch["per_account"]["secret_page"]["status"], "private")

    def test_wrong_format_or_version_is_refused_in_persian(self):
        with self.assertRaisesMessage(normalize.BatchError, "abagram-page"):
            normalize.from_abagram_page({"format": "something"})
        with self.assertRaises(normalize.BatchError):
            normalize.from_abagram_page(dict(abagram_export("a_b", []), version=7))
        with self.assertRaises(normalize.BatchError):
            normalize.from_abagram_page(dict(abagram_export("a_b", []), username="bad name!", profile={}))
        with self.assertRaises(normalize.BatchError):
            normalize.from_abagram_page("not a dict")

    def test_clean_batch_drops_bad_rows_and_cleans_types(self):
        raw = node_batch(1, pages={"ok_page": [abagram_post("GOOD1")]})
        raw["posts"] += [{"account": "ok_page", "code": "bad code!", "taken_at": 1_700_000_000},
                         {"account": "other_page", "code": "NOACC", "taken_at": 1_700_000_000},
                         {"account": "ok_page", "code": "NOTIME", "taken_at": "garbage"},
                         {"account": "ok_page", "code": "GOOD1", "taken_at": 1_700_000_000},
                         {"account": "ok_page", "code": "NEG", "taken_at": 1_700_000_000, "likes": -5, "comments": "x", "views": True}]
        raw["accounts"].append({"username": "bad name"})
        clean = normalize.clean_batch(raw)
        self.assertEqual([p["code"] for p in clean["posts"]], ["GOOD1", "NEG"], "duplicates, unknown pages, bad codes and bad times are dropped")
        neg = clean["posts"][1]
        self.assertEqual((neg["likes"], neg["comments"], neg["views"]), (None, None, None))
        self.assertEqual([a["username"] for a in clean["accounts"]], ["ok_page"])

    def test_clean_batch_refuses_foreign_or_oversized_data(self):
        with self.assertRaises(normalize.BatchError):
            normalize.clean_batch({"format": "x"})
        with self.assertRaises(normalize.BatchError):
            normalize.clean_batch({"format": "nm-ig-batch", "version": 9})
        with self.assertRaises(normalize.BatchError):
            normalize.clean_batch({"format": "nm-ig-batch", "version": 1, "accounts": "no", "posts": []})
        with mock.patch.object(normalize, "MAX_POSTS", 2):
            with self.assertRaises(normalize.BatchError):
                normalize.clean_batch(node_batch(1, pages={"p_a": [abagram_post("A1"), abagram_post("A2"), abagram_post("A3")]}))

    def test_times_accept_epoch_millis_and_iso(self):
        self.assertEqual(normalize.to_epoch(1_700_000_000), 1_700_000_000)
        self.assertEqual(normalize.to_epoch(1_700_000_000_000), 1_700_000_000)
        self.assertEqual(normalize.to_epoch("2026-11-10T08:00:00+00:00"), 1_794_297_600)
        self.assertIsNone(normalize.to_epoch("nope"))
        self.assertIsNone(normalize.to_epoch(5))
        self.assertIsNone(normalize.to_epoch(True))


class IngestTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        self.pages = niche_pages()

    def apply(self, **kw):
        return ingest.apply_batch(self.store, node_batch(self.store.pk, pages=self.pages), **kw)

    def test_a_batch_creates_pages_posts_snapshots_and_scores(self):
        out = self.apply()
        self.assertEqual((out["accounts"], out["posts"], out["new"]), (3, 12, 12))
        self.assertEqual(IgAccount.objects.count(), 3)
        self.assertEqual(IgPost.objects.count(), 12)
        self.assertEqual(IgPostSnapshot.objects.count(), 12)
        hot = IgPost.objects.get(code="HA1")
        self.assertEqual(hot.fmt, "reel")
        self.assertGreater(hot.score, 50)
        self.assertGreater(hot.ratio, 3)
        self.assertEqual(IgPost.objects.get(code="DC1").fmt, "carousel")
        self.assertEqual(IgPost.objects.get(code="HA4").fmt, "photo")
        self.assertTrue(hot.hook)
        self.assertEqual(hot.explain["baseline"], round(IgAccount.objects.get(username="fit_home_a").baseline_reel, 1), "a reel is judged against the page's reels")
        acc = IgAccount.objects.get(username="fit_home_a")
        self.assertIsNotNone(acc.baseline_reel)

    def test_the_same_batch_twice_changes_nothing(self):
        self.apply()
        out = self.apply()
        self.assertEqual((out["new"], out["updated"]), (0, 0))
        self.assertEqual(IgPost.objects.count(), 12)
        self.assertEqual(IgPostSnapshot.objects.count(), 12, "no new reading when nothing changed")
        self.assertEqual(IgAccount.objects.count(), 3)

    def test_new_numbers_update_the_post_and_add_a_reading_only_after_an_hour(self):
        self.apply()
        first = timezone.now()
        self.pages["fit_home_a"][1]["likes"] = 2000
        with mock.patch.object(timezone, "now", return_value=first + timedelta(minutes=20)):
            out = self.apply()
        self.assertEqual(out["updated"], 1)
        self.assertEqual(IgPost.objects.get(code="HA2").likes, 2000)
        self.assertEqual(IgPostSnapshot.objects.filter(post__code="HA2").count(), 1, "20 minutes later: too soon for a new reading")
        self.pages["fit_home_a"][1]["likes"] = 2600
        with mock.patch.object(timezone, "now", return_value=first + timedelta(hours=5)):
            self.apply()
        self.assertEqual(IgPostSnapshot.objects.filter(post__code="HA2").count(), 2)

    def test_growth_is_measured_between_two_readings(self):
        self.apply()
        first = timezone.now()
        self.pages["fit_home_b"][0]["likes"] = 9000
        self.pages["fit_home_b"][0]["comments"] = 400
        with mock.patch.object(timezone, "now", return_value=first + timedelta(hours=6)):
            self.apply()
        post = IgPost.objects.get(code="HB1")
        self.assertIsNotNone(post.growth)
        self.assertGreater(post.growth, 2.0, "it gained far faster than its own earlier pace")
        self.assertAlmostEqual(IgPost.objects.get(code="HB2").growth, 0.0, msg="a post whose numbers did not move has no growth")

    def test_clusters_hashtags_and_sounds_are_built_for_the_store(self):
        out = self.apply()
        self.assertGreaterEqual(out["rebuilt"]["clusters"], 2)
        labels = list(IgTrendCluster.objects.filter(store=self.store, active=True).values_list("label", flat=True))
        self.assertTrue(any("تمرین در خانه" in l for l in labels), labels)
        top = IgTrendCluster.objects.filter(store=self.store, active=True).order_by("-score").first()
        self.assertIn("تمرین در خانه", top.label)
        self.assertGreaterEqual(top.accounts_count, 2)
        self.assertTrue(top.why and top.why[0])
        self.assertTrue(IgHashtag.objects.filter(store=self.store, tag="تمرین_در_خانه").exists())
        audio = IgAudio.objects.get(store=self.store, title="آهنگ اول")
        self.assertEqual((audio.reels, audio.accounts), (2, 2))

    def test_clusters_only_use_the_pages_the_store_watches(self):
        self.apply()
        other_user, other = make_store("فروشگاه دیگر", "other-owner", "shoes")
        engine.rebuild_store(other)
        self.assertEqual(IgTrendCluster.objects.filter(store=other).count(), 0)
        IgSeed.objects.create(store=other, kind="account", value="diet_coach", source="user")
        engine.rebuild_store(other)
        labels = " ".join(IgTrendCluster.objects.filter(store=other, active=True).values_list("label", flat=True))
        self.assertIn("رژیم", labels)
        self.assertNotIn("تمرین در خانه", labels)

    def test_rebuilding_keeps_the_identity_of_a_topic_and_retires_missing_ones(self):
        self.apply()
        keys = set(IgTrendCluster.objects.filter(store=self.store, active=True).values_list("key", flat=True))
        engine.rebuild_store(self.store)
        self.assertEqual(set(IgTrendCluster.objects.filter(store=self.store, active=True).values_list("key", flat=True)), keys)
        IgSeed.objects.filter(store=self.store).delete()
        engine.rebuild_store(self.store)
        self.assertEqual(IgTrendCluster.objects.filter(store=self.store, active=True).count(), 0)
        self.assertEqual(IgTrendCluster.objects.filter(store=self.store).count(), len(keys), "retired, not deleted: ideas and dismissals keep their row")

    def test_pages_read_join_the_watch_list_unless_asked_not_to(self):
        self.apply()
        self.assertEqual(set(IgSeed.objects.filter(store=self.store, kind="account").values_list("value", flat=True)), set(self.pages))
        self.assertFalse(IgSeed.objects.filter(store=self.store, kind="account", scrape=True).exists(), "an imported page is not scanned unless the owner says so")
        user2, store2 = make_store("دوم", "owner-2")
        ingest.apply_batch(store2, node_batch(store2.pk, pages=self.pages), add_pages=False)
        self.assertFalse(IgSeed.objects.filter(store=store2).exists())

    def test_seed_statuses_follow_the_scan_report(self):
        for name in ("gone_page", "priv_page", "ok_page"):
            IgSeed.objects.create(store=self.store, kind="account", value=name)
        batch = node_batch(self.store.pk, pages={"ok_page": [abagram_post("OK1")]})
        batch["per_account"].update({"gone_page": {"status": "not_found", "posts": 0}, "priv_page": {"status": "private", "posts": 0}})
        ingest.apply_batch(self.store, batch)
        gone = IgSeed.objects.get(store=self.store, value="gone_page")
        self.assertEqual((gone.last_status, gone.fail_count, gone.scrape), ("not_found", 1, True))
        ingest.apply_batch(self.store, batch)
        gone.refresh_from_db()
        self.assertFalse(gone.scrape, "two «not found» answers switch the page off")
        self.assertIn("پیدا نشد", gone.note)
        priv = IgSeed.objects.get(store=self.store, value="priv_page")
        self.assertFalse(priv.scrape)
        ok = IgSeed.objects.get(store=self.store, value="ok_page")
        self.assertEqual((ok.last_status, ok.fail_count), ("ok", 0))
        self.assertIsNotNone(ok.last_read_at)

    def test_import_of_an_abagram_export_end_to_end_ignores_followers(self):
        docs = [abagram_export(name, [dict(r) for r in rows]) for name, rows in self.pages.items()]
        merged = normalize.merge_batches([normalize.from_abagram_page(d) for d in docs])
        out = ingest.apply_batch(self.store, merged)
        self.assertEqual(out["posts"], 12)
        self.assertFalse(IgAccount.objects.filter(username__startswith="follower").exists())
        blob = "".join(IgAccount.objects.values_list("biography", flat=True)) + "".join(IgPost.objects.values_list("caption", flat=True))
        self.assertNotIn("PRIVATE-FOLLOWER-DATA", blob)

    def test_hidden_likes_are_estimated_and_flagged_in_the_explanation(self):
        batch = node_batch(self.store.pk, pages={"hid_page": [abagram_post("H1", 30, likes=None, comments=50, likes_hidden=True),
                                                              abagram_post("H2", 80, likes=None, comments=10, likes_hidden=True),
                                                              abagram_post("H3", 120, likes=None, comments=12, likes_hidden=True)]})
        ingest.apply_batch(self.store, batch)
        self.assertTrue(IgPost.objects.get(code="H1").explain["estimated"])

    def test_old_readings_are_forgotten(self):
        self.apply()
        n = ingest.prune_snapshots(timezone.now() + timedelta(days=30))
        self.assertEqual(n, 12)

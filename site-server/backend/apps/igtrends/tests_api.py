"""The HTTP surface: overview, seeds, import (works with the node off), the token door, scan, briefs, settings."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.trend_models import Trend, TrendIdea
from apps.compute.models import ComputeJob, ComputeNode
from apps.products.models import Product

from . import engine, ideas, ingest, views
from .models import IgAccount, IgPost, IgScanRun, IgSeed, IgSettings, IgStoreConfig, IgTrendCluster
from .testkit import abagram_export, abagram_post, make_store, niche_pages, node_batch

TMP = tempfile.mkdtemp(prefix="nm-igtrends-test-")


def upload(name, doc):
    return SimpleUploadedFile(name, json.dumps(doc, ensure_ascii=False).encode("utf-8"), content_type="application/json")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ApiTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.base = "/api/v1/stores/%d/igtrends/" % self.store.pk

    def exports(self):
        return [upload("abagram-%s.json" % n, abagram_export(n, rows)) for n, rows in niche_pages().items()]

    # ---- who may
    def test_anonymous_and_strangers_get_nothing(self):
        self.assertIn(APIClient().get(self.base).status_code, (401, 403))
        stranger = User.objects.create_user("stranger", password="x")
        c = APIClient()
        c.force_authenticate(stranger)
        self.assertEqual(c.get(self.base).status_code, 404)
        self.assertEqual(c.post(self.base + "scan/", {}, format="json").status_code, 404)

    # ---- overview
    def test_overview_of_a_new_gym_store_applies_the_starter_pack_and_explains_the_node(self):
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        kinds = {s["kind"] for s in d["seeds"]}
        self.assertEqual(kinds, {"account", "hashtag", "keyword"})
        self.assertTrue(any(s["value"] == "تمرین_در_خانه" for s in d["seeds"]))
        self.assertFalse(d["node"]["ready"])
        self.assertEqual(d["node"]["problem"], "no_node")
        self.assertIn("START.bat", d["node"]["message"])
        self.assertEqual(d["clusters"], [])
        self.assertTrue(d["can_edit"])
        # the starter pack is applied once, not again
        n = IgSeed.objects.count()
        self.client.get(self.base)
        self.assertEqual(IgSeed.objects.count(), n)

    def test_a_shop_that_is_not_about_fitness_gets_no_starter_pack(self):
        user, shop = make_store("فروشگاه کفش", "shoe-owner", "shoes")
        c = APIClient()
        c.force_authenticate(user)
        d = c.get("/api/v1/stores/%d/igtrends/" % shop.pk).json()
        self.assertEqual(d["seeds"], [])

    # ---- import
    def test_import_of_abagram_files_builds_trends_without_the_node(self):
        r = self.client.post(self.base + "import/", {"files": self.exports()}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["result"]["accounts"], 3)
        self.assertEqual(body["result"]["posts"], 12)
        self.assertEqual(body["run"]["state"], "ok")
        self.assertEqual(body["run"]["source"], "import")
        d = self.client.get(self.base).json()
        self.assertTrue(d["clusters"])
        top = d["clusters"][0]
        self.assertIn("تمرین در خانه", top["label"])
        self.assertTrue(top["why"])
        self.assertTrue(top["examples"] and top["examples"][0]["url"].startswith("https://www.instagram.com/"))
        self.assertTrue(d["top_posts"])
        self.assertTrue(any(h["tag"] == "تمرین_در_خانه" for h in d["hashtags"]))
        self.assertEqual(d["audio"][0]["title"], "آهنگ اول")
        self.assertEqual(d["runs"][0]["source"], "import")

    def test_import_mixes_good_and_bad_files(self):
        good = self.exports()[0]
        bad_json = SimpleUploadedFile("broken.json", b"{not json", content_type="application/json")
        wrong = upload("other.json", {"format": "something-else"})
        r = self.client.post(self.base + "import/", {"files": [good, bad_json, wrong]}, format="multipart")
        self.assertEqual(r.status_code, 201)
        problems = " ".join(r.json()["problems"])
        self.assertIn("broken.json", problems)
        self.assertIn("other.json", problems)
        self.assertEqual(r.json()["result"]["accounts"], 1)

    def test_import_with_nothing_readable_is_refused(self):
        r = self.client.post(self.base + "import/", {"files": [upload("x.json", {"format": "no"})]}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "unreadable")
        self.assertEqual(self.client.post(self.base + "import/", {}, format="multipart").json()["error"]["code"], "no_file")

    def test_import_size_limits(self):
        with mock.patch.object(views, "MAX_FILE", 50):
            r = self.client.post(self.base + "import/", {"files": [self.exports()[0]]}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("بزرگ", " ".join(r.json()["error"]["message"].split("|")))
        with mock.patch.object(views, "MAX_TOTAL", 50):
            r = self.client.post(self.base + "import/", {"files": self.exports()}, format="multipart")
        self.assertEqual(r.status_code, 413)

    def test_import_can_leave_the_pages_out_of_the_watch_list(self):
        r = self.client.post(self.base + "import/", {"files": [self.exports()[0]], "add_pages": "false"}, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(IgSeed.objects.filter(store=self.store, kind="account", value="fit_home_a").exists())

    def test_a_viewer_cannot_import_or_scan(self):
        from apps.stores.models import Membership
        viewer = User.objects.create_user("viewer", password="x")
        Membership.objects.create(store=self.store, user=viewer, role="VIEWER", is_active=True)
        c = APIClient()
        c.force_authenticate(viewer)
        self.assertEqual(c.get(self.base).status_code, 200)
        self.assertEqual(c.post(self.base + "scan/", {}, format="json").status_code, 403)
        self.assertEqual(c.post(self.base + "import/", {"files": self.exports()}, format="multipart").status_code, 403)
        self.assertFalse(c.get(self.base).json()["can_edit"])

    # ---- seeds
    def test_seed_crud(self):
        r = self.client.post(self.base + "seeds/", {"kind": "account", "value": "https://www.instagram.com/Some_Page/, @other.page\nbad name"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(sorted(s["value"] for s in r.json()["added"]), ["other.page", "some_page"])
        self.assertEqual(r.json()["invalid"], ["bad name"])
        r = self.client.post(self.base + "seeds/", {"kind": "hashtag", "value": "#تمرین خانگی"}, format="json")
        self.assertEqual(r.json()["added"][0]["value"], "تمرین_خانگی")
        self.assertEqual(self.client.post(self.base + "seeds/", {"kind": "account", "value": "bad name"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.base + "seeds/", {"kind": "nope", "value": "x"}, format="json").status_code, 400)
        seed = IgSeed.objects.get(store=self.store, value="some_page")
        r = self.client.patch(self.base + "seeds/%d/" % seed.pk, {"enabled": False, "note": "n"}, format="json")
        self.assertFalse(r.json()["enabled"])
        self.assertEqual(self.client.delete(self.base + "seeds/%d/" % seed.pk).status_code, 204)
        self.assertFalse(IgSeed.objects.filter(pk=seed.pk).exists())
        self.assertEqual(self.client.delete(self.base + "seeds/%d/" % seed.pk).status_code, 404)

    def test_seeds_of_another_store_cannot_be_touched(self):
        user2, store2 = make_store("دیگری", "owner-b")
        seed = IgSeed.objects.create(store=store2, kind="account", value="theirs")
        self.assertEqual(self.client.delete(self.base + "seeds/%d/" % seed.pk).status_code, 404)
        self.assertTrue(IgSeed.objects.filter(pk=seed.pk).exists())

    def test_reset_puts_the_starter_pack_back(self):
        self.client.get(self.base)
        IgSeed.objects.filter(store=self.store, kind="hashtag").delete()
        r = self.client.post(self.base + "seeds/reset/", {}, format="json")
        self.assertGreater(r.json()["added"], 10)
        self.assertTrue(IgSeed.objects.filter(store=self.store, kind="hashtag", value="بدنسازی").exists())

    def test_config(self):
        r = self.client.post(self.base + "config/", {"auto_scan": False, "interval_h": 1, "max_accounts": 99, "min_reread_h": 12}, format="json")
        self.assertEqual(r.json(), {"auto_scan": False, "interval_h": 2, "max_accounts": 12, "min_reread_h": 12})
        self.assertEqual(self.client.post(self.base + "config/", {"interval_h": "x"}, format="json").status_code, 400)

    # ---- the token door
    def push(self, key=None, node_token=None, batch=None, query=""):
        c = APIClient()
        headers = {}
        if key:
            headers["HTTP_X_IG_KEY"] = key
        if node_token:
            headers["HTTP_AUTHORIZATION"] = "Node " + node_token
        batch = batch if batch is not None else node_batch(self.store.pk, pages=niche_pages())
        return c.post("/api/v1/igtrends/ingest/" + query, batch, format="json", **headers)

    def test_ingest_needs_the_key_or_a_node_token(self):
        self.assertEqual(self.push().status_code, 401)
        self.assertEqual(self.push(key="wrong").status_code, 401)
        self.assertEqual(self.push(node_token="nope").status_code, 401)
        self.assertEqual(IgPost.objects.count(), 0)

    def test_ingest_with_the_key_stores_the_batch(self):
        key = IgSettings.get().ingest_key
        r = self.push(key=key)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["posts"], 12)
        self.assertEqual(IgPost.objects.count(), 12)
        self.assertEqual(IgScanRun.objects.get(store=self.store).source, "ingest")

    def test_ingest_with_a_node_token(self):
        node = ComputeNode.objects.create(name="gpu-1")
        self.assertEqual(self.push(node_token=node.token).status_code, 201)
        node.enabled = False
        node.save()
        self.assertEqual(self.push(node_token=node.token).status_code, 401)

    def test_ingest_needs_a_store_and_a_valid_batch(self):
        key = IgSettings.get().ingest_key
        batch = node_batch(self.store.pk, pages=niche_pages())
        batch["store_id"] = 99999
        self.assertEqual(self.push(key=key, batch=batch).json()["error"]["code"], "no_store")
        batch.pop("store_id")
        self.assertEqual(self.push(key=key, batch=batch, query="?store=%d" % self.store.pk).status_code, 201)
        self.assertEqual(self.push(key=key, batch={"format": "x", "store_id": self.store.pk}).json()["error"]["code"], "bad_batch")

    def test_ingest_key_is_staff_only_and_can_be_rotated(self):
        self.assertEqual(self.client.get("/api/v1/igtrends/settings/").status_code, 403)
        admin = User.objects.create_user("admin1", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(admin)
        old = c.get("/api/v1/igtrends/settings/").json()["ingest_key"]
        new = c.post("/api/v1/igtrends/settings/", {"rotate": True}, format="json").json()["ingest_key"]
        self.assertNotEqual(old, new)
        self.assertEqual(self.push(key=old).status_code, 401)
        self.assertEqual(self.push(key=new).status_code, 201)

    # ---- scan
    def ready_node(self, **abagram):
        rep = {"ready": True, "problem": None, "state": "up", "signed_in": True, "account": "demo", "url": "http://127.0.0.1:8791/"}
        rep.update(abagram)
        return ComputeNode.objects.create(name="home-gpu", last_seen=timezone.now(), capabilities={"instagram": True, "abagram": rep, "agent": "2.11", "kinds": ["echo", "ig.scrape", "ig.health"]})

    def test_scan_without_a_node_says_what_to_do(self):
        r = self.client.post(self.base + "scan/", {}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "no_node")
        self.assertIn("START.bat", r.json()["error"]["message"])

    def test_scan_queues_one_small_durable_job(self):
        self.ready_node()
        self.client.get(self.base)
        r = self.client.post(self.base + "scan/", {}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        run = IgScanRun.objects.get(pk=r.json()["id"])
        job = ComputeJob.objects.get(uid=run.job_uid)
        self.assertEqual(job.kind, "ig.scrape")
        self.assertEqual(job.state, "QUEUED")
        p = job.payload
        self.assertEqual(p["store_id"], self.store.pk)
        self.assertEqual(p["run_id"], run.pk)
        self.assertLessEqual(len(p["accounts"]), 5)
        self.assertEqual(p["pace_s"], [45, 110])
        self.assertTrue(p["fresh"])
        self.assertEqual(job.max_attempts, 1, "a scan is never retried by itself")
        self.assertEqual(self.client.post(self.base + "scan/", {}, format="json").status_code, 409)

    def test_scan_names_given_by_the_user_are_cleaned(self):
        self.ready_node()
        r = self.client.post(self.base + "scan/", {"accounts": ["@Some_Page", "bad name", "https://instagram.com/other.one/"]}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(IgScanRun.objects.get().accounts, ["some_page", "other.one"])

    # ---- briefs
    def build_clusters(self):
        ingest.apply_batch(self.store, node_batch(self.store.pk, pages=niche_pages()))
        return IgTrendCluster.objects.filter(store=self.store, active=True).order_by("-score").first()

    def test_brief_without_ai_is_a_labelled_template_and_a_trend_idea(self):
        cluster = self.build_clusters()
        Product.objects.create(store=self.store, name="برنامهٔ تمرین در خانه", price=100, is_available=True)
        with mock.patch.object(ideas.research_llm, "status", return_value=(False, "no model")):
            r = self.client.post(self.base + "clusters/%d/brief/" % cluster.pk, {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d["source"], "template")
        self.assertIn("بدونِ هوش مصنوعی", d["brief"]["idea"])
        self.assertIn("در دسترس نیست", d["note"])
        self.assertEqual(d["brief"]["product_name"], "برنامهٔ تمرین در خانه")
        self.assertTrue(d["brief"]["outline"])
        self.assertTrue(d["brief"]["examples"])
        idea = TrendIdea.objects.get(pk=d["idea_id"])
        self.assertEqual(idea.store, self.store)
        self.assertEqual(idea.trend.region, "IG")
        self.assertEqual(idea.trend.source, "instagram_scrape")
        self.assertEqual(idea.product.name, "برنامهٔ تمرین در خانه")
        self.assertEqual(idea.kind, "VIDEO")
        cluster.refresh_from_db()
        self.assertEqual(cluster.idea_trend_id, idea.trend_id)
        self.assertEqual(cluster.brief["source"], "template")
        # asking again replaces the open idea instead of piling up
        with mock.patch.object(ideas.research_llm, "status", return_value=(False, "no model")):
            self.client.post(self.base + "clusters/%d/brief/" % cluster.pk, {}, format="json")
        self.assertEqual(TrendIdea.objects.filter(store=self.store, state="OPEN").count(), 1)

    def test_brief_uses_the_model_when_it_answers_well_and_falls_back_when_it_does_not(self):
        cluster = self.build_clusters()
        good = {"kind": "VIDEO", "hook": "تمرین در خانه را از امروز شروع کن", "idea": "یک ریلز ۲۰ ثانیه‌ای که یک حرکتِ ساده را نشان می‌دهد و در پایان برنامه را معرفی می‌کند.",
                "why": "چند صفحه همین موضوع را ساخته‌اند و فروشگاهِ شما هم باشگاه است", "outline": ["قلاب", "نمایش", "دعوت"], "caption": "کپشن [جزئیات]", "hashtags": ["#تمرین"]}
        with mock.patch.object(ideas.research_llm, "status", return_value=(True, "")), mock.patch.object(ideas.research_llm, "ask_json", return_value=good):
            d = self.client.post(self.base + "clusters/%d/brief/" % cluster.pk, {}, format="json").json()
        self.assertEqual(d["source"], "ai")
        self.assertEqual(d["brief"]["hook"], good["hook"])
        for failure in (ideas.research_llm.LLMUnavailable("down"), RuntimeError("HTTP 402 payment required")):
            with mock.patch.object(ideas.research_llm, "status", return_value=(True, "")), mock.patch.object(ideas.research_llm, "ask_json", side_effect=failure):
                d = self.client.post(self.base + "clusters/%d/brief/" % cluster.pk, {}, format="json").json()
            self.assertEqual(d["source"], "template")
            self.assertIn("جواب نداد", d["note"])

    def test_dismissing_a_topic_hides_it(self):
        cluster = self.build_clusters()
        self.assertEqual(self.client.post(self.base + "clusters/%d/dismiss/" % cluster.pk, {}, format="json").json()["dismissed"], True)
        d = self.client.get(self.base).json()
        self.assertNotIn(cluster.pk, [c["id"] for c in d["clusters"]])
        self.assertEqual(d["dismissed_count"], 1)

    def test_clusters_of_another_store_are_not_reachable(self):
        cluster = self.build_clusters()
        user2, store2 = make_store("دیگری", "owner-c")
        c = APIClient()
        c.force_authenticate(user2)
        self.assertEqual(c.post("/api/v1/stores/%d/igtrends/clusters/%d/brief/" % (store2.pk, cluster.pk), {}, format="json").status_code, 404)

    def test_overview_rebuilds_when_data_arrived(self):
        ingest.apply_batch(self.store, node_batch(self.store.pk, pages=niche_pages()), rebuild=False)
        IgStoreConfig.objects.filter(store=self.store).update(dirty=True)
        self.assertEqual(IgTrendCluster.objects.filter(store=self.store).count(), 0)
        d = self.client.get(self.base).json()
        self.assertTrue(d["clusters"])
        self.assertTrue({"fit_home_a", "fit_home_b", "diet_coach"} <= set(engine.watched_usernames(self.store)), "the read pages join the watched ones")
        self.assertGreaterEqual(d["totals"]["pages"], 3)

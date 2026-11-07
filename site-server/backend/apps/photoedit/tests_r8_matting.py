"""دورِ ۸: حذفِ پس‌زمینه با چند مدل — وضعیتِ مدل‌ها، اجرا و مقایسه از راهِ صفِ ماندگار، نتیجه به کتابخانه. بی شبکه، بی دانلود."""
import json
from datetime import timedelta
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.stores.models import Store

from . import matting, matting_nodes as mn
from .models import PhotoAsset
from .tests import ApiTestBase, photo


def matting_node(online=True, models=None, **caps):
    return ComputeNode.objects.create(
        name="gpu-mat", last_seen=timezone.now() if online else timezone.now() - timedelta(hours=2),
        capabilities={"photo": True, "photo_matting": True, "matting_models": models or {},
                      "matting_runtime": {"ok": True, "providers": ["CPUExecutionProvider"], "message": ""}} | caps)


class MattingStatusTests(ApiTestBase):
    def test_no_node_means_waiting_for_download_and_rvm_ready(self):
        with mock.patch.object(matting, "available", return_value=True):
            j = self.api.get(f"{self.base}/matting/").json()
        rows = {m["id"]: m for m in j["models"]}
        self.assertEqual(list(rows), ["rvm", "u2netp", "isnet", "birefnet-lite"])
        self.assertEqual((rows["rvm"]["where"], rows["rvm"]["state"]), ("site", "installed"))
        for k in ("u2netp", "isnet", "birefnet-lite"):
            self.assertEqual((rows[k]["where"], rows[k]["state"]), ("node", "missing"), k)
            self.assertIn("دانلود", rows[k]["state_fa"])
        self.assertFalse(j["node_known"])
        self.assertEqual(j["default"], "rvm")

    def test_node_report_installed_downloading_failed(self):
        matting_node(models={"u2netp": {"state": "installed", "size_mb": 5}, "isnet": {"state": "downloading", "progress": 0.4},
                             "birefnet-lite": {"state": "failed", "error": "disk full"}},
                     matting_runtime={"ok": True, "providers": ["CPUExecutionProvider"], "message": ""})
        j = self.api.get(f"{self.base}/matting/").json()
        rows = {m["id"]: m for m in j["models"]}
        self.assertEqual(rows["u2netp"]["state"], "installed")
        self.assertEqual(rows["u2netp"]["installed_on"], ["gpu-mat"])
        self.assertEqual(rows["isnet"]["state"], "downloading")
        self.assertIn("۴۰", rows["isnet"]["state_fa"].translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")))
        self.assertEqual((rows["birefnet-lite"]["state"], rows["birefnet-lite"]["error"]), ("failed", "disk full"))
        self.assertTrue(j["node_known"] and j["node_online"])
        self.assertTrue(j["runtime"]["ok"])


class MattingRunTests(ApiTestBase):
    def _alpha(self, img, passes=3):
        a = np.zeros((img.height, img.width), np.float32)
        a[img.height // 4:3 * img.height // 4, img.width // 4:3 * img.width // 4] = 1.0
        return a

    def run_models(self, models, aid=None):
        aid = aid or self.upload(photo(seed=21))[0]
        r = self.api.post(f"{self.base}/matting/run/", {"asset": aid, "models": models}, format="json")
        return aid, r

    def test_compare_runs_site_now_and_queues_node_models_durably(self):
        matting_node(online=False, models={"u2netp": {"state": "installed"}})
        with mock.patch.object(matting, "alpha", side_effect=self._alpha), mock.patch.object(matting, "available", return_value=True):
            aid, r = self.run_models(["rvm", "u2netp", "isnet", "birefnet-lite"])
        self.assertEqual(r.status_code, 201, r.content)
        jobs = {j["model"]: j for j in r.json()["jobs"]}
        self.assertEqual(set(jobs), {"rvm", "u2netp", "isnet", "birefnet-lite"})
        self.assertEqual(jobs["rvm"]["state"], "ready")
        self.assertTrue(jobs["rvm"]["url"].endswith(f"/matting/site/{aid}/"))
        for k in ("u2netp", "isnet", "birefnet-lite"):
            self.assertEqual(jobs[k]["state"], "queued", k)
            self.assertEqual(jobs[k]["message"], "در صف — منتظرِ سرورِ پردازش")
            cj = ComputeJob.objects.get(uid=jobs[k]["uid"])
            self.assertEqual((cj.kind, cj.origin, cj.state), ("photo.matting", "photomatting", "QUEUED"))
            self.assertEqual(cj.payload["model"], k)
            self.assertTrue(cj.payload["keep_size"])
        # نتیجهٔ RVM قابلِ دیدن است
        png = self.api.get(f"{self.base}/matting/site/{aid}/")
        self.assertEqual((png.status_code, png["Content-Type"]), (200, "image/png"))
        # پنل می‌پرسد: هنوز منتظر
        uids = ",".join(j["uid"] for j in jobs.values() if j["uid"])
        got = self.api.get(f"{self.base}/matting/jobs/?uids={uids}").json()
        self.assertEqual({x["state"] for x in got["jobs"]}, {"queued"})
        self.assertFalse(got["node_online"])

    def test_node_finishes_one_model_then_result_is_served_and_importable(self):
        node = matting_node(models={"isnet": {"state": "installed"}})
        aid, r = self.run_models(["isnet"])
        job_row = r.json()["jobs"][0]
        job = ComputeJob.objects.get(uid=job_row["uid"])
        got = compute.claim(node)
        self.assertEqual(got.pk, job.pk)
        out = Image.new("RGBA", (40, 30), (200, 10, 10, 255))
        out.save(compute.output_path(job, "cutout.png"))
        Image.new("L", (40, 30), 255).save(compute.output_path(job, "mask.png"))
        compute.output_path(job, "photo-matting.json").write_text(json.dumps({"model": "isnet", "seconds": 1.4, "size": [40, 30], "device": "cpu"}), encoding="utf-8")
        compute.finish(job, node, True, meta={"primary": "cutout.png", "model": "isnet"})
        st = self.api.get(f"{self.base}/matting/jobs/?uids={job_row['uid']}").json()["jobs"][0]
        self.assertEqual((st["state"], st["model"], st["device"]), ("ready", "isnet", "cpu"))
        self.assertTrue(st["url"].endswith("/cutout.png"))
        png = self.api.get(f"{self.base}/matting/jobs/{job_row['uid']}/cutout.png")
        self.assertEqual((png.status_code, png["Content-Type"]), (200, "image/png"))
        n0 = PhotoAsset.objects.count()
        ap = self.api.post(f"{self.base}/matting/apply/", {"asset": aid, "model": "isnet", "uid": job_row["uid"]}, format="json")
        self.assertEqual(ap.status_code, 201, ap.content)
        self.assertEqual(PhotoAsset.objects.count(), n0 + 1)
        self.assertIn("isnet", ap.json()["asset"]["title"])

    def test_unknown_model_and_no_registered_node_are_reported_not_fatal(self):
        aid, r = self.run_models(["rvm-x", "isnet"])
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertEqual(j["jobs"], [])
        self.assertEqual({s["model"] for s in j["skipped"]}, {"rvm-x", "isnet"})
        self.assertEqual(self.api.post(f"{self.base}/matting/run/", {"asset": aid, "models": []}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/matting/run/", {"asset": 999999, "models": ["rvm"]}, format="json").status_code, 404)

    def test_site_model_failure_message_when_model_is_missing(self):
        with mock.patch.object(matting, "alpha", return_value=None):
            aid, r = self.run_models(["rvm"])
        row = r.json()["jobs"][0]
        self.assertEqual(row["state"], "failed")
        self.assertIn("مدلِ", row["message"])
        self.assertEqual(self.api.get(f"{self.base}/matting/site/{aid}/").status_code, 404)

    def test_other_users_store_cannot_see_results(self):
        node = matting_node(models={"isnet": {"state": "installed"}})
        aid, r = self.run_models(["isnet"])
        uid = r.json()["jobs"][0]["uid"]
        other = get_user_model().objects.create_user("intruder-r8", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}/matting/jobs/{uid}/cutout.png").status_code, 404)
        self.assertEqual(c.get(f"{self.base}/matting/").status_code, 404)
        # مالک هم تا وقتی کار تمام نشده بریده‌ای نمی‌بیند
        self.assertEqual(self.api.get(f"{self.base}/matting/jobs/{uid}/cutout.png").status_code, 404)
        del node

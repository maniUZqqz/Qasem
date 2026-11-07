"""«جمع‌کردنِ فایل‌های پروژه»: one zip with the project and every original it uses."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import collect

from .models import UploadedVideo, VideoProject

TEMP = tempfile.mkdtemp(prefix="nm-collect-")


def clip(ref, at=0.0):
    return {"id": f"c{at}", "type": "media", "ref": ref, "label": "x", "kind": "video", "at": at, "start": 0, "end": 1, "src": 2, "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1}


class RefsTests(SimpleTestCase):
    def test_every_distinct_media_ref_including_sequences_luts_and_mattes(self):
        data = {"tracks": [{"clips": [clip("video:1"), clip("video:1", 1), clip("shape"), clip("adjust"), clip("seq:s1"),
                                      {**clip("video:2", 2), "lut": {"key": "warm", "amount": 1}, "matte": {"key": "m1"}}]}],
                "sequences": {"s1": {"tracks": [{"clips": [clip("audio:7"), clip("video:1")]}]}}}
        self.assertEqual(collect.refs_of(data), ["video:1", "video:2", "lut:warm", "matte:m1", "audio:7"])
        self.assertEqual(collect.refs_of({}), [])
        self.assertEqual(collect.refs_of({"tracks": [{"clips": ["junk", None]}]}), [])


@override_settings(MEDIA_ROOT=TEMP)
class CollectTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.owner = User.objects.create_user("co-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه جمع‌آوری")
        self.client.force_login(self.owner)
        root = Path(TEMP) / "uploads/videos"
        root.mkdir(parents=True, exist_ok=True)
        (root / "a.mp4").write_bytes(b"A" * 1000)
        (root / "b.mp4").write_bytes(b"B" * 2000)
        self.a = UploadedVideo.objects.create(store=self.store, title="الف", video="uploads/videos/a.mp4", state="READY", duration=2.0)
        self.b = UploadedVideo.objects.create(store=self.store, title="ب", video="uploads/videos/b.mp4", state="READY", duration=2.0)
        self.other = Store.objects.create(owner=self.owner, name="دیگری")
        (root / "x.mp4").write_bytes(b"X" * 500)
        self.foreign = UploadedVideo.objects.create(store=self.other, title="غریبه", video="uploads/videos/x.mp4", state="READY", duration=2.0)
        data = {"format": {"width": 240, "height": 426, "fps": 12}, "tracks": [{"id": "t", "kind": "video", "clips": [
            clip(f"video:{self.a.pk}"), clip(f"video:{self.b.pk}", 1), clip(f"video:{self.foreign.pk}", 2), clip("video:999999", 3), clip("shape", 4)]}]}
        self.project = VideoProject.objects.create(store=self.store, title="پروژهٔ جمع", data=data)

    def go(self):
        with patch("apps.content.views_editor_pro.dispatch_job", side_effect=lambda job, task, *a, **k: task(*a, **k) and None):
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/editor/projects/{self.project.pk}/collect/")
        self.assertEqual(r.status_code, 202, r.content)
        return Job.objects.get(pk=r.json()["job_id"])

    def test_the_zip_holds_the_project_the_shops_own_originals_and_a_manifest_with_notes(self):
        job = self.go()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(job.result["files"], 2)
        self.assertEqual(len(job.result["skipped"]), 2, "the other shop's file and the missing one are notes, never read")
        path = Path(TEMP) / job.result["url"].replace("/media/", "", 1)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            self.assertIn("project.json", names)
            self.assertIn("manifest.json", names)
            media = sorted(n for n in names if n.startswith("media/"))
            self.assertEqual(len(media), 2)
            self.assertEqual(zf.read(media[0]), b"A" * 1000)
            self.assertEqual(json.loads(zf.read("project.json"))["format"]["width"], 240, "the project JSON is stored untouched")
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual([m["ref"] for m in manifest["files"]], [f"video:{self.a.pk}", f"video:{self.b.pk}"])
            self.assertNotIn(b"X" * 100, b"".join(zf.read(n) for n in media), "the other shop's bytes are not in the archive")

    def test_a_too_big_project_is_refused_with_a_clear_sentence(self):
        with patch.object(collect, "MAX_BYTES", 1500):
            job = self.go()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("گیگابایت", job.error)

    def test_only_the_newest_earlier_archive_is_kept(self):
        first = self.go()
        second = self.go()
        folder = (Path(TEMP) / "generated/editing" / f"project_{self.project.pk}" / "exports")
        zips = sorted(p.name for p in folder.glob("collect_*.zip"))
        self.assertEqual(zips, [f"collect_{first.pk}.zip", f"collect_{second.pk}.zip"])
        third = self.go()
        zips = sorted(p.name for p in folder.glob("collect_*.zip"))
        self.assertEqual(zips, [f"collect_{second.pk}.zip", f"collect_{third.pk}.zip"])

    def test_other_shops_and_anonymous_users_cannot_collect(self):
        stranger = User.objects.create_user("co-stranger", password="x")
        self.client.force_login(stranger)
        r = self.client.post(f"/api/v1/stores/{self.store.pk}/editor/projects/{self.project.pk}/collect/")
        self.assertIn(r.status_code, (403, 404))
        self.client.logout()
        r = self.client.post(f"/api/v1/stores/{self.store.pk}/editor/projects/{self.project.pk}/collect/")
        self.assertIn(r.status_code, (401, 403))

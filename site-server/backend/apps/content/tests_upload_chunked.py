"""Resumable video upload: pieces in order, a repeated piece, a gap, resume by key (also after a "reload"), size/type/ownership checks,
a corrupt file, cancel, the stale sweep — all through the real endpoints with real ffmpeg on a tiny clip."""
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.video.ffmpeg import FFMPEG

from . import views_upload
from .models import UploadedVideo
from .tests_editor_modes import make_video

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-upload-chunked-")


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ChunkedUploadTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            return
        cls.clip = Path(TEMP_MEDIA) / "src.mp4"
        make_video(cls.clip, size="160x90", seconds=3)
        cls.data = cls.clip.read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "data"):
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("up-chunk", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه آپلود تکه‌ای")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/videos/uploads/"
        shutil.rmtree(Path(TEMP_MEDIA) / "uploads", ignore_errors=True)

    def start(self, **over):
        body = {"name": "clip.mp4", "size": len(self.data), "key": "clip.mp4:1:2", **over}
        return self.client.post(self.base, json.dumps(body), content_type="application/json")

    def put(self, uid, offset, chunk):
        return self.client.put(f"{self.base}{uid}/?offset={offset}", data=chunk, content_type="application/octet-stream")

    def finish(self, uid):
        with patch("apps.content.views_upload.dispatch_job", side_effect=run_inline):
            return self.client.post(f"{self.base}{uid}/finish/", "{}", content_type="application/json")

    def test_a_file_in_pieces_becomes_an_analysed_upload(self):
        r = self.start()
        self.assertEqual(r.status_code, 201, r.content)
        uid = r.json()["upload_id"]
        self.assertEqual((r.json()["received"], r.json()["resumed"]), (0, False))
        step = max(1, len(self.data) // 4)
        pos = 0
        while pos < len(self.data):
            piece = self.data[pos:pos + step]
            a = self.put(uid, pos, piece)
            self.assertEqual(a.status_code, 200, a.content)
            pos += len(piece)
            self.assertEqual(a.json()["received"], pos)
        self.assertEqual(self.client.get(f"{self.base}{uid}/").json()["received"], len(self.data))
        f = self.finish(uid)
        self.assertEqual(f.status_code, 201, f.content)
        row = UploadedVideo.objects.get(pk=f.json()["video"]["id"])
        self.assertEqual(row.title, "clip.mp4")
        self.assertEqual(Path(row.video.path).read_bytes(), self.data)           # byte for byte what was sent
        job = Job.objects.get(pk=f.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)              # the usual analysis ran
        row.refresh_from_db()
        self.assertEqual(row.state, UploadedVideo.State.READY)
        self.assertFalse(list((Path(TEMP_MEDIA) / "uploads" / "tmp" / f"s{self.store.pk}").glob("*")), "no leftovers of the session")

    def test_a_repeated_piece_is_accepted_and_a_gap_is_refused_with_the_right_offset(self):
        uid = self.start().json()["upload_id"]
        half = len(self.data) // 2
        self.assertEqual(self.put(uid, 0, self.data[:half]).json()["received"], half)
        dup = self.put(uid, 0, self.data[:half])                                  # the answer got lost, the client sends it again
        self.assertEqual((dup.status_code, dup.json()["received"], dup.json().get("duplicate")), (200, half, True))
        overlap = self.put(uid, half - 10, self.data[half - 10:])                 # partly known: only the new tail counts
        self.assertEqual(overlap.json()["received"], len(self.data))
        gap = self.put(uid, len(self.data) + 5, b"x")
        self.assertEqual(gap.status_code, 409)
        self.assertEqual(gap.json()["error"]["received"], len(self.data))
        self.assertEqual(self.finish(uid).status_code, 201)

    def test_gap_in_the_middle(self):
        uid = self.start().json()["upload_id"]
        r = self.put(uid, 1000, self.data[1000:2000])
        self.assertEqual((r.status_code, r.json()["error"]["code"], r.json()["error"]["received"]), (409, "gap", 0))

    def test_finishing_early_is_refused_and_says_how_far_it_got(self):
        uid = self.start().json()["upload_id"]
        self.put(uid, 0, self.data[:1000])
        r = self.finish(uid)
        self.assertEqual((r.status_code, r.json()["error"]["code"], r.json()["error"]["received"]), (409, "incomplete", 1000))

    def test_the_same_file_picked_again_resumes_where_it_stopped_even_after_a_reload(self):
        first = self.start().json()
        self.put(first["upload_id"], 0, self.data[:5000])
        again = self.start().json()                                                # a fresh page, same name+size+date key
        self.assertEqual((again["upload_id"], again["received"], again["resumed"]), (first["upload_id"], 5000, True))
        other = self.start(key="other:1:2").json()
        self.assertNotEqual(other["upload_id"], first["upload_id"])
        self.assertEqual(other["received"], 0)

    def test_validation_messages_are_persian(self):
        bad = self.start(name="notes.txt")
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (400, "wrong_type"))
        self.assertIn("فرمت", bad.json()["error"]["message"])
        big = self.start(size=900 * 1024 * 1024)
        self.assertEqual((big.status_code, big.json()["error"]["code"]), (400, "too_big"))
        self.assertIn("مگابایت", big.json()["error"]["message"])
        self.assertEqual(self.start(size=0).status_code, 400)
        self.assertEqual(self.start(name="").status_code, 400)
        uid = self.start().json()["upload_id"]
        self.assertEqual(self.put(uid, 0, b"").status_code, 400)
        self.assertEqual(self.client.put(f"{self.base}{uid}/?offset=abc", data=b"x", content_type="application/octet-stream").status_code, 400)
        with patch.object(views_upload, "CHUNK_MAX", 10):
            self.assertEqual(self.put(uid, 0, b"x" * 11).status_code, 413)
        over = self.put(uid, 0, self.data + b"extra")
        self.assertEqual((over.status_code, over.json()["error"]["code"]), (409, "overflow"))

    def test_a_file_that_is_not_a_video_is_refused_at_the_end_with_a_clear_sentence(self):
        junk = b"this is not a movie " * 50
        uid = self.start(name="fake.mp4", size=len(junk), key="fake").json()["upload_id"]
        self.put(uid, 0, junk)
        r = self.finish(uid)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "not_video"))
        self.assertIn("سالم نیست", r.json()["error"]["message"])
        self.assertEqual(UploadedVideo.objects.count(), 0)
        self.assertEqual(self.client.get(f"{self.base}{uid}/").status_code, 404)    # the broken session is gone

    def test_other_people_cannot_touch_a_session_and_cancel_removes_it(self):
        uid = self.start().json()["upload_id"]
        self.put(uid, 0, self.data[:100])
        other = User.objects.create_user("up-chunk-2", password="x")
        self.client.force_login(other)
        self.assertIn(self.client.get(f"{self.base}{uid}/").status_code, (403, 404))
        self.assertIn(self.put(uid, 100, b"x").status_code, (403, 404))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.delete(f"{self.base}{uid}/").status_code, 204)
        self.assertEqual(self.client.get(f"{self.base}{uid}/").status_code, 404)
        self.assertEqual(self.put(uid, 0, b"x").status_code, 404)
        self.assertEqual(self.client.delete(f"{self.base}{uid}/").status_code, 204)      # cancelling twice is fine
        self.assertEqual(self.client.get(f"{self.base}../../x/").status_code, 404)

    def test_abandoned_sessions_are_swept_after_two_days_and_the_open_count_is_capped(self):
        old = self.start(key="old").json()["upload_id"]
        meta = views_upload._meta_path(self.store.pk, old)
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["touched"] = time.time() - 3 * 24 * 3600
        meta.write_text(json.dumps(data), encoding="utf-8")
        self.start(key="new")                                                        # starting another one sweeps the stale one
        self.assertEqual(self.client.get(f"{self.base}{old}/").status_code, 404)
        for i in range(views_upload.MAX_OPEN_PER_STORE + 2):
            self.assertEqual(self.start(key=f"k{i}").status_code, 201)
        open_now = list(views_upload._root(self.store.pk).glob("*.json"))
        self.assertLessEqual(len(open_now), views_upload.MAX_OPEN_PER_STORE)

    def test_a_full_disk_is_said_plainly(self):
        class Usage:
            free = 10 * 1024 * 1024
        with patch("apps.content.views_upload.shutil.disk_usage", return_value=Usage()):
            r = self.start()
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (507, "disk_full"))
        self.assertIn("فضای سرور", r.json()["error"]["message"])

    def test_the_old_single_post_still_works(self):
        with patch("apps.content.views_editing.dispatch_job", side_effect=run_inline), open(self.clip, "rb") as fh:
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/videos/", {"video": fh, "title": "قدیمی"})
        self.assertEqual(r.status_code, 201, r.content)

# -*- coding: utf-8 -*-
"""«زیرنویس: داخلِ تصویر / فایلِ جدا» on the real render path: the same project exported both ways, then the FRAMES are compared.
Burned-in = the text is in the picture; separate file = the picture is exactly the picture without any caption, and the .srt carries the words.
Real ffmpeg on a tiny clip; no node, no model."""
import atexit
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.video.ffmpeg import FFMPEG

from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-ae-caption-media-")
TEMP_DATA = tempfile.mkdtemp(prefix="nm-ae-caption-data-")
atexit.register(shutil.rmtree, TEMP_MEDIA, ignore_errors=True)
atexit.register(shutil.rmtree, TEMP_DATA, ignore_errors=True)
W, H = 320, 240


def frame(path: Path, t: float) -> np.ndarray:
    """One grey frame at `t` seconds, scaled to a fixed size so two exports are comparable whatever their preset."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", f"scale={W}:{H}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.float32)


@override_settings(MEDIA_ROOT=TEMP_MEDIA, NM_DATA_DIR=Path(TEMP_DATA))
class CaptionModeRenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if shutil.which(FFMPEG) or shutil.which("ffmpeg"):
            cls.clip = make_video(Path(TEMP_MEDIA) / "uploads/videos/cap_clip.mp4", seconds=4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        shutil.rmtree(TEMP_DATA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "clip"):
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("cap-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه زیرنویس")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up = UploadedVideo.objects.create(store=self.store, title="با صدا", video="uploads/videos/cap_clip.mp4", state="READY", duration=4.0, has_audio=True)

    def call(self, url, body):
        return self.client.post(self.base + url, json.dumps(body), content_type="application/json")

    def data(self, mode=None, captions=True):
        tracks = [{"kind": "video", "clips": [{"ref": f"video:{self.up.pk}", "at": 0, "start": 0, "end": 3}]}]
        if captions:
            tracks.append({"kind": "text", "caption": True, "clips": [{"text": "سلام به چغر", "at": 0.5, "duration": 2.0, "size": 14, "caption": True,
                                                                      "color": "#ffffff", "box": True, "box_color": "#000000", "box_opacity": 1.0, "y": 0.5}]})
        return {"format": {"width": W, "height": H, "fps": 25}, "tracks": tracks, "export": {"captions": mode} if mode else {}}

    def export(self, **kw):
        made = self.call("/editor/projects/", {"title": "زیرنویس", "data": self.data(**kw)})
        self.assertEqual(made.status_code, 201, made.content)
        pid = made.json()["project"]["id"]
        done = self.call(f"/editor/projects/{pid}/render/", {"quality": "final"})
        self.assertEqual(done.status_code, 202, done.content)
        job = Job.objects.get(pk=done.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        info = VideoProject.objects.get(pk=pid).render_info
        return info, Path(TEMP_MEDIA) / info["rel"]

    def test_burned_in_puts_the_text_in_the_picture_and_a_separate_file_leaves_the_picture_clean(self):
        burn_info, burn = self.export(mode="burn")
        soft_info, soft = self.export(mode="soft")
        _plain_info, plain = self.export(captions=False)
        t = 1.2                                              # inside the caption's 0.5-2.5 s
        b, s, p = frame(burn, t), frame(soft, t), frame(plain, t)
        self.assertGreater(float(np.abs(b - p).max()), 120, "burned-in: the caption box is a block of different pixels")
        self.assertLess(float(np.abs(s - p).mean()), 1.5, "separate file: the picture is the picture without any caption")
        self.assertGreater(float(np.abs(b - s).mean()), float(np.abs(s - p).mean()) * 3)
        self.assertEqual((burn_info["captions"], soft_info["captions"]), ("burn", "soft"))

    def test_both_modes_hand_over_the_srt_with_the_words(self):
        for mode in ("burn", "soft", None):
            info, _out = self.export(mode=mode)
            self.assertTrue(info.get("srt_url"), mode)
            srt = Path(TEMP_MEDIA) / info["srt_rel"]
            self.assertIn("سلام به چغر", srt.read_text(encoding="utf-8-sig"), mode)

    def test_no_choice_means_burned_in_as_before(self):
        info, _out = self.export(mode=None)
        self.assertEqual(info["captions"], "burn")

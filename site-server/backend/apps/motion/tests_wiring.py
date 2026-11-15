"""سیم‌کشیِ صدا میانِ سایت و گره: فایلِ «mix.m4a» به‌عنوانِ ورودیِ کار می‌رود، بی‌هیچ کلیدِ تازه در payload (گرهٔ قدیمی کار را رد نمی‌کند)."""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.stores.models import Store

from . import pipeline, runner, services
from .models import MotionRender

User = get_user_model()


class MixTravelsAsAnInputFile(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="nmmotion-wire-")
        self.data = tempfile.mkdtemp(prefix="nmmotion-wire-data-")
        self.ov = override_settings(MEDIA_ROOT=self.media, NM_DATA_DIR=self.data)
        self.ov.enable()
        self.owner = User.objects.create_user("wire-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def test_build_job_adds_the_mix_as_a_file_and_no_audio_key(self):
        spec = {"style": "flat-vector", "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "سلام"}]}
        r = services.create(self.store, self.owner, mode="template", title="t", spec=spec, target="node", qa=False)
        job, files = services.build_job(r)
        self.assertNotIn("audio", job)
        self.assertNotIn("mix", files)                       # no sound prepared: nothing extra
        d = runner.data_dir() / "audio" / str(r.pk)
        d.mkdir(parents=True)
        (d / "mix.m4a").write_bytes(b"A" * 4000)
        r.audio_dir = f"audio/{r.pk}"
        r.save(update_fields=["audio_dir"])
        job, files = services.build_job(r)
        self.assertNotIn("audio", job)
        self.assertEqual(files["mix"], (b"A" * 4000, ".m4a"))
        self.assertEqual(pipeline.mix_path(r), d / "mix.m4a")
        self.assertTrue(isinstance(r, MotionRender) and Path(d).is_dir())

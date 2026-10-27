"""صدای بازه و برش، از راهِ API ِ پنل، با ویدیوی واقعی (ffmpeg): همگامی، طول، crossfade، برش، شکلِ موج.

کلیپ: فلشِ سفید در فریم‌های ۳۰، ۹۰ (و …) و بوقِ بلندِ ۱ کیلوهرتزی در همان لحظه‌ها روی صدای گفتارمانند — پس
«صدا و تصویر هنوز با هم‌اند» یعنی فاصلهٔ هر بوق از فلشِ متناظرش.
"""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files import File
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.compute import services as compute
from apps.compute.models import ComputeNode
from apps.content.models import UploadedVideo
from apps.stores.models import Store
from services.video.regen import audio as audiomod, media, plan as planmod
from services.video.regen.selftest import FakeModel
from services.video.regen.selftest_audio import beeps, flashes, make_clip, make_tone, max_step, pcm, rms_db

from . import services
from .models import RegenSession, RegenVersion

TMP = Path(tempfile.mkdtemp(prefix="nmregen-atests-"))
CLIP, TONE = TMP / "clip.mp4", TMP / "tone.mp3"


def setUpModule():
    make_clip(CLIP, seconds=4.0)          # فلش و بوق در ۱ و ۳ ثانیه، ۱۲۰ فریم
    make_tone(TONE, 2000, 3.0)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AudioAndCutTests(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmregen-amedia-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmregen-adata-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("regen-audio", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ صدا")
        self.client.force_login(self.owner)
        with open(CLIP, "rb") as fh:
            self.upload = UploadedVideo(store=self.store, title="کلیپ")
            self.upload.video.save("clip.mp4", File(fh), save=True)
        self.base = f"/api/v1/stores/{self.store.pk}/regen"
        r = self.client.post(f"{self.base}/sessions/", {"source": f"upload:{self.upload.pk}"},
                             content_type="application/json")
        self.session = r.json()["session"]
        self.assertEqual(self.session["state"], "READY")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def _version(self, body):
        r = self.client.post(f"{self.base}/sessions/{self.session['id']}/versions/", body,
                             content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        v = self.client.get(f"{self.base}/versions/{r.json()['version']['id']}/").json()["version"]
        self.assertEqual(v["state"], "READY", v["error"])
        return v, RegenVersion.objects.get(pk=v["id"])

    def _paths(self, row):
        return services.abs_path(row.session.original), services.abs_path(row.files["result"])

    def test_mute_keeps_picture_sync_and_length(self):
        v, row = self._version({"mode": "audio", "start": 75, "end": 104,                # ۲٫۵ … ۳٫۵ ثانیه
                                "audio": {"op": "mute", "fade_ms": 80}})
        self.assertEqual(v["mode"], "audio")
        self.assertTrue(all(c["ok"] for c in v["assemble"]["checks"].values()), v["assemble"]["checks"])
        self.assertTrue(v["assemble"]["checks"]["picture_untouched"]["ok"])
        src, out = self._paths(row)
        self.assertEqual(media.probe(out)["duration"], media.probe(src)["duration"])
        self.assertEqual(beeps(pcm(out)), [1.0001])                      # بوقِ ۳ ثانیه داخلِ بازه بود
        x = pcm(out)
        self.assertLess(rms_db(x[int(2.62 * 48000):int(3.38 * 48000)]), -90)
        # crossfade: در لبه‌ها پرشِ نمونه‌به‌نمونه بزرگ‌تر از صدای عادی نیست (تق نمی‌زند)
        x0 = pcm(src)
        self.assertLess(max_step(x, 2.5), 2 * max_step(x0, 2.5) + 0.01)
        self.assertLess(max_step(x, 3.5), 2 * max_step(x0, 3.5) + 0.01)
        self.assertTrue(v["urls"]["before"] and v["urls"]["after"] and v["urls"]["piece"])

    def test_volume_lowers_by_the_asked_amount(self):
        _v, row = self._version({"mode": "audio", "start": 30, "end": 74, "audio": {"op": "volume", "gain_db": -12}})
        src, out = self._paths(row)
        a, b = pcm(src), pcm(out)
        inner = slice(int(1.6 * 48000), int(2.3 * 48000))
        self.assertAlmostEqual(rms_db(b[inner]) - rms_db(a[inner]), -12.0, delta=0.6)

    def test_replace_with_uploaded_file_and_mix(self):
        with open(TONE, "rb") as fh:
            r = self.client.post(f"{self.base}/sessions/{self.session['id']}/audio/",
                                 {"file": SimpleUploadedFile("tone.mp3", fh.read(), "audio/mpeg")})
        self.assertEqual(r.status_code, 201, r.content)
        up = r.json()
        self.assertTrue(up["source"].startswith("upload:"))
        self.assertAlmostEqual(up["duration"], 3.0, delta=0.1)
        for mix in ("replace", "mix"):
            v, row = self._version({"mode": "audio", "start": 45, "end": 89, "audio": {
                "op": "replace", "source": up["source"], "offset": 0.5, "clip_gain_db": -6, "mix": mix}})
            self.assertEqual(v["audio_report"]["mix"], mix)
            _src, out = self._paths(row)
            x = pcm(out)
            self.assertEqual(beeps(x)[0], 1.0001)                       # بیرونِ بازه سرِ جایش
            self.assertEqual(media.count_frames(out), 120)

    def test_cut_removes_picture_and_sound_together(self):
        v, row = self._version({"mode": "cut", "start": 45, "end": 74})                  # ۱٫۵ … ۲٫۵ ثانیه
        self.assertEqual(v["removed_frames"], 30)
        src, out = self._paths(row)
        oi = media.probe(out)
        self.assertEqual(oi["n_frames"], 90)
        self.assertAlmostEqual(oi["duration"], 3.0, delta=1 / 30)
        # فلش و بوقِ ۳ ثانیه حالا هر دو در ۲ ثانیه‌اند (همگام)
        self.assertEqual(flashes(out, oi), [30, 60])
        b = beeps(pcm(out))
        self.assertEqual(len(b), 2)
        self.assertLess(abs(b[1] - 60 / 30), 0.005)
        self.assertLess(max_step(pcm(out), 1.5), 0.05)                 # جای چسب تق نمی‌زند
        # قبول ⇐ پایهٔ تازه: ۹۰ فریم، نوارِ کوچک‌نمایی هم از نو
        self.client.post(f"{self.base}/versions/{v['id']}/accept/")
        s = self.client.get(f"{self.base}/sessions/{self.session['id']}/").json()["session"]
        self.assertEqual(s["info"]["n_frames"], 90)
        self.assertIn("filmstrip_v", s["filmstrip"]["url"])

    def test_waveform_shows_where_the_sound_is(self):
        r = self.client.get(f"{self.base}/sessions/{self.session['id']}/waveform/", {"n": 40})
        w = r.json()
        self.assertTrue(w["has_audio"])
        self.assertEqual(len(w["peaks"]), 40)
        self.assertEqual(max(w["peaks"]), 1.0)                          # بوقِ ۱ ثانیه
        z = self.client.get(f"{self.base}/sessions/{self.session['id']}/waveform/",
                            {"from": 0.9, "to": 1.2, "n": 30}).json()
        self.assertEqual(len(z["peaks"]), 30)

    def test_bad_requests(self):
        url = f"{self.base}/sessions/{self.session['id']}/versions/"
        for body in ({"mode": "audio", "start": 10, "end": 20, "audio": {"op": "keep"}},
                     {"mode": "audio", "start": 10, "end": 20, "audio": {"op": "replace"}},
                     {"mode": "audio", "start": 10, "end": 20, "audio": {"op": "replace", "source": "upload:../x"}},
                     {"mode": "cut", "start": 0, "end": 119},
                     {"mode": "audio", "start": 10, "end": 200, "audio": {"op": "mute"}},
                     {"mode": "weird", "start": 10, "end": 20}):
            r = self.client.post(url, body, content_type="application/json")
            self.assertEqual(r.status_code, 400, body)
        r = self.client.post(f"{self.base}/sessions/{self.session['id']}/audio/",
                             {"file": SimpleUploadedFile("x.txt", b"hello", "text/plain")})
        self.assertEqual(r.status_code, 400)

    def test_picture_and_audio_together(self):
        """تکهٔ تازهٔ تصویر (گرهٔ شبیه‌سازی‌شده) + بی‌صدا کردنِ همان بازه در یک نسخه."""
        node = ComputeNode.objects.create(name="gpu-a", last_seen=timezone.now(),
                                          capabilities={"comfyui": True, "comfy_nodes": ["WanFirstLastFrameToVideo"]})
        r = self.client.post(f"{self.base}/sessions/{self.session['id']}/versions/",
                             {"start": 75, "end": 104, "prompt": "x", "audio": {"op": "mute"}},
                             content_type="application/json")
        vid = r.json()["version"]["id"]
        row = RegenVersion.objects.get(pk=vid)
        self.assertEqual((row.mode, row.audio["op"]), ("picture", "mute"))
        job = compute.claim(node)
        path, info = services.base_of(row.session, row)
        p = planmod.make_plan(info, 75, 104)
        tmp = Path(tempfile.mkdtemp())
        for chunk, paths in FakeModel(path, info, p).render(tmp).items():
            for k, src in enumerate(paths):
                with open(src, "rb") as fh:
                    compute.save_output(job, f"c{chunk}_{k + 1:05d}_.png", fh)
        compute.finish(job, node, True)
        shutil.rmtree(tmp, ignore_errors=True)
        v = self.client.get(f"{self.base}/versions/{vid}/").json()["version"]
        self.assertEqual(v["state"], "READY", v["error"])
        self.assertEqual(v["audio_report"]["op"], "mute")
        out = services.abs_path(RegenVersion.objects.get(pk=vid).files["result"])
        self.assertEqual(beeps(pcm(out)), [1.0001])
        self.assertEqual(media.count_frames(out), 120)
        self.assertIn(v["seams"]["verdict"], ("invisible", "slight"))

    def test_replace_from_the_shops_audio_library(self):
        """«کتابخانهٔ صداها» ِ بخشِ صدا (گفتار/کلون/موسیقی/افکت): همان فایلِ دارایی، فقط اگر آماده و مالِ همین فروشگاه."""
        from apps.ai.audio_library_models import AudioAsset
        from services.audio import studio

        rel = f"store_{self.store.pk}/music_test.mp3"
        (studio.root() / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TONE, studio.root() / rel)
        asset = AudioAsset.objects.create(store=self.store, kind="MUSIC", status="READY", title="آهنگِ آزمون",
                                          file_name=rel, duration=3.0)
        v, row = self._version({"mode": "audio", "start": 45, "end": 89,
                                "audio": {"op": "replace", "source": f"asset:{asset.pk}", "mix": "mix"}})
        self.assertEqual(v["audio"]["source"], f"asset:{asset.pk}")
        other = Store.objects.create(owner=User.objects.create_user("other-shop"), name="دیگر")
        foreign = AudioAsset.objects.create(store=other, kind="MUSIC", status="READY", file_name=rel, duration=3.0)
        r = self.client.post(f"{self.base}/sessions/{self.session['id']}/versions/", {
            "mode": "audio", "start": 45, "end": 89, "audio": {"op": "replace", "source": f"asset:{foreign.pk}"}},
            content_type="application/json")
        self.assertEqual(r.status_code, 400)

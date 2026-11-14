"""Database-backed tests of the fixes after the owner's own video (1405/08/23): the starter music library, the look preview's moment, and the queue row of a
cancelled parked job.  Real ffmpeg on tiny clips; no node, no model."""
import atexit
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.ai.models import AudioAsset
from apps.compute.models import ComputeJob
from apps.jobs import cancellation
from apps.jobs.models import Job
from apps.stores.models import Store
from services.audio import starter_music
from services.editing.director.ctx import store_ctx
from services.editing import music_match
from services.tests_autoedit_audio import SR, mux, synth_speech, write_wav
from services.video.ffmpeg import FFMPEG

from .models import UploadedVideo

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-autoedit-fixes-media-")
TEMP_DATA = tempfile.mkdtemp(prefix="nm-autoedit-fixes-data-")
atexit.register(shutil.rmtree, TEMP_MEDIA, ignore_errors=True)
atexit.register(shutil.rmtree, TEMP_DATA, ignore_errors=True)
HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


@override_settings(MEDIA_ROOT=TEMP_MEDIA, NM_DATA_DIR=Path(TEMP_DATA), AUTOEDIT_STARTER_MUSIC=True)
class StarterMusicTests(TestCase):
    """The owner's shop had no music at all, so every automatic edit said «موسیقیِ هم‌خوان پیدا نشد» and the video had none."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(Path(TEMP_DATA) / "audio_library", ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        self.owner = User.objects.create_user("music-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ بی‌موسیقی")

    def music(self, store=None):
        return AudioAsset.objects.filter(store=store or self.store, kind=AudioAsset.Kind.MUSIC)

    def test_the_six_tracks_are_composed_here_and_are_music_not_noise(self):
        keys = [t["key"] for t in starter_music.TRACKS]
        self.assertEqual(keys, ["calm", "warm", "happy", "energetic", "inspiring", "dramatic"])
        for spec in starter_music.TRACKS:
            x = starter_music.synthesize(spec)
            self.assertEqual(x.ndim, 2)
            self.assertEqual(x.shape[1], 2, "stereo")
            seconds = len(x) / starter_music.SR
            self.assertGreaterEqual(seconds, 45.0, spec["key"])
            self.assertLessEqual(float(abs(x).max()), 0.9, f"{spec['key']} stays under -1 dBFS")
            rms_db = 20 * __import__("math").log10(float((x.astype("float64") ** 2).mean() ** 0.5) + 1e-9)
            self.assertTrue(-24.0 < rms_db < -13.0, f"{spec['key']} loudness {rms_db:.1f} dBFS")
            self.assertTrue((x[: int(0.01 * starter_music.SR)] ** 2).mean() < 1e-3, "fades in, no click at the start")
        a, b = starter_music.synthesize(starter_music.TRACKS[0]), starter_music.synthesize(starter_music.TRACKS[0])
        self.assertTrue((a == b).all(), "deterministic: the same track every time")

    def test_every_track_is_a_licence_free_original_that_says_so(self):
        for spec in starter_music.TRACKS:
            self.assertIn(spec["bpm"], range(60, 140))
            self.assertTrue(spec["title"] and spec["text"])
        ensured = starter_music.ensure_for_store(self.store, upgrade_on_node=False)
        self.assertEqual(ensured["created"], 6)
        for row in self.music():
            self.assertEqual(row.engine, "starter")
            self.assertTrue(row.commercial)
            self.assertIn("CC0", row.license)
            self.assertEqual(row.status, AudioAsset.Status.READY)
            self.assertTrue(row.saved, "a library track, not a draft that is swept after a day")

    def test_a_library_without_music_gets_the_starter_pack_once(self):
        first = starter_music.ensure_for_store(self.store, upgrade_on_node=False)
        self.assertEqual((first["created"], self.music().count()), (6, 6))
        for row in self.music():
            path = Path(TEMP_DATA) / "audio_library" / row.file_name
            self.assertTrue(path.is_file() and path.stat().st_size > 100_000, row.title)
            self.assertGreater(row.duration, 45.0)
        again = starter_music.ensure_for_store(self.store, upgrade_on_node=False)
        self.assertEqual((again["created"], self.music().count()), (0, 6), "never twice")

    def test_a_shop_that_already_has_music_keeps_its_own(self):
        mine = AudioAsset.objects.create(store=self.store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY, title="آهنگِ خودم", file_name="x.wav")
        self.assertEqual(starter_music.ensure_for_store(self.store, upgrade_on_node=False)["created"], 0)
        self.assertEqual(list(self.music().values_list("pk", flat=True)), [mine.pk])

    def test_it_can_be_switched_off(self):
        with override_settings(AUTOEDIT_STARTER_MUSIC=False):
            self.assertEqual(starter_music.ensure_for_store(self.store)["created"], 0)
        self.assertEqual(self.music().count(), 0)
        self.assertEqual(starter_music.ensure_for_store(None)["created"], 0)

    def test_the_directors_context_finds_a_track_by_itself(self):
        ctx = store_ctx(self.store, asr=False)
        ref = ctx.find_music("")
        self.assertTrue(ref and ref.startswith("audio:"), ref)
        self.assertEqual(self.music().count(), 6)
        self.assertTrue(ctx.describe(ref)["duration"] > 45, "the track is a real, probed media item")

    def test_the_ranking_picks_calm_for_a_talking_video_and_energetic_for_a_sale(self):
        ctx = store_ctx(self.store, asr=False)
        talk = music_match.target_for(pace="normal", speech_share=0.8, recipe="polish")
        ranked = ctx.rank_music(talk, 60.0)
        self.assertTrue(ranked, "a talking video must find music")
        self.assertIn(ranked[0]["title"].split(" — ")[0], ("آرامش", "گرم و صمیمی"), ranked[0]["title"])
        sale = music_match.target_for(pace="fast", speech_share=0.0, recipe="sale")
        top = ctx.rank_music(sale, 60.0)[0]
        self.assertIn(top["title"].split(" — ")[0], ("پرانرژی و تند", "شاد و پرانرژی"), top["title"])

    def test_a_node_with_the_music_engine_is_asked_for_real_tracks_once(self):
        created = []

        def fake_create(store, user, **kw):
            row = AudioAsset.objects.create(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.PENDING, engine="acestep", params={"style": kw["style"]})
            created.append(kw["style"])
            return row

        with patch("services.audio.studio.create_music", side_effect=fake_create):
            self.assertEqual(starter_music.queue_node_music(self.store), 3)
            self.assertEqual(created, ["calm", "upbeat", "cinematic"])
            self.assertEqual(starter_music.queue_node_music(self.store), 0, "once per shop per two weeks, not on every edit")
        self.assertTrue(all(r.saved for r in self.music().filter(engine="acestep")))

    def test_a_library_of_starters_asks_the_node_but_a_shops_own_music_is_never_upsold(self):
        calls = []

        def fake_create(store, user, **kw):
            calls.append(kw["style"])
            return AudioAsset.objects.create(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.PENDING, engine="acestep", params={"style": kw["style"]})

        with patch("services.audio.studio.create_music", side_effect=fake_create):
            first = starter_music.ensure_for_store(self.store)
            self.assertEqual((first["created"], first["queued_node"]), (6, 3))
            again = starter_music.ensure_for_store(self.store)
            self.assertEqual((again["created"], again["queued_node"]), (0, 0), "asked once, not on every edit")
            other = Store.objects.create(owner=self.owner, name="فروشگاهِ موسیقی‌دار")
            AudioAsset.objects.create(store=other, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY, title="آهنگِ خودش", file_name="y.wav")
            self.assertEqual(starter_music.ensure_for_store(other)["queued_node"], 0)
        self.assertEqual(calls, ["calm", "upbeat", "cinematic"])

    def test_a_refused_ask_is_remembered_so_the_next_edit_does_not_pay_for_it_again(self):
        from services.audio import studio

        starter_music.ensure_for_store(self.store, upgrade_on_node=False)
        with patch("services.audio.studio.create_music", side_effect=studio.StudioError("no node", 503)) as fake:
            self.assertEqual(starter_music.ensure_for_store(self.store)["queued_node"], 0)
            self.assertEqual(starter_music.ensure_for_store(self.store)["queued_node"], 0)
        self.assertEqual(fake.call_count, 1, "the second edit must not ask again within the retry window")

    def test_the_command_seeds_one_shop_and_says_so(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("seed_starter_music", "--store", str(self.store.pk), "--dry-run", stdout=out)
        self.assertIn("would get the six starter tracks", out.getvalue())
        self.assertEqual(self.music().count(), 0)
        out = StringIO()
        call_command("seed_starter_music", "--store", str(self.store.pk), "--no-node", stdout=out)
        self.assertIn("6 starter track(s) added", out.getvalue())
        self.assertEqual(self.music().count(), 6)
        out = StringIO()
        call_command("seed_starter_music", "--store", str(self.store.pk), "--no-node", stdout=out)
        self.assertIn("0 starter track(s) added (6 were there)", out.getvalue())
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_starter_music")

    def test_no_node_or_no_allowance_is_not_an_error(self):
        from services.audio import studio

        with patch("services.audio.studio.create_music", side_effect=studio.StudioError("هیچ سرورِ پردازشی روشن نیست", 503)) as fake:
            self.assertEqual(starter_music.queue_node_music(self.store), 0)
        self.assertEqual(fake.call_count, 1, "the same answer for the rest: no repeated attempts")


@override_settings(MEDIA_ROOT=TEMP_MEDIA, NM_DATA_DIR=Path(TEMP_DATA))
class LookPreviewMomentTests(TestCase):
    """The preview opened on the MIDDLE frame - the recorded app screen of the owner's video - and said «نیازی به اصلاح نبود» about a video whose face
    part does need it.  It opens on a frame with a person in it now, and the moment can be chosen."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE:
            return
        root = Path(TEMP_MEDIA) / "uploads/videos"
        root.mkdir(parents=True, exist_ok=True)
        cls.clip = mux(root / "lp_talk.mp4", write_wav(root / "lp_talk.wav", synth_speech(8, seed=3)), 8)

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        self.owner = User.objects.create_user("look-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه نور")
        self.client.force_login(self.owner)
        self.up = UploadedVideo.objects.create(store=self.store, title="x.mp4", video="uploads/videos/lp_talk.mp4", state="READY", duration=8, has_audio=True)

    def get(self, **params):
        q = "&".join(f"{k}={v}" for k, v in {"ref": f"video:{self.up.pk}", **params}.items())
        return self.client.get(f"/api/v1/stores/{self.store.pk}/autoedit/look-preview/?{q}")

    def test_the_answer_says_how_long_the_video_is_and_whether_the_moment_was_chosen(self):
        r = self.get()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertAlmostEqual(body["duration"], 8.0, delta=0.6)
        self.assertTrue(body["auto_t"])
        r = self.get(t=2.5)
        self.assertEqual((r.json()["t"], r.json()["auto_t"]), (2.5, False))

    def test_without_a_moment_it_opens_on_a_frame_with_a_person(self):
        """The first probe with a face wins (the middle first); no face anywhere = the middle."""
        from apps.content import views_autoedit

        seen = []

        def fake_in_image(path):
            seen.append(Path(path).name)
            return [object()] if len(seen) == 3 else []            # the third probe (30 %) has a face

        with patch("services.video.faces.in_image", side_effect=fake_in_image), patch("services.video.faces.available", return_value=(True, "")):
            t = views_autoedit.default_look_time(Path(TEMP_MEDIA) / "uploads/videos/lp_talk.mp4", 8.0)
        self.assertEqual(len(seen), 3)
        self.assertAlmostEqual(t, 2.5, delta=0.01, msg="30 % of 8 s, on a half second")
        with patch("services.video.faces.in_image", return_value=[]), patch("services.video.faces.available", return_value=(True, "")):
            self.assertEqual(views_autoedit.default_look_time(Path(TEMP_MEDIA) / "uploads/videos/lp_talk.mp4", 8.0), 4.0)
        with patch("services.video.faces.available", return_value=(False, "no opencv")):
            self.assertEqual(views_autoedit.default_look_time(Path(TEMP_MEDIA) / "uploads/videos/lp_talk.mp4", 8.0), 4.0)


class CancelledParkedJobTests(TestCase):
    """Cancelling a parked job left its «در صف — منتظرِ …» row QUEUED: phantom waiting rows in the owner's queue until the sweep found them."""

    def setUp(self):
        self.owner = User.objects.create_user("park-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه صف")

    def parked(self):
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.QUEUED, context={"what": "director"})
        ph = ComputeJob.objects.create(kind="wait.node", payload={"capability": "voice", "ref": {"model": "jobs.Job", "id": job.pk}}, origin="park", store=self.store,
                                       state=ComputeJob.State.QUEUED, message="در صف — منتظرِ روشن شدنِ سرورِ پردازش", timeout_s=0)
        job.context = {**job.context, "node_wait": {"park": str(ph.uid), "cap": "voice"}}
        job.save(update_fields=["context"])
        return job, ph

    def test_cancelling_the_job_takes_its_queue_row_away(self):
        job, ph = self.parked()
        other_job, other_ph = self.parked()
        out = cancellation.cancel(job)
        self.assertTrue(out["cancelled"])
        ph.refresh_from_db()
        other_ph.refresh_from_db()
        self.assertEqual(ph.state, ComputeJob.State.CANCELLED)
        self.assertIsNotNone(ph.finished_at)
        self.assertEqual(other_ph.state, ComputeJob.State.QUEUED, "another job's row is not touched")
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.CANCELLED)

    def test_the_row_is_found_by_its_reference_even_without_the_uid_in_the_context(self):
        job, ph = self.parked()
        job.context = {"what": "director"}
        job.save(update_fields=["context"])
        cancellation.cancel(job)
        ph.refresh_from_db()
        self.assertEqual(ph.state, ComputeJob.State.CANCELLED)

    def test_cancelling_the_queue_row_still_cancels_the_job_without_looping(self):
        from apps.compute import services as compute

        job, ph = self.parked()
        compute.cancel(ph, "لغو شد")
        job.refresh_from_db()
        ph.refresh_from_db()
        self.assertEqual(job.state, Job.State.CANCELLED)
        self.assertEqual(ph.state, ComputeJob.State.CANCELLED)

    def test_a_plain_job_cancel_is_unchanged(self):
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.RUNNING, context={})
        self.assertTrue(cancellation.cancel(job)["cancelled"])

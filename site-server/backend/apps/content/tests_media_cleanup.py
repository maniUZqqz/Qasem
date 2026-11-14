"""The video editor's disk hygiene (audit 2026-11-14): deleting a video removes what it owned, an automatic edit keeps only edited.mp4,
the finished video is moved (never read into memory), a failed segment cut leaves no temp folder, and the daily sweeper is conservative."""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import agent
from services.editing import edl as edl_module

from . import media_cleanup, tasks_editing
from .models import UploadedVideo

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-cleanup-")
DAY = 86400.0


def put(rel: str, size: int = 10, age_days: float = 0.0) -> Path:
    path = Path(TEMP_MEDIA) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days:
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))
    return path


def age_tree(path: Path, age_days: float):
    stamp = time.time() - age_days * DAY
    for base, dirs, files in os.walk(path, topdown=False):
        for name in files + dirs:
            os.utime(os.path.join(base, name), (stamp, stamp))
    os.utime(path, (stamp, stamp))


def work_tree(pk: int) -> Path:
    """What an automatic edit leaves in upload_<pk> (the real layout of /generated/editing/upload_22 on the live server)."""
    base = f"generated/editing/upload_{pk}"
    for rel in ("edited.mp4", "edit_round1.mp4", "edit_round2.mp4", "denoised.wav", "qc_analysis.wav", "proxy.mp4", "edited_proxy.mp4",
                "after1/qc_analysis.wav", "after1/faces/f.png", "after2/look/q.png", "denoise_work/denoise_in.wav", "dfn/.keep", "noise/qc_analysis.wav",
                "faces/f1.png", "look/q1.png", "shots/s1.png", "stats/s.json", "cuts/edited_reel.mp4", "cuts/edited_feed.mp4"):
        put(f"{base}/{rel}", 100)
    return Path(TEMP_MEDIA) / base


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class CleanupBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)            # every test starts with an empty media folder (the DB rolls back, files do not)
        Path(TEMP_MEDIA).mkdir(parents=True, exist_ok=True)
        self.owner = User.objects.create_user("cleanup-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه پاک‌سازی")

    def make(self, title="v", video=None, edited="", subtitles="", state=UploadedVideo.State.READY) -> UploadedVideo:
        up = UploadedVideo.objects.create(store=self.store, title=title, state=state, video=video or SimpleUploadedFile(f"{title}.mp4", b"vid" * 10))
        changed = []
        if edited:
            up.edited.name = edited
            changed.append("edited")
        if subtitles:
            up.subtitles.name = subtitles
            changed.append("subtitles")
        if changed:
            up.save(update_fields=changed)
        return up


class DeleteRemovesWhatTheVideoOwnedTests(CleanupBase):
    def delete(self, up):
        self.client.force_login(self.owner)
        return self.client.delete(f"/api/v1/stores/{self.store.pk}/videos/{up.pk}/")

    def test_upload_edited_copy_subtitles_and_work_folder_are_removed(self):
        up = self.make("alpha")
        work = work_tree(up.pk)
        put("generated/subtitles/alpha.srt")
        up.edited.name = f"generated/editing/upload_{up.pk}/edited.mp4"
        up.subtitles.name = "generated/subtitles/alpha.srt"
        up.save()
        video_path = Path(up.video.path)
        self.assertTrue(video_path.is_file())
        other = self.make("beta")
        other_work = work_tree(other.pk)
        other_file = Path(other.video.path)

        self.assertEqual(self.delete(up).status_code, 204)

        self.assertFalse(UploadedVideo.objects.filter(pk=up.pk).exists())
        self.assertFalse(video_path.exists(), "the uploaded file")
        self.assertFalse(work.exists(), "the whole upload_<pk> work folder (edited copy, cuts, proxies, intermediates)")
        self.assertFalse((Path(TEMP_MEDIA) / "generated/subtitles/alpha.srt").exists())
        # the other video is untouched, row exists -> kept
        self.assertTrue(other_file.is_file())
        self.assertTrue(other_work.is_dir() and (other_work / "edited.mp4").is_file())

    def test_a_file_that_belongs_to_something_else_is_kept(self):
        render = put("generated/editing/project_5/replace_1.mp4", 50)          # «رندر و جایگزینی» makes an UploadedVideo pointing at a render
        motion = put("generated/motion/34/clip.mp4", 50)
        a = self.make("from-render", video=None)
        a.video.name = "generated/editing/project_5/replace_1.mp4"
        a.save()
        b = self.make("from-motion")
        b.video.name = "generated/motion/34/clip.mp4"
        b.save()
        self.assertEqual(self.delete(a).status_code, 204)
        self.assertEqual(self.delete(b).status_code, 204)
        self.assertTrue(render.is_file() and motion.is_file(), "files of other features survive the delete of the row that pointed at them")

    def test_a_file_another_row_still_uses_is_kept(self):
        a = self.make("dup")
        b = self.make("dup2")
        b.video.name = a.video.name
        b.save()
        path = Path(a.video.path)
        self.assertEqual(self.delete(a).status_code, 204)
        self.assertTrue(path.is_file(), "the other row still points at the same file")
        self.assertEqual(self.delete(b).status_code, 204)
        self.assertFalse(path.exists())

    def test_a_failing_removal_never_fails_the_delete(self):
        up = self.make("gamma")
        with patch.object(media_cleanup.shutil, "rmtree", side_effect=OSError("busy")), patch.object(Path, "unlink", side_effect=OSError("busy")):
            self.assertEqual(self.delete(up).status_code, 204)
        self.assertFalse(UploadedVideo.objects.filter(pk=up.pk).exists())

    def test_another_stores_video_cannot_be_deleted(self):
        up = self.make("mine")
        stranger = User.objects.create_user("stranger", password="x")
        self.client.force_login(stranger)
        self.assertIn(self.client.delete(f"/api/v1/stores/{self.store.pk}/videos/{up.pk}/").status_code, (403, 404))
        self.assertTrue(Path(up.video.path).is_file())


class TrimAndPromoteTests(CleanupBase):
    def test_promote_renames_and_never_reads_the_video_into_memory(self):
        src = put("generated/editing/upload_1/edit_round2.mp4", 5000)
        dst = Path(TEMP_MEDIA) / "generated/editing/upload_1/edited.mp4"
        dst.write_bytes(b"old")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("read_bytes")), patch.object(Path, "write_bytes", side_effect=AssertionError("write_bytes")):
            media_cleanup.promote(src, dst)
        self.assertFalse(src.exists())
        self.assertEqual(dst.stat().st_size, 5000)
        media_cleanup.promote(dst, dst)                                       # same path: nothing to do
        self.assertEqual(dst.stat().st_size, 5000)

    def test_promote_copies_in_chunks_when_a_rename_is_impossible(self):
        src = put("generated/editing/upload_1/edit_round1.mp4", 777)
        dst = Path(TEMP_MEDIA) / "generated/editing/upload_1/edited.mp4"
        with patch.object(media_cleanup.os, "replace", side_effect=OSError("cross-device")):
            media_cleanup.promote(src, dst)
        self.assertEqual(dst.stat().st_size, 777)
        self.assertFalse(src.exists())

    def test_after_a_new_edit_only_the_result_proxy_and_the_source_analysis_stay(self):
        work = work_tree(7)
        before = media_cleanup._tree_size(work)
        report = media_cleanup.trim_after_edit(work, new_edit=True)
        left = sorted(str(p.relative_to(work)).replace("\\", "/") for p in work.rglob("*") if p.is_file())
        self.assertEqual(left, ["edited.mp4", "faces/f1.png", "look/q1.png", "proxy.mp4", "shots/s1.png", "stats/s.json"])
        self.assertGreater(report["bytes"], 0)
        self.assertLess(media_cleanup._tree_size(work), before / 2)

    def test_without_a_new_edit_the_previous_version_keeps_its_cuts_and_proxy(self):
        work = work_tree(8)
        media_cleanup.trim_after_edit(work, new_edit=False)
        self.assertTrue((work / "cuts/edited_reel.mp4").is_file() and (work / "edited_proxy.mp4").is_file() and (work / "edited.mp4").is_file())
        self.assertFalse((work / "edit_round1.mp4").exists() or (work / "after1").exists() or (work / "denoised.wav").exists())

    def test_trimming_a_missing_folder_is_not_an_error(self):
        self.assertEqual(media_cleanup.trim_after_edit(Path(TEMP_MEDIA) / "nope", new_edit=True)["removed"], [])

    def test_nothing_outside_the_editing_folder_is_ever_removed(self):
        outside = put("uploads/videos/keep.wav", 10)
        report = media_cleanup._new_report()
        self.assertFalse(media_cleanup._remove(outside, media_cleanup.editing_root(), report, "test"))
        self.assertTrue(outside.is_file())


class EditTaskTests(CleanupBase):
    def fake_run(self, source, out_path, work_dir, **kw):
        work = Path(work_dir)
        for rel, n in (("edit_round1.mp4", 100), ("edit_round2.mp4", 3000), ("denoised.wav", 50), ("after1/qc_analysis.wav", 50), ("after2/x.png", 5), ("denoise_work/a.wav", 9)):
            put(f"generated/editing/{work.name}/{rel}", n)
        plan = agent.Plan(edl=edl_module.EDL(source=Path(source), duration=1.0))
        return agent.Outcome(plan=plan, output=work / "edit_round2.mp4", before={"duration": 1.0}, after={"duration": 1.0}, rounds=2, note="ok")

    def test_the_result_is_moved_to_edited_mp4_and_the_intermediates_are_gone(self):
        up = self.make("task")
        old_cuts = put(f"generated/editing/upload_{up.pk}/cuts/edited_reel.mp4", 20)
        old_proxy = put(f"generated/editing/upload_{up.pk}/edited_proxy.mp4", 20)
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"upload_id": up.pk, "mode": "AUTO"})
        with patch.object(tasks_editing.agent, "run", side_effect=self.fake_run), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("the video must not be read into memory")):
            result = tasks_editing.edit_video_task.run(job.id, up.pk, "AUTO")
        self.assertNotIn("error", result, result)
        up.refresh_from_db()
        work = Path(TEMP_MEDIA) / f"generated/editing/upload_{up.pk}"
        self.assertEqual(up.state, UploadedVideo.State.EDITED)
        self.assertEqual(up.edited.name, f"generated/editing/upload_{up.pk}/edited.mp4")
        self.assertEqual((work / "edited.mp4").stat().st_size, 3000, "the last round became the edited video")
        names = sorted(p.name for p in work.iterdir())
        self.assertEqual(names, ["edited.mp4"], names)
        self.assertFalse(old_cuts.exists() or old_proxy.exists(), "derived files of the previous version")

    def test_a_failed_edit_still_clears_its_intermediates_and_keeps_the_old_result(self):
        up = self.make("task2")
        old = put(f"generated/editing/upload_{up.pk}/edited.mp4", 11)
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"upload_id": up.pk, "mode": "AUTO"})

        def boom(source, out_path, work_dir, **kw):
            put(f"generated/editing/upload_{up.pk}/edit_round1.mp4", 100)
            raise RuntimeError("ffmpeg died")

        with patch.object(tasks_editing.agent, "run", side_effect=boom):
            result = tasks_editing.edit_video_task.run(job.id, up.pk, "AUTO")
        self.assertIn("error", result)
        self.assertTrue(old.is_file() and old.stat().st_size == 11)
        self.assertFalse((old.parent / "edit_round1.mp4").exists())

    def test_a_second_running_edit_keeps_the_intermediates_for_itself(self):
        up = self.make("task3")
        work = work_tree(up.pk)
        busy = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.PROCESSING, context={"upload_id": up.pk, "mode": "AUTO"})
        me = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.COMPLETED, context={"upload_id": up.pk, "mode": "AUTO"})
        self.assertTrue(media_cleanup.edit_running(up.pk, exclude_job=me.pk))
        self.assertFalse(media_cleanup.edit_running(up.pk, exclude_job=busy.pk))
        self.assertFalse(media_cleanup.edit_running(up.pk + 1))
        self.assertTrue((work / "edit_round1.mp4").is_file())
        Job.objects.filter(pk=busy.pk).update(state=Job.State.COMPLETED)
        self.assertFalse(media_cleanup.edit_running(up.pk, exclude_job=me.pk))


class SegmentFolderTests(CleanupBase):
    def test_the_temp_folder_does_not_survive_a_failed_ffmpeg(self):
        made = []
        real = tempfile.mkdtemp

        def spy(*a, **k):
            path = real(*a, **k)
            made.append(path)
            return path

        with patch("services.editing.compose._source_size", return_value=(1280, 720)), patch("tempfile.mkdtemp", side_effect=spy), \
                patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
            with self.assertRaises(subprocess.CalledProcessError):
                tasks_editing._segment_file("/x/y.mp4", 0.0, 2.0, 640)
        self.assertEqual(len(made), 1)
        self.assertFalse(Path(made[0]).exists(), "the nm-seg-* folder is removed when the cut fails")

    def test_the_folder_stays_for_the_caller_when_the_cut_works(self):
        def fake(cmd, **kw):
            Path(cmd[-1]).write_bytes(b"clip")

        with patch("services.editing.compose._source_size", return_value=(1280, 720)), patch("subprocess.run", side_effect=fake):
            out, w, h = tasks_editing._segment_file("/x/y.mp4", 0.0, 2.0, 640)
        try:
            self.assertTrue(out.is_file())
            self.assertEqual((w, h), (640, 360))
        finally:
            shutil.rmtree(out.parent, ignore_errors=True)


class SweeperTests(CleanupBase):
    def test_orphan_work_folders_need_no_row_and_three_days(self):
        live = self.make("live")
        keep_live = work_tree(live.pk)
        age_tree(keep_live, 30)
        gone_old = work_tree(9001)
        age_tree(gone_old, 5)
        gone_new = work_tree(9002)
        age_tree(gone_new, 1)
        odd = put("generated/editing/upload_x/keep.txt", 5, age_days=60)         # not an upload_<digits> folder: never touched
        cache = put("generated/editing/cache/a.wave.json", 5, age_days=60)
        report = media_cleanup.sweep_orphans()
        self.assertTrue(keep_live.is_dir(), "its row exists")
        self.assertFalse(gone_old.exists(), "no row and older than 3 days")
        self.assertTrue(gone_new.is_dir(), "no row but only a day old")
        self.assertTrue(odd.is_file() and cache.is_file())
        self.assertEqual([r for r in report["removed"] if "9001" in r], ["generated/editing/upload_9001"])
        self.assertGreater(report["bytes"], 0)

    def test_orphan_upload_files_need_no_row_and_seven_days(self):
        row = self.make("row")
        row_file = Path(row.video.path)
        age_tree(row_file, 90)
        old_orphan = put("uploads/videos/rev_talk_old.mp4", 30, age_days=10)
        new_orphan = put("uploads/videos/rev_talk_new.mp4", 30, age_days=2)
        referenced_as_edited = put("uploads/videos/odd_edited.mp4", 30, age_days=40)
        row.edited.name = "uploads/videos/odd_edited.mp4"
        row.save()
        other_feature = put("generated/motion/34/old.mp4", 30, age_days=400)
        sub = put("generated/subtitles/lonely.srt", 30, age_days=400)
        media_cleanup.sweep_orphans()
        self.assertTrue(row_file.is_file(), "row exists")
        self.assertFalse(old_orphan.exists())
        self.assertTrue(new_orphan.is_file())
        self.assertTrue(referenced_as_edited.is_file())
        self.assertTrue(other_feature.is_file() and sub.is_file(), "other media is never looked at")

    def test_dry_run_removes_nothing_and_a_second_run_finds_nothing(self):
        gone = work_tree(9100)
        age_tree(gone, 20)
        orphan = put("uploads/videos/x.mp4", 30, age_days=20)
        dry = media_cleanup.sweep_orphans(dry_run=True)
        self.assertTrue(gone.is_dir() and orphan.is_file())
        self.assertIn("generated/editing/upload_9100", dry["removed"])
        self.assertIn("uploads/videos/x.mp4", dry["removed"])
        first = media_cleanup.sweep_orphans()
        self.assertFalse(gone.exists() or orphan.exists())
        self.assertEqual(len(first["removed"]), 2)
        self.assertEqual(media_cleanup.sweep_orphans()["removed"], [])

    def test_a_symlinked_folder_is_never_followed(self):
        target = Path(tempfile.mkdtemp(prefix="nm-outside-"))
        (target / "precious.txt").write_text("keep")
        try:
            link = Path(TEMP_MEDIA) / "generated/editing/upload_9200"
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("no symlinks here")
            media_cleanup.sweep_orphans(now=time.time() + 400 * DAY)
            self.assertTrue((target / "precious.txt").is_file())
        finally:
            shutil.rmtree(target, ignore_errors=True)

    def test_the_celery_task_and_the_schedule_exist(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["editing-media-sweep"]
        self.assertEqual(entry["task"], "apps.content.tasks_editing.sweep_editing_media")
        self.assertEqual(entry["schedule"], 86400.0)
        gone = work_tree(9300)
        age_tree(gone, 10)
        out = tasks_editing.sweep_editing_media()
        self.assertEqual(out["removed"], 1)
        self.assertFalse(gone.exists())

"""Disk hygiene of the video editor (audit 2026-11-14).

Before this module a deleted video left its upload, its edited copy and the whole ``generated/editing/upload_<pk>`` work folder on the disk
(``upload.delete()`` removes the row, never the files), and an automatic edit left ~4x the video in intermediates (every render round, the
denoised wav, the analysis frames of every round) and copied the finished video through RAM.  On a server whose disk is 87 % full that is
a leak that grows with every video.

Three pieces, all of them conservative (they only ever touch the editor's own folders, never another feature's media):

* ``purge_upload(...)``   - what a deleted video owned: its files and its work folder.
* ``promote`` / ``trim_after_edit(...)`` - the finished edit becomes ``edited.mp4`` by a rename, the intermediates go.
* ``sweep_orphans(...)``  - a daily safety net: a work folder whose upload no longer exists AND that is older than 3 days, and an upload
  file no row points at AND older than 7 days.  Every removal is logged.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: the folders whose files belong to exactly one UploadedVideo (the subtitles folder is shared with generated videos - see `_referenced`)
OWN_PREFIXES = ("uploads/videos/", "generated/edited/", "generated/subtitles/")
ORPHAN_WORK_DAYS = 3
ORPHAN_UPLOAD_DAYS = 7
_WORK_NAME = re.compile(r"^upload_(\d+)$")
_ROUND = re.compile(r"^edit_round\d+\.mp4$")
_AFTER = re.compile(r"^after\d+$")


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT).resolve()


def editing_root() -> Path:
    return media_root() / "generated" / "editing"


def work_dir_of(pk: int) -> Path:
    return editing_root() / f"upload_{int(pk)}"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _tree_size(path: Path) -> int:
    total = 0
    try:
        if path.is_file() or path.is_symlink():
            return path.lstat().st_size
        for base, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.lstat(os.path.join(base, name)).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _newest_mtime(path: Path) -> float:
    """The latest modification time of a file or of anything inside a folder."""
    latest = 0.0
    try:
        latest = path.lstat().st_mtime
        if path.is_dir() and not path.is_symlink():
            for base, dirs, files in os.walk(path):
                for name in files + dirs:
                    try:
                        latest = max(latest, os.lstat(os.path.join(base, name)).st_mtime)
                    except OSError:
                        pass
    except OSError:
        pass
    return latest


def _remove(path: Path, root: Path, report: dict, why: str) -> bool:
    """Delete a file or a folder - only when it is really inside `root` (never through a symlink)."""
    if not path.exists() and not path.is_symlink():
        return False
    if not _inside(path.parent, root) or not _inside(path, root):
        logger.warning("media cleanup: refusing %s (outside %s)", path, root)
        return False
    size = _tree_size(path)
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        logger.warning("media cleanup: could not remove %s: %s", path, exc)
        return False
    report["removed"].append(str(path.relative_to(media_root())).replace("\\", "/"))
    report["bytes"] += size
    logger.info("media cleanup: removed %s (%s, %.1f MB)", path, why, size / 1e6)
    return True


def _new_report() -> dict:
    return {"removed": [], "kept": [], "bytes": 0}


# ------------------------------------------------------------------ what a deleted video owned

def _referenced(name: str, *, exclude_pk: int | None = None) -> bool:
    """Does any other row still point at this stored file name?  (An UploadedVideo made from a render points at the render's own file,
    and generated videos keep their subtitles in the same folder as uploads do.)"""
    from django.db.models import Q

    from .models import UploadedVideo, VideoScript

    rows = UploadedVideo.objects.all()
    if exclude_pk is not None:
        rows = rows.exclude(pk=exclude_pk)
    if rows.filter(Q(video=name) | Q(edited=name) | Q(subtitles=name)).exists():
        return True
    return VideoScript.objects.filter(subtitles=name).exists()


def snapshot(upload) -> dict:
    """What to remove once the row is gone (taken BEFORE `upload.delete()`, which blanks the pk)."""
    return {"pk": upload.pk, "names": [f.name for f in (upload.video, upload.edited, upload.subtitles) if f and f.name]}


def purge_upload(snap: dict) -> dict:
    """Remove the files and the work folder of a deleted upload; never raises (a failed removal is logged and the sweeper retries it later)."""
    report = _new_report()
    root = media_root()
    try:
        pk = int(snap["pk"])
        work = work_dir_of(pk)
        for name in snap.get("names") or []:
            path = root / name
            own = any(name.startswith(p) for p in OWN_PREFIXES) or _inside(path, work)
            if not own:
                report["kept"].append(name)                    # e.g. an upload made from a render: the file belongs to that render
                continue
            if _referenced(name, exclude_pk=pk):
                report["kept"].append(name)
                continue
            _remove(path, root, report, "file of a deleted video")
        if work.exists():
            _remove(work, editing_root(), report, "work folder of a deleted video")
    except Exception:  # noqa: BLE001 - deleting a row must never fail because of a file
        logger.exception("media cleanup: purge of upload %s failed", snap.get("pk"))
    return report


# ------------------------------------------------------------------ after an automatic edit

def promote(rendered: Path, final: Path) -> Path:
    """Make `rendered` the finished `final` WITHOUT reading it into memory: a rename inside the work folder (the usual case), a streamed
    copy only when they are on different volumes."""
    rendered, final = Path(rendered), Path(final)
    if rendered == final:
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(rendered, final)
    except OSError:
        shutil.copyfile(rendered, final)
        try:
            rendered.unlink()
        except OSError:
            pass
    return final


def edit_running(upload_pk, *, exclude_job=None) -> bool:
    """Is another automatic/manual edit of this video still running (so its intermediates must stay)?  A job that has not moved for two
    hours is a dead one and does not count."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.jobs.models import Job

    done = [Job.State.COMPLETED, Job.State.FAILED, Job.State.CANCELLED]
    rows = Job.objects.filter(type=Job.Type.VIDEO_EDIT, context__upload_id=upload_pk, context__has_key="mode",
                              updated_at__gte=timezone.now() - timedelta(hours=2)).exclude(state__in=done)
    if exclude_job is not None:
        rows = rows.exclude(pk=exclude_job)
    return rows.exists()


def trim_after_edit(work: Path, *, new_edit: bool) -> dict:
    """Throw away what an edit run leaves behind.  Always: every render round, the analysis folders of the rounds, the denoise scratch
    folders and the wav files.  When a NEW edited.mp4 was made, also the previous version's derived files (the multi-size «cuts» no longer
    match the video, and the editor's `edited_proxy.mp4` would keep showing the old edit).  Kept: edited.mp4, proxy.mp4 and the small
    analysis of the source (faces, look, shots, stats)."""
    report = _new_report()
    work = Path(work)
    if not work.is_dir():
        return report
    root = editing_root()
    try:
        for child in sorted(work.iterdir()):
            name = child.name
            if child.is_file() and (_ROUND.match(name) or name.lower().endswith(".wav")):
                _remove(child, root, report, "edit intermediate")
            elif child.is_dir() and (_AFTER.match(name) or name in ("denoise_work", "dfn", "noise")):
                _remove(child, root, report, "edit intermediate")
        if new_edit:
            _remove(work / "cuts", root, report, "cuts of the previous version")
            _remove(work / "edited_proxy.mp4", root, report, "stale proxy of the previous version")
    except Exception:  # noqa: BLE001 - housekeeping never fails a finished edit
        logger.exception("media cleanup: trimming %s failed", work)
    return report


# ------------------------------------------------------------------ the daily safety net

def sweep_orphans(*, now: float | None = None, dry_run: bool = False, work_days: float = ORPHAN_WORK_DAYS,
                  upload_days: float = ORPHAN_UPLOAD_DAYS) -> dict:
    """Remove (and log) leftovers of videos that no longer exist.  Only these, and only when old enough:

    * ``generated/editing/upload_<N>`` with no UploadedVideo N and nothing in it newer than `work_days`;
    * ``uploads/videos/<file>`` that no UploadedVideo points at (as video, edited copy or subtitles) and older than `upload_days`.

    Nothing else under MEDIA_ROOT is looked at."""
    from .models import UploadedVideo

    now = time.time() if now is None else now
    report = _new_report()
    report["dry_run"] = dry_run
    root = media_root()

    ed = editing_root()
    if ed.is_dir():
        live = set(UploadedVideo.objects.values_list("pk", flat=True))
        for child in sorted(ed.iterdir()):
            m = _WORK_NAME.match(child.name)
            if not m or not child.is_dir() or child.is_symlink():
                continue
            if int(m.group(1)) in live:
                continue
            age_days = (now - _newest_mtime(child)) / 86400.0
            if age_days < work_days:
                report["kept"].append(f"{child.name} (no row, but only {age_days:.1f} days old)")
                continue
            if dry_run:
                report["removed"].append(f"generated/editing/{child.name}")
                report["bytes"] += _tree_size(child)
            else:
                _remove(child, ed, report, f"work folder with no video, {age_days:.0f} days old")

    up = root / "uploads" / "videos"
    if up.is_dir():
        names = set()
        for row in UploadedVideo.objects.values_list("video", "edited", "subtitles"):
            names.update(n for n in row if n)
        for child in sorted(up.iterdir()):
            rel = f"uploads/videos/{child.name}"
            if not child.is_file() or child.is_symlink() or rel in names:
                continue
            age_days = (now - child.stat().st_mtime) / 86400.0
            if age_days < upload_days:
                report["kept"].append(f"{rel} (no row, but only {age_days:.1f} days old)")
                continue
            if _referenced(rel):
                continue
            if dry_run:
                report["removed"].append(rel)
                report["bytes"] += child.stat().st_size
            else:
                _remove(child, up, report, f"upload with no video, {age_days:.0f} days old")
    if report["removed"]:
        logger.info("media sweep: %s %d item(s), %.1f MB", "would remove" if dry_run else "removed", len(report["removed"]), report["bytes"] / 1e6)
    return report

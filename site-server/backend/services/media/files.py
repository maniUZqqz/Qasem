"""Getting media in and out of storage, wherever storage happens to be.

ffmpeg and Pillow want a path on a disk. Django's `FieldFile.path` gives them
one — and raises `NotImplementedError` the moment storage is anything but the
local filesystem. So every `.path` in the pipeline is a line that works
perfectly until somebody sets `MEDIA_STORAGE=s3`, and then does not.

This module is the two operations that bridge that, and nothing else:

* `reading(field)` — a real local path for something in storage. The file
  itself when storage is local (no copy, no temp file, no cost); a download to
  a temporary file when it is not, cleaned up on the way out.
* `store(field, local_path)` — the reverse. A name assignment when local, an
  upload when not.

**Local stays free.** The whole point of a helper is that the common path costs
nothing: on a single machine `reading` hands back the same path `.path` would
have, and `store` does the same `_media_rel` assignment the tasks did before.
Nobody pays for portability they are not using.
"""
from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File

logger = logging.getLogger(__name__)


def is_shared() -> bool:
    """Is media somewhere every worker can reach?"""
    return bool(getattr(settings, "MEDIA_IS_SHARED", False))


def media_rel(path) -> str:
    """A path under MEDIA_ROOT → the relative name a FileField wants."""
    return str(
        Path(path).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())
    ).replace("\\", "/")


@contextlib.contextmanager
def reading(field):
    """A local path for `field`, for as long as the `with` block lasts.

    On local storage this is the file itself — no copy is made, which matters
    when the file is a 200 MB render and the alternative is duplicating it for
    every QC pass.
    """
    if field is None or not field:
        raise ValueError("این فایل خالی است")

    if not is_shared():
        yield Path(field.path)
        return

    suffix = Path(field.name).suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        with field.open("rb") as remote:
            shutil.copyfileobj(remote, handle)
        handle.close()
        yield Path(handle.name)
    finally:
        # Best-effort: a temp file we could not delete is a disk-space problem,
        # not a reason to fail a render the customer is waiting for.
        try:
            Path(handle.name).unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - platform-specific
            logger.info("Could not remove %s: %s", handle.name, exc)


@contextlib.contextmanager
def reading_all(fields):
    """Local paths for several files at once — one `with`, one cleanup."""
    with contextlib.ExitStack() as stack:
        yield [stack.enter_context(reading(field)) for field in fields]


def store(field, local_path, *, name: str | None = None, save: bool = False) -> str:
    """Put a local file into storage and point `field` at it.

    Returns the stored name. Does not save the model by default: the tasks
    write several fields at once and one `save(update_fields=…)` at the end is
    both cheaper and atomic in the way the caller expects.
    """
    local_path = Path(local_path)

    if not is_shared():
        # Already in MEDIA_ROOT; nothing to copy.
        field.name = name or media_rel(local_path)
        if save:
            field.instance.save(update_fields=[field.field.name])
        return field.name

    target = name or f"{field.field.upload_to}{local_path.name}".replace("//", "/")
    with local_path.open("rb") as handle:
        field.save(target, File(handle), save=save)
    return field.name


def url_for(field) -> str | None:
    """The URL a browser should use, or None when there is no file.

    Wrapped because a signed S3 URL expires and a local one does not; callers
    that cache a URL need one place to find out that they should not.
    """
    if not field:
        return None
    try:
        return field.url
    except Exception as exc:  # noqa: BLE001 — a missing file is data, not a crash
        logger.info("No URL for %s: %s", getattr(field, "name", "?"), exc)
        return None

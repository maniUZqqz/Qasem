"""Receiving a CSV file safely, and previewing it before anything is imported.

The upload is validated (size, extension, text not binary), stored under a random name that
includes the uploader's id, and referred to afterwards only by an opaque ``upload_id``.
Stale uploads are removed opportunistically.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.growth_engine.core import conf, csvio

from . import csv_mapping

UPLOAD_DIR = "growth_engine/uploads"
ALLOWED_EXTENSIONS = (".csv", ".txt", ".tsv")
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class UploadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def safe_file_name(name: str) -> str:
    """Display name only (never used as a path): no directories, no control characters."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:120] or "file.csv"


def _paths(user_id: int, token: str) -> tuple[str, str]:
    return f"{UPLOAD_DIR}/u{user_id}-{token}.csv", f"{UPLOAD_DIR}/u{user_id}-{token}.json"


def cleanup_stale_uploads() -> int:
    """Delete uploads older than ``UPLOAD_TTL_SECONDS``. Best effort; returns how many files went."""
    removed = 0
    try:
        _, files = default_storage.listdir(UPLOAD_DIR)
    except (FileNotFoundError, NotImplementedError, OSError):
        return 0
    cutoff = time.time() - conf.get("UPLOAD_TTL_SECONDS")
    for name in files:
        path = f"{UPLOAD_DIR}/{name}"
        try:
            if default_storage.get_modified_time(path).timestamp() < cutoff:
                default_storage.delete(path)
                removed += 1
        except OSError:
            continue
    return removed


def save_upload(user, uploaded) -> dict:
    """Validate and store an uploaded file; return the preview payload for the mapping step."""
    name = safe_file_name(getattr(uploaded, "name", ""))
    if not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise UploadError("bad_extension", "فقط فایل‌های CSV (و txt/tsv) پذیرفته می‌شوند.")
    limit = conf.get("CSV_MAX_BYTES")
    if getattr(uploaded, "size", 0) and uploaded.size > limit:
        raise UploadError("too_big", f"حجم فایل از {limit // (1024 * 1024)} مگابایت بیشتر است.")
    data = uploaded.read(limit + 1)
    if len(data) > limit:
        raise UploadError("too_big", f"حجم فایل از {limit // (1024 * 1024)} مگابایت بیشتر است.")
    info = analyse(data, name)
    cleanup_stale_uploads()
    token = secrets.token_hex(16)
    data_path, meta_path = _paths(user.pk, token)
    default_storage.save(data_path, ContentFile(data))
    default_storage.save(meta_path, ContentFile(json.dumps({"file_name": name}).encode("utf-8")))
    return {"upload_id": token, "file_name": name, "size": len(data), **info}


def analyse(data: bytes, name: str) -> dict:
    """Decode + parse + first-guess mapping. Raises ``UploadError`` for unreadable files."""
    try:
        text, encoding = csvio.decode_bytes(data)
        headers, rows, delimiter = csvio.read_table(text, max_rows=conf.get("CSV_MAX_ROWS"))
    except csvio.CsvError as exc:
        raise UploadError(exc.code, exc.message) from exc
    if not rows:
        raise UploadError("no_rows", "فایل فقط ردیفِ عنوان دارد و هیچ ردیفِ داده‌ای در آن نیست.")
    preview_n = conf.get("CSV_PREVIEW_ROWS")
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "total_rows": len(rows),
        "headers": headers,
        "sample_rows": [{"row": number, "cells": cells[: len(headers)]} for number, cells in rows[:preview_n]],
        "suggested_mapping": csv_mapping.suggest_mapping(headers),
        "targets": csv_mapping.TARGETS,
    }


def load_upload(user_id: int, token: str) -> tuple[bytes, str]:
    """(bytes, file name) of an upload of this user. Raises ``UploadError`` when it is gone."""
    if not _TOKEN.match(token or ""):
        raise UploadError("bad_upload", "شناسهٔ فایل معتبر نیست.")
    data_path, meta_path = _paths(user_id, token)
    try:
        with default_storage.open(data_path, "rb") as fh:
            data = fh.read()
        with default_storage.open(meta_path, "rb") as fh:
            name = json.loads(fh.read().decode("utf-8")).get("file_name", "file.csv")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise UploadError("upload_missing", "فایل پیدا نشد یا منقضی شده؛ دوباره آپلودش کنید.") from exc
    return data, safe_file_name(name)


def delete_upload_files(data_path: str) -> None:
    """Remove a stored upload and its sidecar (best effort)."""
    for path in (data_path, data_path[:-4] + ".json" if data_path.endswith(".csv") else ""):
        if path:
            try:
                default_storage.delete(path)
            except OSError:
                pass

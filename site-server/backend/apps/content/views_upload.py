"""Resumable (chunked) video upload.

A phone video over a slow or dropping line cannot be one 300 MB POST: the line breaks at 80 % and everything starts again, nginx may refuse
the body (the panel's server allows 200 MB per request) and the person sees nothing until it is over. So the panel sends small pieces:

    POST   stores/<id>/videos/uploads/               {name, size, key?, title?} → {upload_id, received, chunk}   (a session; `key` = name+size+date of the
                                                      file, so the SAME file picked again after a reload / a new day continues where it stopped)
    GET    stores/<id>/videos/uploads/<uid>/          → {received, size}                                          (where to continue from)
    PUT    stores/<id>/videos/uploads/<uid>/?offset=N raw bytes (≤ 8 MiB) → {received}                              (a repeated piece is accepted, a gap is refused with `received`)
    POST   stores/<id>/videos/uploads/<uid>/finish/   → 201 {video, job_id}                                       (checks the size and that ffprobe sees a video, then the usual analyse job)
    DELETE stores/<id>/videos/uploads/<uid>/          → 204                                                       (cancel; the pieces are removed)

Sessions live on disk (a .json next to a .part) — no table, nothing to migrate; abandoned ones are swept after 48 hours.
The old single-POST endpoint keeps working for scripts.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.utils.text import get_valid_filename
from rest_framework import status
from rest_framework.parsers import BaseParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.video.ffmpeg import probe

from .models import UploadedVideo
from .tasks_editing import analyze_upload_task
from .views_editing import ALLOWED_SUFFIXES, MAX_UPLOAD_MB, UploadedVideoSerializer

logger = logging.getLogger(__name__)

CHUNK_HINT = 2 * 1024 * 1024         # what the panel starts with (it adapts to the line)
CHUNK_MAX = 8 * 1024 * 1024          # one PUT never carries more than this
STALE_SECONDS = 48 * 3600
MAX_OPEN_PER_STORE = 4
MIN_FREE_AFTER = 600 * 1024 * 1024   # keep this much disk free after the file lands


def _err(code: str, message: str, http: int = status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http)


class RawParser(BaseParser):
    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()


def _root(store_id: int) -> Path:
    path = Path(settings.MEDIA_ROOT) / "uploads" / "tmp" / f"s{int(store_id)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_path(store_id: int, uid: str) -> Path:
    return _root(store_id) / f"{uid}.json"


def _part_path(store_id: int, uid: str) -> Path:
    return _root(store_id) / f"{uid}.part"


def _load(store_id: int, uid: str, user_id: int) -> dict | None:
    if not uid.isalnum():
        return None
    try:
        meta = json.loads(_meta_path(store_id, uid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if meta.get("user") == user_id and meta.get("store") == store_id else None


def _save(meta: dict) -> None:
    meta["touched"] = time.time()
    path = _meta_path(meta["store"], meta["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _received(meta: dict) -> int:
    try:
        return _part_path(meta["store"], meta["id"]).stat().st_size
    except OSError:
        return 0


def _drop(store_id: int, uid: str) -> None:
    for p in (_meta_path(store_id, uid), _part_path(store_id, uid)):
        p.unlink(missing_ok=True)


def sweep(store_id: int, now: float | None = None) -> int:
    """Remove sessions nobody touched for 48 h (called whenever a new one starts). Returns how many went."""
    now = now or time.time()
    n = 0
    for meta_file in _root(store_id).glob("*.json"):
        try:
            if now - json.loads(meta_file.read_text(encoding="utf-8")).get("touched", 0) > STALE_SECONDS:
                _drop(store_id, meta_file.stem)
                n += 1
        except (OSError, ValueError):
            meta_file.unlink(missing_ok=True)
    for part in _root(store_id).glob("*.part"):
        if not part.with_suffix(".json").exists():
            part.unlink(missing_ok=True)
    return n


def _view(meta: dict) -> dict:
    got = _received(meta)
    return {"upload_id": meta["id"], "received": got, "size": meta["size"], "chunk": CHUNK_HINT, "chunk_max": CHUNK_MAX}


class UploadStartView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        name = str(request.data.get("name") or "").strip()[:200]
        try:
            size = int(request.data.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if not name or size <= 0:
            return _err("bad_request", "نام یا اندازهٔ فایل فرستاده نشد.")
        if not name.lower().endswith(ALLOWED_SUFFIXES):
            return _err("wrong_type", f"این فرمت پذیرفته نمی‌شود. فرمت‌های قابل قبول: {'، '.join(ALLOWED_SUFFIXES)}")
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            return _err("too_big", f"حجمِ فایل بیشتر از {MAX_UPLOAD_MB} مگابایت است. آن را کوچک‌تر کنید (مثلاً با ضبط با کیفیتِ ۱۰۸۰ به‌جای ۴K).")
        sweep(store.pk)
        key = str(request.data.get("key") or "")[:120]
        open_sessions = []
        for mf in _root(store.pk).glob("*.json"):
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if m.get("user") == request.user.pk:
                open_sessions.append(m)
        if key:
            same = next((m for m in open_sessions if m.get("key") == key and m.get("size") == size), None)
            if same:                                                        # the same file again: continue it
                _save(same)
                return Response({**_view(same), "resumed": True})
        if len(open_sessions) >= MAX_OPEN_PER_STORE:
            oldest = min(open_sessions, key=lambda m: m.get("touched", 0))
            _drop(store.pk, oldest["id"])                                   # an abandoned one makes room
        free = shutil.disk_usage(settings.MEDIA_ROOT).free
        if free < size + MIN_FREE_AFTER:
            return _err("disk_full", "فضای سرور برای این فایل کافی نیست. به پشتیبانی خبر بدهید یا فایلِ کوچک‌تری بفرستید.", status.HTTP_507_INSUFFICIENT_STORAGE)
        meta = {"id": uuid.uuid4().hex[:20], "store": store.pk, "user": request.user.pk, "name": name, "size": size, "key": key,
                "title": str(request.data.get("title") or "").strip()[:200] or name, "created": time.time()}
        _part_path(store.pk, meta["id"]).touch()
        _save(meta)
        return Response({**_view(meta), "resumed": False}, status=status.HTTP_201_CREATED)


class UploadChunkView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [RawParser]

    def _session(self, request, store_id, uid):
        access.get_store(request.user, store_id, access.CONTENT)
        return _load(store_id, uid, request.user.pk)

    def get(self, request, store_id, uid):
        meta = self._session(request, store_id, uid)
        if meta is None:
            return _err("gone", "این آپلود دیگر وجود ندارد؛ فایل را دوباره انتخاب کنید.", status.HTTP_404_NOT_FOUND)
        return Response(_view(meta))

    def put(self, request, store_id, uid):
        meta = self._session(request, store_id, uid)
        if meta is None:
            return _err("gone", "این آپلود دیگر وجود ندارد؛ فایل را دوباره انتخاب کنید.", status.HTTP_404_NOT_FOUND)
        try:
            offset = int(request.query_params.get("offset", ""))
        except ValueError:
            return _err("bad_offset", "جای این تکه معلوم نیست.")
        data = request.data if isinstance(request.data, (bytes, bytearray)) else b""
        if not data:
            return _err("empty", "تکهٔ خالی فرستاده شد.")
        if len(data) > CHUNK_MAX:
            return _err("chunk_too_big", "تکهٔ فرستاده‌شده از سقفِ مجاز بزرگ‌تر است.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        part = _part_path(store_id, uid)
        got = part.stat().st_size if part.exists() else 0
        if offset > got:
            return _err("gap", "یک تکه جا افتاده؛ از جای درست ادامه بده.", status.HTTP_409_CONFLICT, received=got)
        if offset + len(data) <= got:                                       # a retry of something we already have (the answer got lost)
            return Response({"received": got, "size": meta["size"], "duplicate": True})
        if offset < got:                                                    # partly known: keep only the new tail
            data = bytes(data)[got - offset:]
        if got + len(data) > meta["size"]:
            return _err("overflow", "حجمِ فرستاده‌شده از اندازهٔ اعلام‌شدهٔ فایل بیشتر شد؛ آپلود را از اول شروع کن.", status.HTTP_409_CONFLICT, received=got)
        with open(part, "ab") as fh:
            fh.write(data)
        meta["touched"] = time.time()
        _save(meta)
        return Response({"received": got + len(data), "size": meta["size"]})

    def delete(self, request, store_id, uid):
        access.get_store(request.user, store_id, access.CONTENT)
        if _load(store_id, uid, request.user.pk) is not None:
            _drop(store_id, uid)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UploadFinishView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT)
        meta = _load(store.pk, uid, request.user.pk)
        if meta is None:
            return _err("gone", "این آپلود دیگر وجود ندارد؛ فایل را دوباره انتخاب کنید.", status.HTTP_404_NOT_FOUND)
        got = _received(meta)
        if got != meta["size"]:
            return _err("incomplete", f"آپلود کامل نشده ({got} از {meta['size']} بایت). ادامه بده.", status.HTTP_409_CONFLICT, received=got)
        part = _part_path(store.pk, uid)
        try:
            info = probe(part)
            has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
        except Exception:  # noqa: BLE001 — ffprobe refused it: not a video (or cut short)
            has_video = False
        if not has_video:
            _drop(store.pk, uid)
            return _err("not_video", "این فایل ویدیوی سالم نیست (خراب یا ناقص است). یک بار دیگر از گوشی یا دوربین بفرستید.")
        stem, ext = os.path.splitext(get_valid_filename(meta["name"]) or "video.mp4")
        folder = Path(settings.MEDIA_ROOT) / "uploads" / "videos"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{stem[:80]}_{uuid.uuid4().hex[:8]}{ext.lower()}"
        os.replace(part, dest)
        _meta_path(store.pk, uid).unlink(missing_ok=True)
        upload = UploadedVideo.objects.create(store=store, title=meta["title"], video=str(dest.relative_to(settings.MEDIA_ROOT)).replace("\\", "/"))
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_ANALYSIS, context={"upload_id": upload.pk})
        failed = dispatch_job(job, analyze_upload_task, job.id, upload.pk)
        if failed is not None:
            return failed
        return Response({"video": UploadedVideoSerializer(upload).data, "job_id": job.id}, status=status.HTTP_201_CREATED)

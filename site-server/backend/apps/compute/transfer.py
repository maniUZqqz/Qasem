"""انتقالِ فایل‌های بزرگ برای کارهای گره (رندرِ نهایی): دانلودِ ازسرگیرِ ورودی‌ها و آپلودِ ازسرگیرِ خروجی.

  GET /api/v1/compute/jobs/<uid>/files/<fid>/                 فایلِ ورودیِ کار (Range، سرآیند X-NM-SHA256)
  GET /api/v1/compute/jobs/<uid>/chunks/<name>/               وضعیتِ آپلودِ خروجی: {"size": بایتِ دریافت‌شده, "complete": bool}
  PUT /api/v1/compute/jobs/<uid>/chunks/<name>/?offset=&total=&sha256=   یک تکه (بدنهٔ خام)؛ offset باید همان size باشد، وگرنه 409

چرا جدا از package/upload: بستهٔ کار همه‌چیز را در یک zip می‌ریزد و upload کلِ فایل را در یک multipart می‌فرستد؛ برای فیلمِ چندصد
مگابایتی روی خطِ ناپایدار هر قطع‌شدن یعنی از اول. این‌جا هر دو سو از همان‌جا که ماندند ادامه می‌دهند و آخرش sha256 سنجیده می‌شود.
فایل‌های ورودی را سرور در `<پوشهٔ کار>/assets.json` ثبت می‌کند ({fid: {path, size, sha256, name}}) — مسیرِ سرور هرگز به گره نمی‌رود.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.response import Response

from . import services as SV
from .api import _job_of, node_api

ASSETS = "assets.json"
READ_CHUNK = 1 << 20
MAX_CHUNK = 16 << 20
MAX_TOTAL = 8 << 30
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def assets_file(job) -> Path:
    return SV.job_root(job) / ASSETS


def register_assets(job, assets: dict) -> None:
    """{fid: {"path", "size", "sha256", "name"}} — the files the node may download for this job."""
    tmp = assets_file(job).with_suffix(".tmp")
    tmp.write_text(json.dumps(assets, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, assets_file(job))


def load_assets(job) -> dict:
    try:
        return json.loads(assets_file(job).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_file(path: Path, start: int, end: int):
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            data = fh.read(min(READ_CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@node_api("GET")
def job_file(request, uid, fid):
    node, job = _job_of(request, uid)
    entry = load_assets(job).get(str(fid))
    path = Path(entry["path"]) if entry else None
    if not path or not path.is_file():
        return Response({"error": "فایل پیدا نشد"}, status=404)
    size = path.stat().st_size
    start, end, status = 0, size - 1, 200
    header = request.META.get("HTTP_RANGE", "")
    if header:
        m = _RANGE.match(header.strip())
        if not m or (not m.group(1) and not m.group(2)):
            return Response({"error": "Range نامعتبر"}, status=416)
        if m.group(1):
            start = int(m.group(1))
            end = min(size - 1, int(m.group(2))) if m.group(2) else size - 1
        else:                                            # bytes=-N : the last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size or start > end:
            resp = Response({"error": "خارج از فایل"}, status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        status = 206
    job.heartbeat_at = timezone.now()
    job.save(update_fields=["heartbeat_at"])
    resp = StreamingHttpResponse(_iter_file(path, start, end), status=status, content_type="application/octet-stream")
    resp["Content-Length"] = str(end - start + 1)
    resp["Accept-Ranges"] = "bytes"
    resp["X-NM-SHA256"] = entry.get("sha256", "")
    if status == 206:
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
    return resp


def _part(job, name) -> tuple[Path, Path]:
    final = SV.output_path(job, name)
    return final, final.with_name(final.name + ".part")


@node_api("GET", "PUT")
def output_chunks(request, uid, name):
    node, job = _job_of(request, uid)
    final, part = _part(job, name)
    have = part.stat().st_size if part.is_file() else 0
    if request.method == "GET":
        return Response({"size": have, "complete": final.is_file() and not part.is_file(),
                         "final_size": final.stat().st_size if final.is_file() else 0})
    try:
        offset = int(request.query_params.get("offset", ""))
        total = int(request.query_params.get("total", ""))
    except ValueError:
        return Response({"error": "offset و total لازم است"}, status=400)
    sha = (request.query_params.get("sha256") or "").lower()
    body = request.body
    if not (0 <= total <= MAX_TOTAL) or len(body) > MAX_CHUNK or offset < 0:
        return Response({"error": "اندازهٔ نامعتبر"}, status=400)
    if offset != have:
        if offset == 0 and have:                        # a fresh start of the same file
            part.unlink(missing_ok=True)
            have = 0
        else:
            return Response({"size": have, "error": "offset"}, status=409)
    if have + len(body) > total:
        part.unlink(missing_ok=True)
        return Response({"size": 0, "error": "بیشتر از اندازهٔ اعلام‌شده"}, status=400)
    with open(part, "ab") as fh:
        fh.write(body)
    size = have + len(body)
    job.heartbeat_at = timezone.now()
    job.save(update_fields=["heartbeat_at"])
    if size == total:
        if sha and file_sha256(part) != sha:
            part.unlink(missing_ok=True)
            return Response({"size": 0, "error": "sha256"}, status=422)
        os.replace(part, final)
        return Response({"size": size, "complete": True})
    return Response({"size": size, "complete": False})

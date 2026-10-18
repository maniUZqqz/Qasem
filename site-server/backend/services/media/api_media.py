"""Image and video generation over an HTTP API, as an alternative to ComfyUI.

ComfyUI patches a workflow graph and polls `/history`; a hosted API takes a
prompt and returns a URL. This module hides that difference behind the same
"give me a file on disk" contract the ComfyUI client already offers, so
`apps.content.tasks` can switch between our GPU and someone else's without
knowing which it got.

Two request shapes cover almost every vendor:

* **sync** — POST returns the image/video (or its URL) in one response.
  OpenAI images, most image APIs.
* **async** — POST returns a job id, then a status URL is polled until the
  output URL appears. Replicate, Runway, Kling, most video APIs.

Which one, and where the fields live in the JSON, is configured per provider
in `options` so a new vendor is an admin form, not a code change.
"""
from __future__ import annotations

import base64
import logging
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3.0
DOWNLOAD_TIMEOUT = 300


class MediaAPIError(Exception):
    """The remote generator failed or returned something unusable."""


def _dig(data, path: str, default=None):
    """`_dig(payload, "output.0.url")` → payload["output"][0]["url"]."""
    if not path:
        return default
    current = data
    for part in path.split("."):
        if current is None:
            return default
        if part.isdigit() and isinstance(current, (list, tuple)):
            index = int(part)
            current = current[index] if index < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return default
    return current if current is not None else default


def _headers(resolved) -> dict:
    headers = {"Content-Type": "application/json"}
    if resolved.api_key:
        scheme = (resolved.options or {}).get("auth_scheme", "Bearer")
        header = (resolved.options or {}).get("auth_header", "Authorization")
        headers[header] = f"{scheme} {resolved.api_key}".strip()
    return headers


def _save(content: bytes, dest_dir, suffix: str, filename=None) -> Path:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / (filename or f"{uuid.uuid4().hex}{suffix}")
    path.write_bytes(content)
    return path


def _fetch(url: str, dest_dir, suffix: str, filename=None) -> Path:
    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MediaAPIError(f"دانلود خروجی ممکن نشد: {exc}") from exc
    return _save(response.content, dest_dir, suffix, filename)


def _result_to_file(payload, resolved, dest_dir, suffix, filename) -> Path:
    """Pull the produced file out of a response, however it was returned."""
    options = resolved.options or {}
    url = _dig(payload, options.get("output_url_path", "data.0.url"))
    if isinstance(url, list):
        url = url[0] if url else None
    if url:
        return _fetch(url, dest_dir, suffix, filename)

    b64 = _dig(payload, options.get("output_b64_path", "data.0.b64_json"))
    if isinstance(b64, list):
        b64 = b64[0] if b64 else None
    if b64:
        return _save(base64.b64decode(b64), dest_dir, suffix, filename)

    raise MediaAPIError(
        "پاسخ سرویس نه آدرس فایل داشت نه محتوای base64. "
        "مسیر خروجی را در options تنظیم کن (output_url_path)."
    )


def _submit(resolved, body: dict) -> dict:
    url = resolved.base_url
    try:
        response = requests.post(
            url, json=body, headers=_headers(resolved), timeout=resolved.timeout_s
        )
    except requests.Timeout as exc:
        raise MediaAPIError(f"سرویس در {resolved.timeout_s} ثانیه پاسخ نداد.") from exc
    except requests.RequestException as exc:
        raise MediaAPIError(f"اتصال به سرویس ممکن نشد: {exc}") from exc

    if response.status_code == 401:
        raise MediaAPIError("کلید API پذیرفته نشد (۴۰۱).")
    if response.status_code == 429:
        raise MediaAPIError("سهمیه‌ی سرویس تمام شده است (۴۲۹).")
    if response.status_code >= 400:
        raise MediaAPIError(f"خطای سرویس {response.status_code}: {response.text[:300]}")
    return response.json()


def _poll(resolved, payload: dict) -> dict:
    """Follow an async job until it finishes."""
    options = resolved.options or {}
    status_url = _dig(payload, options.get("status_url_path", "urls.get"))
    if not status_url:
        job_id = _dig(payload, options.get("job_id_path", "id"))
        template = options.get("status_url_template", "")
        if not (job_id and template):
            return payload  # nothing to poll — treat as already complete
        status_url = template.format(id=job_id)

    done_values = {
        str(v).lower() for v in options.get("done_values", ["succeeded", "completed", "success"])
    }
    fail_values = {
        str(v).lower() for v in options.get("failed_values", ["failed", "error", "canceled"])
    }
    status_path = options.get("status_path", "status")

    deadline = time.monotonic() + resolved.timeout_s
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            response = requests.get(status_url, headers=_headers(resolved), timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("poll failed (%s); retrying", exc)
            continue
        current = response.json()
        state = str(_dig(current, status_path, "")).lower()
        if state in fail_values:
            detail = _dig(current, options.get("error_path", "error"), "")
            raise MediaAPIError(f"تولید ناموفق بود: {detail or state}")
        if state in done_values or not state:
            return current
    raise MediaAPIError(f"سرویس در {resolved.timeout_s} ثانیه کاری تحویل نداد.")


def _run(resolved, body: dict, dest_dir, suffix: str, filename=None) -> Path:
    options = resolved.options or {}
    payload = _submit(resolved, body)
    if options.get("mode", "sync") == "async":
        payload = _poll(resolved, payload)
    return _result_to_file(payload, resolved, dest_dir, suffix, filename)


# ---------------------------------------------------------------- public


def generate_image(resolved, prompt: str, dest_dir, *, negative="", image_path=None,
                   width=None, height=None, filename=None) -> Path:
    """Text-to-image, or image-to-image when `image_path` is given."""
    options = resolved.options or {}
    body = {
        "model": resolved.model_name,
        "prompt": prompt,
        **{k: v for k, v in options.items() if k not in _CONTROL_KEYS},
    }
    if negative:
        body[options.get("negative_field", "negative_prompt")] = negative
    if width and height:
        body[options.get("size_field", "size")] = f"{width}x{height}"
    if image_path:
        body[options.get("image_field", "image")] = base64.b64encode(
            Path(image_path).read_bytes()
        ).decode()
    return _run(resolved, body, dest_dir, ".png", filename)


def generate_video(resolved, prompt: str, dest_dir, *, image_path=None,
                   duration=None, negative="", filename=None) -> Path:
    """Image-to-video (the anchor frame) or text-to-video."""
    options = resolved.options or {}
    body = {
        "model": resolved.model_name,
        "prompt": prompt,
        **{k: v for k, v in options.items() if k not in _CONTROL_KEYS},
    }
    if negative:
        body[options.get("negative_field", "negative_prompt")] = negative
    if duration:
        body[options.get("duration_field", "duration")] = duration
    if image_path:
        body[options.get("image_field", "image")] = base64.b64encode(
            Path(image_path).read_bytes()
        ).decode()
    return _run(resolved, body, dest_dir, ".mp4", filename)


def replicate_health(resolved) -> tuple[bool, str]:
    """Reachability probe for a Replicate-style endpoint."""
    if not resolved.base_url:
        return False, "آدرس تنظیم نشده است."
    try:
        response = requests.get(
            resolved.base_url, headers=_headers(resolved), timeout=20
        )
    except requests.RequestException as exc:
        return False, f"اتصال ممکن نشد: {exc}"
    if response.status_code == 401:
        return False, "کلید API پذیرفته نشد (۴۰۱)."
    if response.status_code >= 500:
        return False, f"سرویس خطا داد ({response.status_code})."
    return True, f"پاسخ داد ({response.status_code})."


# option keys that configure this module rather than the remote model
_CONTROL_KEYS = {
    "mode", "auth_scheme", "auth_header", "output_url_path", "output_b64_path",
    "status_url_path", "status_url_template", "job_id_path", "status_path",
    "done_values", "failed_values", "error_path", "negative_field",
    "size_field", "image_field", "duration_field",
}

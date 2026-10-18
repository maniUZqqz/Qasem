"""
ComfyUI client — ported from the proven Flask prototype (`API/app.py`) with
timeouts, typed errors and configurable endpoints.

Only this module talks to the ComfyUI HTTP API.
"""
import logging
import time
import uuid
from pathlib import Path

import requests
from django.conf import settings

from services.comfyui import remote
from services.net import is_listening

logger = logging.getLogger(__name__)


class ComfyUIError(Exception):
    """Base error for ComfyUI failures."""


class ComfyUITimeout(ComfyUIError):
    pass


class ComfyUIJobFailed(ComfyUIError):
    pass


class ComfyUIUnavailable(ComfyUIError):
    """ComfyUI is not running at all — distinct from a workflow that failed.

    Worth its own type and its own message: "ComfyUI is switched off" is the
    single most common reason an image or video job fails on the main system,
    and the owner can fix it in ten seconds if we say so plainly instead of
    surfacing a raw English ConnectionError.
    """


class ComfyUIClient:
    def __init__(self, base_url=None, timeout=None, poll_interval=None):
        conf = settings.UPMARKET_AI
        self.base_url = (base_url or conf["COMFYUI_BASE_URL"]).rstrip("/")
        self.timeout = timeout or conf["COMFYUI_TIMEOUT"]
        self.poll_interval = poll_interval or conf["COMFYUI_POLL_INTERVAL"]
        self.http_timeout = 60
        # agent://  ⇐ کار روی سرورِ پردازش (GPU، بی‌IP) انجام می‌شود؛ services/comfyui/remote.py
        self.remote = None
        if remote.is_agent_url(self.base_url):
            self.remote = remote.RemoteTransport(self)

    def _unavailable(self, detail="") -> ComfyUIUnavailable:
        return ComfyUIUnavailable(
            f"ComfyUI در دسترس نیست ({self.base_url}) — برنامهٔ ComfyUI را روی "
            "سیستم اجرا کنید (یا COMFYUI_BASE_URL را در backend/.env.local بنویسید — این فایل مخصوص همین سیستم است) "
            "و دوباره تلاش کنید. بدون ComfyUI تولید تصویر و ویدیو ممکن نیست."
            + (f" جزئیات: {detail}" if detail else "")
        )

    def _ensure_up(self) -> None:
        """Fail fast and in Persian when nothing is listening on the port.

        This is the cheap check. It can still be wrong — `is_listening` caches
        its answer for a few seconds, and ComfyUI can die mid-job — so every
        call site ALSO maps a connection error to the same message; the probe
        only saves the user from waiting on a socket that will never answer.
        """
        if getattr(settings, "IS_TEST", False):
            return
        if self.remote is not None:
            if not self.remote.available():
                raise self.remote.unavailable_error()
            return
        if not is_listening(self.base_url):
            raise self._unavailable()

    # ------------------------------------------------------------------ IO
    def upload_image(self, image_path) -> str:
        """Upload an input image; returns the server-side filename to reference."""
        path = Path(image_path)
        self._ensure_up()
        if self.remote is not None:
            return self.remote.upload_image(path)
        try:
            with path.open("rb") as fh:
                response = requests.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (path.name, fh)},
                    data={"overwrite": "true"},
                    timeout=self.http_timeout,
                )
            response.raise_for_status()
            return response.json()["name"]
        except requests.HTTPError as exc:
            detail = getattr(exc.response, "text", "")[:1000]
            raise ComfyUIError(f"Image upload failed: {exc} — {detail}") from exc
        except requests.ConnectionError as exc:
            raise self._unavailable(str(exc)[:200]) from exc
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise ComfyUIError(f"Image upload failed: {exc}") from exc

    def submit(self, workflow: dict) -> str:
        """Queue an API-format workflow; returns the prompt_id."""
        client_id = str(uuid.uuid4())
        self._ensure_up()
        if self.remote is not None:
            return self.remote.submit(workflow)
        try:
            response = requests.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
                timeout=self.http_timeout,
            )
            response.raise_for_status()
            return response.json()["prompt_id"]
        except requests.HTTPError as exc:
            # ComfyUI puts node validation errors in the body — surface them
            detail = getattr(exc.response, "text", "")[:1000]
            raise ComfyUIError(f"Workflow submission failed: {exc} — {detail}") from exc
        except requests.ConnectionError as exc:
            raise self._unavailable(str(exc)[:200]) from exc
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise ComfyUIError(f"Workflow submission failed: {exc}") from exc

    # ------------------------------------------------------------------ tracking
    def wait_for_output(self, prompt_id: str, timeout=None) -> dict:
        """Poll /history until the job produces a video/image output or fails.

        Returns the output file info dict: {"filename", "subfolder", "type"}.
        """
        if self.remote is not None:
            return self.remote.wait_for_output(prompt_id, timeout=timeout)
        budget = timeout or self.timeout
        deadline = time.monotonic() + budget
        consecutive_failures = 0
        while time.monotonic() < deadline:
            try:
                response = requests.get(
                    f"{self.base_url}/history/{prompt_id}", timeout=self.http_timeout
                )
                response.raise_for_status()
                history = response.json()
                consecutive_failures = 0
            except (requests.RequestException, ValueError) as exc:
                # a long GPU job must survive transient poll blips
                consecutive_failures += 1
                logger.warning(
                    "ComfyUI history poll failed (%s in a row): %s", consecutive_failures, exc
                )
                if consecutive_failures >= 10:
                    # ComfyUI dying mid-render (out of VRAM) is the usual cause,
                    # so give the actionable message rather than a poll trace
                    if isinstance(exc, requests.ConnectionError):
                        raise self._unavailable(
                            "ارتباط وسط رندر قطع شد — احتمالاً ComfyUI بسته شد یا حافظهٔ "
                            "کارت گرافیک تمام شد."
                        ) from exc
                    raise ComfyUIError(
                        f"History polling failed {consecutive_failures} times in a row: {exc}"
                    ) from exc
                time.sleep(self.poll_interval)
                continue

            if prompt_id in history:
                entry = history[prompt_id]
                outputs = entry.get("outputs", {})
                for _node_id, output in outputs.items():
                    if "videos" in output and output["videos"]:
                        return output["videos"][0]
                    if "images" in output and output["images"]:
                        for item in output["images"]:
                            if item.get("filename", "").endswith((".mp4", ".webm", ".mov")):
                                return item
                        # image workflows: first image is the result
                        if not any(
                            o.get("videos") for o in outputs.values()
                        ):
                            return output["images"][0]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIJobFailed(f"ComfyUI reported an error: {status}")
                if status.get("completed") or status.get("status_str") == "success":
                    # finished but produced no output key we recognize — say so
                    # clearly instead of spinning until the timeout
                    keys = {k for o in outputs.values() for k in o}
                    raise ComfyUIJobFailed(
                        f"ComfyUI job {prompt_id} completed but returned no video/image "
                        f"output (output keys: {sorted(keys) or 'none'})"
                    )
            time.sleep(self.poll_interval)
        raise ComfyUITimeout(f"ComfyUI job {prompt_id} exceeded {budget}s")

    def download(self, output_info: dict, dest_dir, filename=None) -> Path:
        """Download an output file to dest_dir; returns the local path."""
        if self.remote is not None:
            return self.remote.download(output_info, dest_dir, filename=filename)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        name = filename or f"{uuid.uuid4().hex}_{output_info['filename']}"
        try:
            response = requests.get(
                f"{self.base_url}/view",
                params={
                    "filename": output_info["filename"],
                    "subfolder": output_info.get("subfolder", ""),
                    "type": output_info.get("type", "output"),
                },
                timeout=self.http_timeout,
            )
            response.raise_for_status()
        except requests.ConnectionError as exc:
            raise self._unavailable(str(exc)[:200]) from exc
        except requests.RequestException as exc:
            raise ComfyUIError(f"Output download failed: {exc}") from exc
        local_path = dest / name
        local_path.write_bytes(response.content)
        return local_path

    # ------------------------------------------------------------------ introspection
    def has_node(self, class_name: str) -> bool | None:
        """آیا این نودِ سفارشی نصب است؟ None یعنی نمی‌دانیم (گرهٔ راه‌دور فهرست نفرستاده)."""
        if self.remote is not None:
            return remote.has_comfy_node(class_name, self.base_url)
        try:
            response = requests.get(f"{self.base_url}/object_info/{class_name}", timeout=15)
            return bool(response.json()) if response.ok else False
        except (requests.RequestException, ValueError):
            return False

    # ------------------------------------------------------------------ high level
    def generate(self, workflow: dict, dest_dir, filename=None, timeout=None) -> Path:
        """submit → wait → download. Returns the local output file path."""
        prompt_id = self.submit(workflow)
        logger.info("ComfyUI job queued: %s", prompt_id)
        output_info = self.wait_for_output(prompt_id, timeout=timeout)
        return self.download(output_info, dest_dir, filename=filename)

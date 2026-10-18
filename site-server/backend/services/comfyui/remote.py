"""ComfyUI روی سرورِ پردازش (agent://) — همان ComfyUIClient، ولی کار به‌جای HTTP ِ مستقیم
به صفِ apps.compute می‌رود و یکی از سرورهای پردازش (GPU) آن را انجام می‌دهد.

    COMFYUI_BASE_URL=agent://any        هر سرورِ پردازشی که ComfyUI دارد
    COMFYUI_BASE_URL=agent://gpu-1      فقط گرهٔ gpu-1

سرورِ پردازش IP ندارد؛ خودش به سایت وصل می‌شود و کار می‌گیرد (apps/compute/models.py).
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEME = "agent://"


def is_agent_url(url: str) -> bool:
    return (url or "").startswith(SCHEME)


def node_name(url: str) -> str:
    """'agent://gpu-1' ⇐ 'gpu-1'؛ 'agent://any' یا 'agent://' ⇐ انتخابِ پنل (ComputeSettings) یا ''"""
    name = (url or "")[len(SCHEME):].strip("/").strip()
    if name in ("", "any", "*"):
        try:
            from apps.compute.models import ComputeSettings

            return (ComputeSettings.get().image_video_node or "").strip()
        except Exception:  # noqa: BLE001 — بی‌دیتابیس (ابزار/تست): «هر گره»
            return ""
    return name


def comfy_nodes_online(url: str = "agent://any") -> list:
    from apps.compute import services as compute

    nodes = compute.online_nodes("comfyui")
    wanted = node_name(url)
    return [n for n in nodes if not wanted or n.name == wanted]


def has_comfy_node(class_name: str, url: str = "agent://any") -> bool | None:
    """آیا نودِ سفارشیِ ComfyUI (مثلاً LatentSync) روی گره‌ای نصب است؟ None = گره‌ای گزارشی نداده."""
    known = None
    for n in comfy_nodes_online(url):
        names = (n.capabilities or {}).get("comfy_nodes")
        if not isinstance(names, list):
            continue
        known = False
        if class_name in names:
            return True
    return known


class RemoteTransport:
    """پشتِ ComfyUIClient وقتی base_url با agent:// شروع شود."""

    def __init__(self, client):
        self.client = client
        self.url = client.base_url
        self.node = node_name(self.url)
        self._uploads: dict[str, str] = {}
        self._jobs: dict[str, object] = {}

    # ─── وضعیت
    def available(self) -> bool:
        return bool(comfy_nodes_online(self.url))

    def unavailable_error(self):
        from services.comfyui.client import ComfyUIUnavailable

        who = f"سرورِ پردازشِ «{self.node}»" if self.node else "هیچ سرورِ پردازشی با ComfyUI"
        return ComfyUIUnavailable(
            f"{who} آنلاین نیست — روی سیستمِ گرافیکی START.bat ِ بستهٔ UpMarket-Processing را اجرا کنید "
            "(صفحهٔ «سرورهای پردازش» در پنل وضعیت را نشان می‌دهد). بدون سرورِ پردازش تولید تصویر و ویدیو ممکن نیست."
        )

    # ─── IO
    def upload_image(self, image_path) -> str:
        path = Path(image_path)
        if not path.is_file():
            from services.comfyui.client import ComfyUIError

            raise ComfyUIError(f"فایلِ ورودی پیدا نشد: {path}")
        # نام از روی محتوا: دو کارِ هم‌زمان با فایلِ متفاوت روی یک گره هم را نمی‌پوشانند، و درخواستِ یکسان
        # (همان عکس، همان گراف) همان نام و همان hash را می‌گیرد تا تکرارنشدنِ apps.compute کار کند —
        # نامِ تصادفیِ قبلی داخلِ گراف می‌نشست و هر درخواستی را «تازه» جلوه می‌داد
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        name = f"nm_{h.hexdigest()[:12]}_{path.name}"
        self._uploads[name] = str(path)
        return name

    def submit(self, workflow: dict) -> str:
        from apps.compute import services as compute
        from services.comfyui.client import ComfyUIError

        files = {}
        graph_text = _dumps(workflow)
        for name, src in self._uploads.items():
            if name in graph_text:
                files[name] = src
        try:
            job = compute.enqueue(
                "comfy.graph",
                {"graph": workflow, "uploads": sorted(files)},
                files,
                origin="comfyui",
                node=self.node,
                timeout_s=int(self.client.timeout),
            )
        except compute.ComputeUnavailable as exc:
            raise self.unavailable_error() from exc
        except compute.ComputeError as exc:
            raise ComfyUIError(str(exc)) from exc
        self._jobs[str(job.uid)] = job
        if job.state == "COMPLETED":
            logger.info("ComfyUI(remote): identical job already rendered — reusing %s", job.uid)
        return str(job.uid)

    def wait_for_output(self, prompt_id: str, timeout=None) -> dict:
        from django.core.exceptions import ValidationError

        from apps.compute import services as compute
        from apps.compute.models import ComputeJob
        from services.comfyui.client import ComfyUIError, ComfyUIJobFailed, ComfyUITimeout, ComfyUIUnavailable

        job = self._jobs.get(prompt_id)
        if job is None:
            try:
                job = ComputeJob.objects.get(uid=prompt_id)
            except (ComputeJob.DoesNotExist, ValueError, ValidationError):
                raise ComfyUIError(f"کارِ {prompt_id} در صفِ سرورهای پردازش نیست.")
        try:
            job = compute.wait(job, timeout_s=int(timeout or self.client.timeout), poll=self.client.poll_interval)
        except compute.ComputeTimeout as exc:
            raise ComfyUITimeout(str(exc)) from exc
        except compute.ComputeFailed as exc:
            msg = str(exc)
            low = msg.lower()
            if "comfyui" in low and ("در دسترس" in msg or "unavailable" in low or "refused" in low or "10061" in msg):
                # پیامِ حالتِ محلی («ComfyUI را روی این سیستم اجرا کنید / COMFYUI_BASE_URL») این‌جا دروغ بود:
                # ComfyUI روی خودِ سرورِ پردازش خاموش است، نه روی سرورِ سایت
                raise ComfyUIUnavailable(
                    f"ComfyUI روی سرورِ پردازشِ «{job.node.name if job.node else self.node or '?'}» پاسخ نداد — "
                    "روی همان سیستمِ گرافیکی ComfyUI را اجرا کنید (START.bat ِ بستهٔ UpMarket-Processing آن را بالا می‌آورد). "
                    f"جزئیات: {msg[:200]}"
                ) from exc
            raise ComfyUIJobFailed(f"ComfyUI روی سرورِ پردازش خطا داد: {msg}") from exc
        except compute.ComputeError as exc:
            raise ComfyUIError(str(exc)) from exc
        outputs = job.outputs()
        meta = (job.result or {}).get("meta") or {}
        primary = meta.get("primary")
        chosen = next((o for o in outputs if o["name"] == primary), None) if primary else None
        if chosen is None:
            chosen = (next((o for o in outputs if o.get("media") == "video"), None)
                      or next((o for o in outputs if o.get("media") == "image"), None))
        if chosen is None:
            raise ComfyUIJobFailed(
                f"ComfyUI job {prompt_id} completed but returned no video/image output "
                f"(outputs: {[o['name'] for o in outputs] or 'none'})"
            )
        return {"filename": chosen["name"], "subfolder": "", "type": "remote", "job": str(job.uid),
                "path": str(compute.output_path(job, chosen["name"]))}

    def download(self, output_info: dict, dest_dir, filename=None) -> Path:
        from services.comfyui.client import ComfyUIError

        src = Path(output_info.get("path") or "")
        if not src.is_file():
            raise ComfyUIError(f"خروجیِ سرورِ پردازش پیدا نشد: {output_info.get('filename')}")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        name = filename or f"{uuid.uuid4().hex}_{output_info['filename']}"
        local = dest / name
        shutil.copyfile(src, local)
        return local


def _dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)

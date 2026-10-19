"""Ollama روی سرورِ پردازش (agent://) — همان OllamaProvider، ولی درخواست به‌جای HTTP ِ مستقیم
به صفِ apps.compute می‌رود و گره‌ای که Ollama دارد آن را اجرا می‌کند (همان قراردادِ ComfyUI در
services/comfyui/remote.py).

    OLLAMA_BASE_URL=agent://any        هر سرورِ پردازشی که Ollama دارد
    OLLAMA_BASE_URL=agent://gpu-1      فقط گرهٔ gpu-1

سرورِ سایت Ollama ندارد و سرورِ پردازش IP ندارد؛ پس کار «ollama.generate» با بدنهٔ خودِ
Ollama (model/prompt/system/options/format/images) در صف می‌نشیند، گره آن را به
`/api/generate` ِ خودش می‌دهد و جوابِ JSON ِ Ollama را به نامِ `ollama.json` برمی‌گرداند
(processing-server/agent.py: h_ollama). تصویرها به‌صورتِ فایلِ ورودی می‌روند، نه base64 داخلِ
payload — گره خودش آن‌ها را base64 می‌کند.

اگر OLLAMA_BASE_URL هنوز نشانیِ محلی باشد ولی چیزی آن‌جا گوش ندهد و گره‌ای با Ollama ثبت شده
باشد، همین مسیر خودکار استفاده می‌شود: نصبی که فقط COMFYUI_BASE_URL را agent:// کرده، متن و
بینایی‌اش بی‌تنظیمِ اضافه روی همان گره می‌رود.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

SCHEME = "agent://"
JOB_KIND = "ollama.generate"
OUTPUT_NAME = "ollama.json"
POLL_SECONDS = 2.0


def is_agent_url(url: str) -> bool:
    return (url or "").startswith(SCHEME)


def node_name(url: str) -> str:
    """'agent://gpu-1' ⇐ 'gpu-1'؛ 'agent://any' یا 'agent://' ⇐ '' (هر گرهٔ توانا)."""
    name = (url or "")[len(SCHEME):].strip("/").strip()
    return "" if name in ("", "any", "*") else name


def _is_loopback(url: str) -> bool:
    from urllib.parse import urlparse

    host = urlparse(url if "//" in (url or "") else f"http://{url}").hostname or ""
    return host in {"127.0.0.1", "::1", "localhost"}


def ollama_nodes(url: str = "agent://any", online_only: bool = True) -> list:
    """گره‌هایی که Ollama دارند (و اگر خواسته شد، همین حالا آنلاین‌اند)."""
    try:
        from apps.compute import services as compute
        from apps.compute.models import ComputeNode
    except Exception:  # noqa: BLE001 — بی‌دیتابیس (ابزار/تست)
        return []
    try:
        if online_only:
            nodes = compute.online_nodes("ollama")
        else:
            nodes = [n for n in ComputeNode.objects.filter(enabled=True) if n.has("ollama")]
    except Exception as exc:  # noqa: BLE001 — جدول هنوز ساخته نشده (مهاجرتِ اول)
        logger.info("compute nodes unavailable (%s)", exc)
        return []
    wanted = node_name(url)
    return [n for n in nodes if not wanted or n.name == wanted]


def available(url: str = "agent://any") -> bool:
    return bool(ollama_nodes(url))


def use_remote(base_url: str) -> bool:
    """آیا این نشانی باید از راهِ صف برود؟

    * agent://…  ⇐ همیشه.
    * نشانیِ محلی که چیزی رویش گوش نمی‌دهد، در حالی که گره‌ای با Ollama ثبت شده ⇐ بله —
      سرورِ سایت Ollama ندارد و تنها جایی که مدل هست همان گره است.
    """
    if is_agent_url(base_url):
        return True
    if getattr(settings, "IS_TEST", False):
        return False
    if not _is_loopback(base_url):
        return False
    from services.net import is_listening

    if is_listening(base_url):
        return False
    return bool(ollama_nodes(online_only=False))


def effective_base_url(base_url: str) -> str:
    """نشانی‌ای که واقعاً استفاده می‌شود: agent://any وقتی مسیرِ صف انتخاب شده."""
    if is_agent_url(base_url):
        return base_url
    return "agent://any" if use_remote(base_url) else base_url


def installed_models(url: str = "agent://any") -> list[dict]:
    """مدل‌هایی که گره‌های آنلاینِ Ollama در heartbeat گزارش کرده‌اند — `[{"name", "size"}]`.

    اندازه را گره نمی‌فرستد (۰)؛ ترتیبِ خودِ گره نگه داشته می‌شود.
    """
    names: list[str] = []
    for node in ollama_nodes(url):
        for name in (node.capabilities or {}).get("ollama_models") or []:
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return [{"name": n, "size": 0} for n in names]


def unavailable_message(url: str = "agent://any") -> str:
    who = node_name(url)
    where = f"سرورِ پردازشِ «{who}»" if who else "هیچ سرورِ پردازشی با Ollama"
    return (
        f"{where} آنلاین نیست — روی سیستمِ گرافیکی START.bat ِ بستهٔ UpMarket-Processing را اجرا کنید "
        "(صفحهٔ «سرورهای پردازش» در پنل وضعیت را نشان می‌دهد). بدون سرورِ پردازش، مدلِ لوکال پاسخ نمی‌دهد."
    )


# ─── تصویرها: base64 یا مسیرِ فایل ⇐ فایلِ ورودیِ کار

def _sniff_ext(head: bytes) -> str:
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith(b"GIF8"):
        return ".gif"
    return ".bin"


def _materialize_images(images, tmp_dir: Path) -> dict[str, str]:
    """هر تصویر (base64، data:-URL یا مسیرِ فایل) ⇐ {نامِ ورودی: مسیرِ فایل}."""
    files: dict[str, str] = {}
    for index, image in enumerate(images or []):
        if isinstance(image, (bytes, bytearray)):
            raw = bytes(image)
        else:
            text = str(image)
            candidate = Path(text) if len(text) < 1024 else None
            if candidate is not None and candidate.is_file():
                raw = candidate.read_bytes()
            else:
                if text.startswith("data:") and "," in text:
                    text = text.split(",", 1)[1]
                try:
                    raw = base64.b64decode(text, validate=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"تصویرِ شمارهٔ {index + 1} نه فایل است نه base64: {exc}") from exc
        name = f"image_{index + 1}{_sniff_ext(raw[:16])}"
        path = tmp_dir / name
        path.write_bytes(raw)
        files[name] = str(path)
    return files


# ─── اجرای یک تولید از راهِ صف

def generate(payload: dict, *, base_url: str = "agent://any", timeout_s: int = 600,
             images=None, on_tick=None) -> dict:
    """کارِ ollama.generate را در صف می‌گذارد، منتظر می‌ماند و JSON ِ جوابِ Ollama را برمی‌گرداند.

    خطاها با همان خانوادهٔ OllamaError برمی‌گردند تا مسیرِ تکرار/تعمیر/ثبتِ شکست دست‌نخورده بماند.
    """
    from apps.compute import services as compute

    from .ollama import OllamaError, OllamaTimeout, OllamaUnavailable

    body = dict(payload)
    body.setdefault("stream", False)
    body.setdefault("path", "/api/generate")
    node = node_name(base_url)
    tmp_dir = Path(tempfile.mkdtemp(prefix="nm-ollama-"))
    try:
        files = _materialize_images(images, tmp_dir)
        if files:
            body["images"] = sorted(files)
        try:
            job = compute.enqueue(
                JOB_KIND, body, files, origin="ollama", node=node, timeout_s=int(timeout_s),
                # جوابِ مدل تصادفی است (temperature)؛ همان پرسش دوباره یعنی جوابِ تازه، نه رونوشتِ قبلی
                dedupe=False,
                # پاسخِ متنی تعاملی است (چت، کپشن)؛ پیش از رندرهای در صف گرفته شود (کمتر = زودتر)
                priority=50,
            )
        except compute.ComputeUnavailable as exc:
            raise OllamaUnavailable(unavailable_message(base_url)) from exc
        except compute.ComputeError as exc:
            raise OllamaError(f"ثبتِ کار در صفِ سرورهای پردازش ممکن نشد: {exc}") from exc
    finally:
        # نسخهٔ کار داخلِ پوشهٔ خودِ کار کپی شده؛ فایل‌های موقت لازم نیستند
        for p in tmp_dir.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    logger.info("ollama(remote): %s queued as %s (model=%s)", JOB_KIND, job.uid, body.get("model"))
    try:
        job = compute.wait(job, timeout_s=int(timeout_s), poll=POLL_SECONDS, on_tick=on_tick)
    except compute.ComputeTimeout as exc:
        raise OllamaTimeout(
            f"سرورِ پردازش در {int(timeout_s)} ثانیه جوابِ مدل {body.get('model')} را نداد."
        ) from exc
    except compute.ComputeFailed as exc:
        msg = str(exc)
        low = msg.lower()
        if "not reachable" in low or "در دسترس" in msg or "refused" in low or "10061" in msg:
            who = job.node.name if job.node else (node or "?")
            raise OllamaUnavailable(
                f"Ollama روی سرورِ پردازشِ «{who}» پاسخ نداد — روی همان سیستم Ollama را اجرا کنید "
                f"(START.bat ِ بستهٔ UpMarket-Processing). جزئیات: {msg[:200]}"
            ) from exc
        raise OllamaError(f"Ollama روی سرورِ پردازش خطا داد (model={body.get('model')}): {msg[:500]}") from exc
    except compute.ComputeCancelled as exc:
        raise OllamaError("کارِ مدل لغو شد.") from exc
    except compute.ComputeError as exc:
        raise OllamaError(str(exc)) from exc

    return read_answer(job)


def read_answer(job) -> dict:
    """جوابِ Ollama از خروجیِ کار (ollama.json)."""
    from apps.compute import services as compute

    from .ollama import OllamaError

    outputs = job.outputs()
    chosen = next((o for o in outputs if o.get("name") == OUTPUT_NAME), None) or next(
        (o for o in outputs if str(o.get("name", "")).endswith(".json")), None
    )
    if chosen is None:
        raise OllamaError(
            f"سرورِ پردازش کارِ {job.uid} را تمام کرد ولی جوابی ({OUTPUT_NAME}) برنگرداند "
            f"(خروجی‌ها: {[o.get('name') for o in outputs] or 'هیچ'})."
        )
    path = compute.output_path(job, chosen["name"])
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise OllamaError(f"جوابِ سرورِ پردازش خوانا نبود ({os.path.basename(str(path))}): {exc}") from exc
    if not isinstance(data, dict):
        raise OllamaError("جوابِ سرورِ پردازش ساختارِ Ollama را نداشت.")
    return data

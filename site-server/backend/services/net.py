"""
Fast "is this service even listening?" probe.

On Windows a refused HTTP connection to localhost costs several seconds
(IPv6 then IPv4). The AI stack touches Ollama and ComfyUI several times per
job, so a service that is simply switched off turned a job into 40 seconds of
apparent "loading" before the error appeared. A 1s TCP probe answers the
same question immediately, and the answer is cached briefly because these
services do not come and go mid-job.
"""
import socket
import time
from urllib.parse import urlparse

PROBE_TIMEOUT = 1.0
REMOTE_PROBE_TIMEOUT = 3.0
CACHE_SECONDS = 5.0

_cache: dict[str, tuple[float, bool]] = {}


def _endpoint(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url if "//" in base_url else f"http://{base_url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname or "localhost", port


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def is_listening(base_url: str, timeout: float | None = None, use_cache: bool = True) -> bool:
    """True when something accepts TCP connections at `base_url`. Never raises."""
    if (base_url or "").startswith("agent://"):
        # ComfyUI روی سرورِ پردازش (بی‌IP): «گوش می‌دهد» یعنی گره‌ای آنلاین است
        try:
            from services.comfyui import remote

            return bool(remote.comfy_nodes_online(base_url))
        except Exception:  # noqa: BLE001 — بدونِ دیتابیس (تست/ابزار) ساکت باش
            return False
    host, port = _endpoint(base_url or "")
    # a service on this machine answers instantly; one across the LAN deserves
    # more slack before we declare it missing
    if timeout is None:
        timeout = PROBE_TIMEOUT if _is_loopback(host) else REMOTE_PROBE_TIMEOUT
    key = f"{host}:{port}"
    now = time.monotonic()
    if use_cache:
        cached = _cache.get(key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    try:
        with socket.create_connection((host, port), timeout=timeout):
            up = True
    except OSError:
        up = False
    _cache[key] = (now, up)
    return up


def clear_cache() -> None:
    """Forget every probe result (tests, or right after starting a service)."""
    _cache.clear()

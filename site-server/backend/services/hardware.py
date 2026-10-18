"""What this machine actually is.

ROADMAP §8.5: "نباید بر اساس نام مدل یا حدس، ظرفیت را حساب کرد." The capacity
model currently rests on a remembered range of 3–9 minutes of render per second
of video, which is a 3× spread — wide enough that one end of it is a viable
business and the other is not.

This module answers the first half of that ("what hardware is this?"). The
second half — what the hardware actually achieves — is measured per render in
`apps.jobs.metrics`, because a specification sheet has never once predicted how
long Wan 2.2 takes on a particular card with a particular driver.

Every probe here degrades to `None` rather than guessing. A capacity model fed
a fabricated VRAM figure is worse than one that says "unknown", because the
first kind of wrong looks like an answer.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess

logger = logging.getLogger(__name__)

#: nvidia-smi occasionally hangs when a driver is mid-reset. A profile is
#: diagnostic information, never worth blocking a request for.
PROBE_TIMEOUT = 5


def _nvidia_smi(query: str) -> list[str]:
    """Run one nvidia-smi query, returning [] when anything is off."""
    binary = shutil.which("nvidia-smi")
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT, check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.info("nvidia-smi probe failed: %s", exc)
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _to_int(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def gpus() -> list[dict]:
    """One entry per CUDA device, empty when there is no NVIDIA GPU.

    Empty is a real answer: this is how the deployment stack runs on a VPS with
    the models reached over the network.
    """
    rows = _nvidia_smi("name,memory.total,memory.used,temperature.gpu,utilization.gpu")
    found = []
    for index, row in enumerate(rows):
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 5:
            continue
        total, used, temperature, utilisation = (_to_int(p) for p in parts[1:5])
        found.append({
            "index": index,
            "name": parts[0],
            "vram_total_mb": total,
            "vram_used_mb": used,
            "vram_free_mb": (total - used) if (total is not None and used is not None) else None,
            "temperature_c": temperature,
            "utilization_percent": utilisation,
        })
    return found


def vram_used_mb() -> int | None:
    """Total VRAM in use across all cards, for before/after measurement."""
    cards = gpus()
    values = [c["vram_used_mb"] for c in cards if c["vram_used_mb"] is not None]
    return sum(values) if values else None


def cpu_count() -> int:
    return os.cpu_count() or 1


def total_ram_mb() -> int | None:
    """Physical RAM, or None where we cannot ask without a new dependency.

    psutil would answer everywhere, and is not worth a dependency for a number
    that appears in a diagnostic report.
    """
    try:  # Linux / most containers
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size / (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        pass
    if platform.system() == "Windows":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys / (1024 * 1024))
        except Exception as exc:  # noqa: BLE001 — diagnostics only
            logger.debug("Could not read Windows memory status: %s", exc)
    return None


def fingerprint() -> str:
    """A short, stable name for "the machine these numbers came from".

    Measurements from a 3060 and a 4090 must not be averaged together, and the
    benchmark report groups by this string. It deliberately contains no serial
    number or hostname — it identifies a class of machine, not an installation.
    """
    cards = gpus()
    if cards:
        names = sorted({c["name"] for c in cards if c["name"]})
        gpu_part = "+".join(names) if names else "gpu"
        if len(cards) > 1:
            gpu_part = f"{len(cards)}x{gpu_part}"
    else:
        gpu_part = "no-gpu"
    return f"{gpu_part} · {cpu_count()}cpu · {platform.system()}"


def profile() -> dict:
    """Everything at once, for the admin page and the benchmark header."""
    cards = gpus()
    return {
        "fingerprint": fingerprint(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": cpu_count(),
        "ram_total_mb": total_ram_mb(),
        "gpus": cards,
        "gpu_count": len(cards),
        # Said plainly rather than implied by an empty list: this is the flag
        # that decides whether a render happens here or over the network.
        "has_gpu": bool(cards),
    }

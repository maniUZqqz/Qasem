"""فایل‌ها و ffmpeg ِ «فیلم‌برداریِ هدایت‌شده».

سرورِ سایت کوچک است (۲ هسته، ۳ گیگ): هر ffmpeg با `nice -n 10` و حداکثر ۲ نخ اجرا می‌شود تا سایت کند نشود،
و پیش از پذیرفتنِ ویدیو جای خالیِ دیسک وارسی می‌شود.
"""
from __future__ import annotations

import functools
import logging
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: کمتر از این جای خالی ⇐ ویدیوی تازه پذیرفته نمی‌شود (سایت و پایگاهِ داده هم جا لازم دارند)
MIN_FREE_BYTES = 1_200_000_000
#: سقفِ فضای یک جلسه
SESSION_MAX_BYTES = 1_500_000_000
FF_TIMEOUT = 900


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def abs_path(rel: str) -> Path:
    return media_root() / rel


def url(rel: str | None) -> str | None:
    if not rel:
        return None
    return settings.MEDIA_URL.rstrip("/") + "/" + rel.lstrip("/")


def dir_size(path: Path) -> int:
    total = 0
    if path.is_dir():
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    return total


def disk_free() -> int:
    try:
        return shutil.disk_usage(media_root()).free
    except OSError:
        return 0


def _nice() -> list[str]:
    return ["nice", "-n", "10"] if shutil.which("nice") else []


def run_ff(args: list, *, timeout: float = FF_TIMEOUT, probe: bool = False) -> subprocess.CompletedProcess:
    """ffmpeg (یا ffprobe) با اولویتِ پایین؛ خطا ⇐ VideoProcessingError با خلاصهٔ stderr."""
    from services.video.ffmpeg import FFMPEG, FFPROBE, VideoProcessingError, stderr_summary

    exe = FFPROBE if probe else FFMPEG
    cmd = _nice() + [exe, "-hide_banner"] + ([] if probe else ["-nostdin", "-threads", "2"]) + [str(a) for a in args]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                                stdin=subprocess.DEVNULL, timeout=timeout)
    except FileNotFoundError as exc:
        raise VideoProcessingError("ffmpeg روی سرور پیدا نشد.") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError(f"ffmpeg بیش از {int(timeout)} ثانیه طول کشید و متوقف شد.") from exc
    if result.returncode != 0:
        raise VideoProcessingError("ffmpeg ناموفق بود: " + (stderr_summary(result.stderr) or f"کد {result.returncode}"))
    return result


@functools.lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    from services.video.ffmpeg import FFMPEG

    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, encoding="utf-8",
                             errors="replace", timeout=20).stdout
    except Exception:  # noqa: BLE001
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


def capabilities() -> dict:
    return {
        "stabilize": has_filter("vidstabdetect") and has_filter("vidstabtransform"),
        "xfade": has_filter("xfade"),
        "ducking": has_filter("sidechaincompress"),
    }

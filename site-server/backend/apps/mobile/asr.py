"""Call audio -> text, through NM's existing AI routing.

Order follows the owner's setting (`services.ai.priority`): «اول لوکال» tries the processing node's `voice.asr`
(then the site's own Whisper) and falls back to Metis; «اول متیس» does the reverse. The Metis leg is customer audio
leaving our machines, so it goes through the store's data policy (CUSTOMER class) like every other external AI call.

Tests never reach a real engine: they replace `transcribe` (or the two legs) with fakes.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings as dj_settings

logger = logging.getLogger(__name__)


class AsrUnavailable(Exception):
    """No engine could transcribe; the message (Persian) is shown to the user."""


def _ffmpeg() -> str:
    return os.getenv("FFMPEG_BIN") or getattr(dj_settings, "FFMPEG_BIN", "") or "ffmpeg"


def to_wav(src: Path, dst: Path) -> None:
    try:
        subprocess.run([_ffmpeg(), "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "wav", str(dst)],
                       check=True, timeout=300, capture_output=True)
    except FileNotFoundError as exc:
        raise AsrUnavailable("ffmpeg روی سرور پیدا نشد.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AsrUnavailable("تبدیلِ قالبِ صدا زیادی طول کشید.") from exc
    except subprocess.CalledProcessError as exc:
        raise AsrUnavailable("فایلِ صدا خوانده نشد (خراب یا ناشناخته).") from exc


def segments_from_words(words, per=10) -> list[dict]:
    segs = []
    for i in range(0, len(words), per):
        chunk = words[i:i + per]
        segs.append({"start": round(float(chunk[0]["s"]), 2), "end": round(float(chunk[-1]["e"]), 2),
                     "text": " ".join(w["w"] for w in chunk)})
    return segs


def _local(path: Path, store) -> dict:
    from services.editing import captions

    with tempfile.TemporaryDirectory(prefix="nm-mobile-asr-") as tmp:
        wav = Path(tmp) / "audio.wav"
        to_wav(path, wav)
        try:
            result = captions.transcribe_wav(wav, store=store, timeout_s=900)
        except captions.CaptionsUnavailable as exc:
            raise AsrUnavailable(str(exc)) from exc
    words = result.get("words") or []
    return {"text": result.get("text") or " ".join(w["w"] for w in words), "segments": segments_from_words(words),
            "engine": result.get("engine") or "node"}


def _metis(path: Path, store) -> dict:
    import requests

    from services.ai import gateway, priority, providers

    if store is not None:
        policy = gateway.policy_for(store)
        if policy.mode == gateway.LOCAL_ONLY or not policy.allow_customer_data_external:
            raise AsrUnavailable("سیاستِ دادهٔ فروشگاه اجازه نمی‌دهد صدای مشتری به سرویسِ بیرونی (متیس) برود.")
    if not priority.metis_configured():
        raise AsrUnavailable("متیس تنظیم نشده است.")
    blocked = priority.open_failure(priority.METIS)
    if blocked:
        raise AsrUnavailable("متیس موقتاً کنار گذاشته شده (" + str(blocked.get("message") or "خطای قبلی") + ").")
    api = providers._api_default(providers.TEXT)
    url = api.base_url.rstrip("/") + "/audio/transcriptions"
    model = os.getenv("MOBILE_ASR_METIS_MODEL", "whisper-1")
    with tempfile.TemporaryDirectory(prefix="nm-mobile-asr-") as tmp:
        wav = Path(tmp) / "audio.mp3"
        # a compact mono mp3 keeps the upload small and is accepted by every OpenAI-compatible ASR
        try:
            subprocess.run([_ffmpeg(), "-y", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-b:a", "48k", str(wav)],
                           check=True, timeout=300, capture_output=True)
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise AsrUnavailable("تبدیلِ قالبِ صدا برای متیس ممکن نشد.") from exc
        try:
            with open(wav, "rb") as fh:
                resp = requests.post(url, headers={"Authorization": f"Bearer {api.api_key}"},
                                     files={"file": ("call.mp3", fh, "audio/mpeg")},
                                     data={"model": model, "language": "fa", "response_format": "verbose_json"}, timeout=300)
        except requests.RequestException as exc:
            raise AsrUnavailable("اتصال به متیس برقرار نشد.") from exc
    if resp.status_code == 402:
        raise AsrUnavailable("اعتبارِ متیس تمام شده است (۴۰۲).")
    if resp.status_code in (401, 403):
        raise AsrUnavailable("کلیدِ متیس پذیرفته نشد.")
    if resp.status_code == 404:
        raise AsrUnavailable("متیس این مدلِ تبدیلِ گفتار را ندارد.")
    if resp.status_code >= 400:
        raise AsrUnavailable(f"متیس خطا داد ({resp.status_code}).")
    try:
        data = resp.json()
    except ValueError as exc:
        raise AsrUnavailable("پاسخِ متیس خوانده نشد.") from exc
    segments = [{"start": round(float(s.get("start", 0)), 2), "end": round(float(s.get("end", 0)), 2),
                 "text": str(s.get("text", "")).strip()} for s in (data.get("segments") or []) if isinstance(s, dict)]
    return {"text": str(data.get("text") or " ".join(s["text"] for s in segments)).strip(), "segments": segments, "engine": "metis"}


def order() -> list[str]:
    from services.ai import priority

    try:
        cfg = priority.config()
        return [priority.METIS, priority.LOCAL] if cfg.priority == priority.METIS_FIRST else [priority.LOCAL, priority.METIS]
    except Exception:  # noqa: BLE001
        return [priority.LOCAL, priority.METIS]


def transcribe(path, store=None) -> dict:
    """{"text", "segments", "engine": "node|local|metis"}. Raises AsrUnavailable with every reason joined."""
    from services.ai import priority

    path = Path(path)
    errors = []
    for provider in order():
        try:
            return _metis(path, store) if provider == priority.METIS else _local(path, store)
        except AsrUnavailable as exc:
            errors.append(f"{priority.PROVIDER_LABEL.get(provider, provider)}: {exc}")
    raise AsrUnavailable("؛ ".join(errors) or "هیچ موتورِ تبدیلِ گفتار در دسترس نیست.")

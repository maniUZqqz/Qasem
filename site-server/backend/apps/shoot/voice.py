"""صدای راهنمای فیلم‌برداری و گویندهٔ تبلیغ، با همان موتورِ گفتارِ سایت (services.audio.tts: Edge/Piper/…).

هر جمله یک بار ساخته و با «موتور + صدا + متن» نشانه‌گذاری می‌شود (media/shoot/voice/<hash>.mp3)، پس «شروع» و
«سه، دو، یک» در همهٔ جلسه‌ها یکی است و دوباره ساخته نمی‌شود. خروجیِ هر موتور به mp3 ِ کوچکِ تک‌کاناله تبدیل
می‌شود تا هر مرورگری پخشش کند.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from . import media

logger = logging.getLogger(__name__)

FIXED_CUES = ["سه", "دو", "یک", "عکس گرفته شد", "ضبط تمام شد", "عالی! بعدی", "بهتر است دوباره بگیری"]
MAX_CUES = 80


def cue_texts(plan: dict) -> list[str]:
    out: list[str] = []

    def add(t):
        t = (t or "").strip()
        if t and t not in out:
            out.append(t)

    for t in FIXED_CUES:
        add(t)
    for shot in plan.get("photos") or []:
        add(shot.get("instruction"))
    for shot in plan.get("video") or []:
        add(shot.get("instruction"))
        for cue in shot.get("cues") or []:
            add(cue.get("text"))
    return out[:MAX_CUES]


def _provider(store):
    from services.audio import tts

    return tts.get_tts_provider("fa", store)


def _voice_id(provider) -> str:
    return f"{getattr(provider, 'name', '')}:{getattr(provider, 'voice', '')}"


def synthesize_to(provider, text: str, out_mp3: Path) -> Path:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    raw = out_mp3.with_name(out_mp3.stem + "_raw.mp3")
    made = Path(provider.synthesize(text, raw) or raw)
    try:
        media.run_ff(["-y", "-i", made, "-ac", "1", "-ar", "24000", "-b:a", "64k", out_mp3], timeout=120)
    finally:
        for p in {raw, made}:
            if p != out_mp3:
                p.unlink(missing_ok=True)
    return out_mp3


def build_cues(session) -> dict:
    """همهٔ جمله‌های راهنمای یک برنامه ⇐ {"state", "clips": {متن: آدرس}, "engine", "failed"}."""
    try:
        provider = _provider(session.store)
    except Exception as exc:  # noqa: BLE001
        return {"state": "FAILED", "clips": {}, "error": f"موتورِ گفتار آماده نیست: {exc}"[:300]}
    vid = _voice_id(provider)
    clips, failed, last_error = {}, 0, ""
    for text in cue_texts(session.plan):
        key = hashlib.sha1(f"{vid}|{text}".encode("utf-8")).hexdigest()[:24]
        rel = f"shoot/voice/{key}.mp3"
        path = media.abs_path(rel)
        if not path.is_file():
            try:
                synthesize_to(provider, text, path)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                last_error = str(exc)[:200]
                logger.info("shoot: cue synthesis failed (%s): %s", text[:30], exc)
                if failed >= 3 and not clips:
                    break
                continue
        clips[text] = media.url(rel)
    engine = getattr(provider, "processor", "") or getattr(provider, "name", "")
    if not clips:
        return {"state": "FAILED", "clips": {}, "engine": engine,
                "error": ("گفتار ساخته نشد: " + last_error)[:300]}
    return {"state": "READY", "clips": clips, "engine": engine, "failed": failed}


def voiceover(store, text: str, out_mp3: Path) -> tuple[Path, str]:
    provider = _provider(store)
    synthesize_to(provider, text, out_mp3)
    return out_mp3, (getattr(provider, "processor", "") or getattr(provider, "name", ""))

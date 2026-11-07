"""Caption translation for the manual editor: the lines of a caption track go to the shop's text model (the processing server's Qwen when it is
online, else the paid API — `services.ai.gateway.text_provider` decides) in small batches, and come back in the same order and count.

Nothing here touches the clips: the panel puts the translated lines on a new caption track (or over the old ones) and the shop can undo it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: key → (Persian name, English name for the prompt)
LANGS: dict[str, tuple[str, str]] = {
    "fa": ("فارسی", "Persian (Farsi)"), "en": ("انگلیسی", "English"), "ar": ("عربی", "Arabic"), "tr": ("ترکی استانبولی", "Turkish"),
    "ru": ("روسی", "Russian"), "de": ("آلمانی", "German"), "fr": ("فرانسوی", "French"), "es": ("اسپانیایی", "Spanish"),
    "it": ("ایتالیایی", "Italian"), "zh": ("چینی", "Chinese (Simplified)"), "hi": ("هندی", "Hindi"), "ur": ("اردو", "Urdu"),
}
BATCH = 25
MAX_ITEMS = 300
MAX_CHARS = 400

SYSTEM = (
    "You are a professional subtitle translator. Translate every caption line into {lang}. "
    "Keep the meaning, the tone and any numbers, product names and brand names. Keep each line about as short as the original so it can be read on screen. "
    "Never merge, split, skip or add lines and never add notes or explanations. "
    'Reply with JSON only: {{"items": ["line 1 translated", "line 2 translated", ...]}} — exactly {n} strings, in the same order as the input.'
)


class TranslateError(Exception):
    """The model answered, but not usably (wrong count, not text)."""


def clean_items(raw) -> list[dict]:
    """The panel's `[{id, text}]` → validated list; raises ValueError with a Persian sentence."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("زیرنویسی برای ترجمه فرستاده نشده است.")
    if len(raw) > MAX_ITEMS:
        raise ValueError(f"در هر بار حداکثر {MAX_ITEMS} خطِ زیرنویس ترجمه می‌شود.")
    out = []
    for it in raw:
        if not isinstance(it, dict):
            raise ValueError("فهرستِ زیرنویس درست نیست.")
        text = str(it.get("text") or "").strip()
        cid = str(it.get("id") or "")[:64]
        if not cid:
            raise ValueError("یکی از خط‌ها شناسه ندارد.")
        if not text:
            continue
        out.append({"id": cid, "text": text[:MAX_CHARS]})
    if not out:
        raise ValueError("همهٔ خط‌های زیرنویس خالی‌اند.")
    return out


def _ask(store, job, system: str, prompt: str, n: int):
    """One model call; patched in tests (no real credit). Returns the parsed JSON."""
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai.gateway import text_provider
    from services.ai.router import TASK_REASONING, models_for

    provider = text_provider(store)
    parsed, _ = recorded_json_call(
        job=job, store=store, task_type=AIRequest.TaskType.REASONING, prompt_id="caption_translate", prompt_version="1", provider=provider,
        models=models_for(TASK_REASONING), prompt=prompt, system=system,
        validate=lambda p: (isinstance((p or {}).get("items"), list) and len(p["items"]) == n and all(isinstance(x, str) for x in p["items"]),
                            [f"items باید دقیقاً {n} رشته باشد"]),
        validation_message="مدل ترجمهٔ هم‌تعداد برنگرداند",
    )
    return parsed


def translate(items: list[dict], lang: str, *, store=None, job=None, progress=None, ask=None) -> list[dict]:
    """[{id, text}] → [{id, text}] in the target language. `progress(done, total)` after each batch."""
    if lang not in LANGS:
        raise ValueError("این زبان پشتیبانی نمی‌شود.")
    ask = ask or _ask
    out: list[dict] = []
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    for k, chunk in enumerate(batches):
        prompt = "Caption lines:\n" + "\n".join(f"{i + 1}. {c['text'].replace(chr(10), ' / ')}" for i, c in enumerate(chunk))
        parsed = ask(store, job, SYSTEM.format(lang=LANGS[lang][1], n=len(chunk)), prompt, len(chunk))
        got = (parsed or {}).get("items") if isinstance(parsed, dict) else None
        if not isinstance(got, list) or len(got) != len(chunk) or not all(isinstance(x, str) for x in got):
            raise TranslateError("هوش مصنوعی ترجمهٔ هم‌تعداد برنگرداند.")
        for c, text in zip(chunk, got):
            out.append({"id": c["id"], "text": text.strip()[:MAX_CHARS * 2].replace(" / ", "\n") if "\n" in c["text"] else text.strip()[:MAX_CHARS * 2]})
        if progress:
            progress(k + 1, len(batches))
    return out

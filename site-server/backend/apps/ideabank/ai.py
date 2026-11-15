"""مسیرِ هوش مصنوعیِ «ایده بساز»: همان مسیریابِ پروژه (Ollama روی سرورِ پردازش ⇐ متیس، به ترتیبِ تنظیمِ مالک).

هر شکستی (متیسِ بی‌اعتبار ۴۰۲، گرهٔ خاموش، سیاستِ داده، پیکربندی) به ``AIUnavailable`` با یک جملهٔ فارسی تبدیل می‌شود و ایده‌ساز به فرمول‌های آماده
برمی‌گردد؛ بار بعدی که هوش مصنوعی برگشت همین مسیر دوباره امتحان می‌شود (چیزی «قفل» نمی‌شود). زیرِ آزمون هیچ‌وقت شبکه صدا زده نمی‌شود.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

AI_TIMEOUT = 150
PROMPT_ID = "ideabank_ideas"


class AIUnavailable(RuntimeError):
    """هوش مصنوعی جواب نداد؛ متنِ فارسی برای کاربر."""


def reason_text(exc: Exception, fallback: str = "") -> str:
    """خطای مسیریاب ⇒ یک جملهٔ کوتاهِ فارسی («سرورِ پردازش خاموش است؛ متیس: اعتبار تمام شده»)."""
    try:
        from apps.photoedit import translate
        from apps.thumbs import hooks

        return hooks.reason_from_exception(exc, fallback or translate.explain(exc))
    except Exception:  # noqa: BLE001 — فقط برای زیباییِ پیام
        text = (fallback or str(exc) or exc.__class__.__name__).strip()
        if "402" in text or "credit" in text.lower() or "insufficient" in text.lower():
            return "اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)"
        return text[:240]


def _short(text: str, limit: int = 170) -> str:
    """دلیلِ بلندِ مسیریاب ⇒ یک یا دو جملهٔ کوتاه و بی‌نقطهٔ اضافه (برای نمایش در بالای صفحه)."""
    t = str(text or "").replace(".؛", "؛").replace("؛.", "؛").strip(" .؛")
    try:
        from apps.thumbs import hooks

        t = hooks.fit_text(t, limit)
    except Exception:  # noqa: BLE001
        t = t[:limit]
    return t.strip(" .؛")


def default_ask(store, prompt: str, system: str) -> tuple[dict, dict]:
    """⇒ (JSON، {label}). هر شکستی ⇒ AIUnavailable(دلیلِ فارسی)."""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        raise AIUnavailable("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from apps.photoedit import translate
        from services.ai import gateway
        from services.ai.priority import TEXT
        from services.ai.router import TASK_REASONING, models_for

        provider = gateway.text_provider(store, kind=TEXT)
        parsed, _row = recorded_json_call(
            store=store, task_type=AIRequest.TaskType.REASONING, prompt_id=PROMPT_ID, prompt_version="1", provider=provider,
            models=models_for(TASK_REASONING), prompt=prompt, system=system,
            validate=lambda d: (isinstance(d, dict) and isinstance(d.get("ideas"), list) and bool(d["ideas"]), ["ideas خالی است"]),
            validation_message="ایده‌ها ناقص بود")
        info = translate._describe(provider)
    except Exception as exc:  # noqa: BLE001 — متیسِ بی‌اعتبار (۴۰۲)، گرهٔ خاموش، سیاستِ داده، پیکربندی…
        raise AIUnavailable(reason_text(exc)) from exc
    return parsed, (info or {})


def status(store) -> tuple[bool, str]:
    """(هوش مصنوعی الان قابل‌استفاده است؟، چرا) — از پایگاه‌داده تصمیم می‌گیرد، به شبکه یا گره درخواست نمی‌زند (۶۰ ثانیه کَش)."""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        return False, "زیرِ آزمون هوشِ مصنوعی صدا زده نمی‌شود."
    try:
        from django.core.cache import cache

        key = f"ideabank-ai-status:{getattr(store, 'pk', 0)}"
        cached = cache.get(key)
        if cached is not None:
            return bool(cached[0]), str(cached[1])
        from services.ai import factory, gateway, providers, routing

        provider = gateway.text_provider(store, kind=routing.TEXT)
        if isinstance(provider, routing.RoutedTextProvider):
            ok, note = provider.availability()
        else:
            ok, note = factory.health(gateway.resolve(providers.TEXT, store))
        result = (bool(ok), _short(reason_text(RuntimeError(str(note)), str(note))) if not ok else str(note)[:200])
        cache.set(key, list(result), 60)
        return result
    except Exception as exc:  # noqa: BLE001 — «در دسترس نیست» خودش جواب است
        return False, reason_text(exc)

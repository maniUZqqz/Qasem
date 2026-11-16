"""مسیرِ هوش مصنوعیِ «ایده بساز»: همان مسیریابِ پروژه (Ollama روی سرورِ پردازش ⇐ متیس، به ترتیبِ تنظیمِ مالک).

هر شکستی (متیسِ بی‌اعتبار ۴۰۲، گرهٔ خاموش، سیاستِ داده، پیکربندی) به ``AIUnavailable`` با یک جملهٔ فارسی تبدیل می‌شود و ایده‌ساز به فرمول‌های آماده
برمی‌گردد؛ بار بعدی که هوش مصنوعی برگشت همین مسیر دوباره امتحان می‌شود (چیزی «قفل» نمی‌شود). زیرِ آزمون هیچ‌وقت شبکه صدا زده نمی‌شود.
"""
from __future__ import annotations

import logging
import threading
from apps.brandchar.inject import with_persona

logger = logging.getLogger(__name__)

#: «ایده بساز» هیچ‌وقت بیش از این منتظرِ هوش مصنوعی نمی‌ماند؛ بعدش فرمول‌های آماده جواب می‌دهند. مسیریاب اگر فقط لوکال مجاز باشد تا ۹۰۰ ثانیه برای
#: نوبتِ سرورِ پردازش و تا ۷ دقیقه برای اجرا صبر می‌کند (کارِ ویدیو و رندر هم همان‌جاست)؛ برای یک دکمهٔ تعاملی این خیلی طولانی است.
AI_TIMEOUT = 150
PROMPT_ID = "ideabank_ideas"
_inflight: dict = {}
_inflight_lock = threading.Lock()


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


def run_bounded(key, fn, timeout: float | None = None):
    """``fn()`` را با سقفِ زمان اجرا می‌کند؛ بعد از سقف ``AIUnavailable`` می‌دهد و درخواست به فرمول‌های آماده می‌رود.

    کارِ مسیریاب در یک رشتهٔ جدا می‌ماند (نمی‌شود وسطش قطعش کرد) و خودش تمام یا لغو می‌شود؛ تا آن موقع درخواستِ دوباره برای همان فروشگاه
    کارِ تازه به صف نمی‌اندازد (وگرنه چند کلیکِ پشتِ‌هم گره را با کارهایی که کسی نتیجه‌شان را نمی‌خواهد پر می‌کرد)."""
    wait = AI_TIMEOUT if timeout is None else timeout
    box: dict = {}
    with _inflight_lock:
        prev = _inflight.get(key)
        if prev is not None and prev.is_alive():
            raise AIUnavailable("درخواستِ قبلیِ «ایده بساز» هنوز در صفِ سرورِ پردازش است؛ چند دقیقه بعد دوباره امتحان کنید.")

        def work():
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 — به رشتهٔ درخواست پس داده می‌شود
                box["error"] = exc
            finally:
                try:
                    from django.db import connection

                    connection.close()                       # هر رشته اتصالِ خودش را دارد
                except Exception:  # noqa: BLE001
                    pass

        worker = threading.Thread(target=work, name=f"ideabank-ai-{key}", daemon=True)
        _inflight[key] = worker
        worker.start()
    worker.join(wait)
    if worker.is_alive():
        raise AIUnavailable(f"سرورِ پردازش در {int(wait)} ثانیه جواب نداد (احتمالاً سرگرمِ کارِ دیگری است)")
    with _inflight_lock:
        if _inflight.get(key) is worker:
            del _inflight[key]
    if "error" in box:
        raise box["error"]
    return box["value"]


def default_ask(store, prompt: str, system: str) -> tuple[dict, dict]:
    """⇒ (JSON، {label}). هر شکستی ⇒ AIUnavailable(دلیلِ فارسی). حداکثر ``AI_TIMEOUT`` ثانیه صبر می‌کند."""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        raise AIUnavailable("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    try:
        return run_bounded(getattr(store, "pk", 0) or 0, lambda: _ask_router(store, prompt, system))
    except AIUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — متیسِ بی‌اعتبار (۴۰۲)، گرهٔ خاموش، سیاستِ داده، پیکربندی…
        raise AIUnavailable(reason_text(exc)) from exc


def _ask_router(store, prompt: str, system: str) -> tuple[dict, dict]:
    """همان مسیریابِ پروژه (لوکال روی گره ⇒ متیس)؛ در رشتهٔ جدا و زیرِ سقفِ ``run_bounded`` صدا زده می‌شود."""
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
            models=models_for(TASK_REASONING), prompt=prompt, system=with_persona(store, system, "ideas"),
            validate=lambda d: (isinstance(d, dict) and isinstance(d.get("ideas"), list) and bool(d["ideas"]), ["ideas خالی است"]),
            validation_message="ایده‌ها ناقص بود")
        info = translate._describe(provider)
    except Exception as exc:  # noqa: BLE001
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

"""هوش مصنوعیِ استودیوی طراحی: همان مسیریابِ پروژه (Ollama روی سرورِ پردازش ⇐ متیس) با بازگشتِ قاعده‌ای.

هر شکستی (متیسِ بی‌اعتبار ۴۰۲، گرهٔ خاموش، سیاستِ داده) به ``AIUnavailable`` با یک جملهٔ فارسی تبدیل می‌شود و پیش‌نویس با قاعده‌ها ساخته می‌شود؛
وقتی هوش مصنوعی برگشت همان مسیر دوباره امتحان می‌شود (چیزی قفل نمی‌شود). زیرِ آزمون هرگز شبکه صدا زده نمی‌شود.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

PROMPT_ID = "design_studio_draft"
AI_TIMEOUT = 150

try:  # همان کمک‌های «بانکِ ایده» (در همین نسخه هست)؛ اگر نبود نسخهٔ کوچکِ خودمان
    from apps.ideabank.ai import AIUnavailable, reason_text, run_bounded, status as _ib_status
except Exception:  # noqa: BLE001 — pragma: no cover
    class AIUnavailable(RuntimeError):
        pass

    def reason_text(exc, fallback=""):
        return (fallback or str(exc) or exc.__class__.__name__)[:240]

    def run_bounded(key, fn, timeout=None):
        return fn()

    _ib_status = None

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json(text: str):
    t = _FENCE.sub("", str(text or "").strip())
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def default_ask(store, prompt: str, system: str, validate=None) -> tuple[dict, dict]:
    """⇒ (JSON، {label}). هر شکستی ⇒ AIUnavailable(دلیلِ فارسی)."""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        raise AIUnavailable("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    try:
        return run_bounded(("design", getattr(store, "pk", 0) or 0), lambda: _ask_router(store, prompt, system, validate), AI_TIMEOUT)
    except AIUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailable(reason_text(exc)) from exc


def _ask_router(store, prompt: str, system: str, validate=None) -> tuple[dict, dict]:
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from apps.photoedit import translate
        from services.ai import gateway
        from services.ai.priority import TEXT
        from services.ai.router import TASK_REASONING, models_for

        provider = gateway.text_provider(store, kind=TEXT)
        parsed, _row = recorded_json_call(
            store=store, task_type=AIRequest.TaskType.REASONING, prompt_id=PROMPT_ID, prompt_version="1", provider=provider, models=models_for(TASK_REASONING),
            prompt=prompt, system=system, validate=validate or (lambda d: (isinstance(d, dict) and bool(d), ["پاسخ خالی است"])), validation_message="پاسخِ مدل ناقص بود")
        info = translate._describe(provider)
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailable(reason_text(exc)) from exc
    return parsed, (info or {})


def status(store) -> tuple[bool, str]:
    if _ib_status is None:
        return False, "وضعیتِ هوش مصنوعی در دسترس نیست."
    try:
        return _ib_status(store)
    except Exception as exc:  # noqa: BLE001
        return False, reason_text(exc)

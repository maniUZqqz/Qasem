"""AI summary and next-step notes for a transcribed call, and quick replies for the in-call assistant.

It reports; it does not decide (same principle as `services/research/call_analysis.py`): the notes land on the call as
suggestions for a person. Customer data class: the store's data policy decides whether a transcript may leave the machine.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SENTIMENTS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}
HEAD_CHARS, TAIL_CHARS = 6000, 4000


class NotesUnavailable(Exception):
    pass


def resolve_store(user=None, device=None):
    """The store the AI call is audited against: the device's, the panel default, the user's, else the first one."""
    from apps.stores.models import Store

    from .models import MobileSettings

    s = MobileSettings.get()
    if s.default_store_id:
        return s.default_store
    if user is not None and getattr(user, "is_authenticated", False):
        from apps.stores import access

        st = access.stores_for(user).first()
        if st:
            return st
    return Store.objects.order_by("id").first()


def _trim(text: str) -> str:
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text
    return text[:HEAD_CHARS] + "\n\n[… میانهٔ تماس کوتاه شده …]\n\n" + text[-TAIL_CHARS:]


def _lines(value, limit=8):
    if isinstance(value, str):
        value = [value]
    out = []
    for item in (value or [])[:limit]:
        t = str(item).strip()[:300]
        if t:
            out.append(t)
    return out


CALL_SYSTEM = ("تو دستیار یک بازاریاب تلفنی هستی. متن پیاده‌شدهٔ یک تماس را می‌خوانی و فقط چیزی را گزارش می‌کنی که در خودِ "
               "متن هست. حدس نزن و چیزی اضافه نکن. اگر چیزی گفته نشده، فهرستش را خالی بگذار.")
CALL_TEMPLATE = """متنِ پیاده‌شدهٔ تماس {direction} با «{who}»:

---
{transcript}
---

یک JSON بده با این کلیدها:
- "summary": خلاصهٔ تماس در حداکثر سه جمله.
- "objections": فهرستِ مخالفت‌ها یا نگرانی‌هایی که طرفِ مقابل گفت (هر کدام یک جمله).
- "commitments": فهرستِ قول‌هایی که داده شد، از هر دو طرف (هر کدام یک جمله).
- "next_steps": فهرستِ قدم‌های بعدیِ پیشنهادی (حداکثر ۴، هر کدام یک جمله).
- "sentiment": یکی از "POSITIVE"، "NEUTRAL"، "NEGATIVE".
فقط JSON بده."""


def _valid(parsed):
    problems = []
    if not isinstance(parsed, dict):
        return False, ["خروجی JSON نبود"]
    if not str(parsed.get("summary", "")).strip():
        problems.append("خلاصه خالی است")
    for key in ("objections", "commitments", "next_steps"):
        if key in parsed and not isinstance(parsed.get(key), (list, str)):
            problems.append(f"«{key}» فهرست نیست")
    if parsed.get("sentiment") and str(parsed["sentiment"]).upper() not in SENTIMENTS:
        problems.append("sentiment مجاز نیست")
    return not problems, problems


def analyse(call) -> dict:
    """-> {"summary","sentiment","objections","commitments","next_steps"}; raises NotesUnavailable."""
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai import gateway
    from services.ai.gateway import text_provider
    from services.ai.priority import RESEARCH
    from services.ai.router import TASK_RESEARCH, models_for

    store = resolve_store(call.user)
    if store is None:
        raise NotesUnavailable("هیچ فروشگاهی تعریف نشده تا درخواستِ هوش مصنوعی به نامش ثبت شود.")
    direction = {"in": "ورودی", "out": "خروجی"}.get(call.direction, "")
    try:
        parsed, _ = recorded_json_call(
            store=store, task_type=AIRequest.TaskType.REASONING, prompt_id="mobile_call_notes", prompt_version="1",
            provider=text_provider(store, gateway.CUSTOMER, kind=RESEARCH), models=models_for(TASK_RESEARCH), system=CALL_SYSTEM,
            prompt=CALL_TEMPLATE.format(direction=direction, who=call.caller_label or call.contact_name or call.number,
                                        transcript=_trim(call.transcript)),
            validate=_valid, validation_message="یادداشتِ تماس ناقص بود")
    except Exception as exc:  # noqa: BLE001
        raise NotesUnavailable(str(exc)[:300]) from exc
    sentiment = str(parsed.get("sentiment", "")).upper()
    return {"summary": str(parsed.get("summary", "")).strip()[:2000], "sentiment": sentiment if sentiment in SENTIMENTS else "",
            "objections": _lines(parsed.get("objections")), "commitments": _lines(parsed.get("commitments")),
            "next_steps": _lines(parsed.get("next_steps"), 4)}


# ------------------------------------------------------------------ assistant quick replies

ASK_SYSTEM = (
    "تو دستیارِ لحظه‌ای یک بازاریابِ تلفنی هستی که همین الان پای تلفن است. فقط از «حقایقِ داده‌شده» استفاده کن؛ اگر چیزی در "
    "حقایق نیست بگو «ثبت نشده» و حدس نزن. قیمت‌ها و موجودی را همان‌طور که هست بگو. هرگز بهای تمام‌شده یا سودِ فروشگاه را به "
    "مشتری نگو؛ «کفِ قیمت» یک حدِ داخلی است برای اینکه بازاریاب بداند تا کجا می‌تواند تخفیف بدهد، نه چیزی که به مشتری گفته شود. "
    "جواب‌ها کوتاه، محترمانه و فارسی باشند (هر کدام حداکثر دو جمله)."
)


def ask_prompt(question: str, facts: dict) -> str:
    import json

    return ("حقایقِ داده‌شده (JSON):\n" + json.dumps(facts, ensure_ascii=False, default=str) + "\n\nسؤال/وضعیتِ مشتری: " + question +
            '\n\nیک JSON بده با کلیدهای: "replies": فهرستِ ۱ تا ۳ جملهٔ پیشنهادی که بازاریاب می‌تواند بگوید (رشته)، '
            '"notes": یک جمله یادداشتِ داخلی برای خودِ بازاریاب (مثلاً تا چه حد می‌تواند تخفیف بدهد). فقط JSON.')


def ask_valid(parsed):
    if not isinstance(parsed, dict) or not isinstance(parsed.get("replies"), list) or not parsed["replies"]:
        return False, ["replies فهرستِ غیرخالی نیست"]
    return True, []


def quick_replies(user, question: str, facts: dict) -> dict:
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai import gateway
    from services.ai.gateway import text_provider
    from services.ai.priority import TEXT
    from services.ai.router import TASK_REASONING, models_for

    store = resolve_store(user)
    if store is None:
        raise NotesUnavailable("هیچ فروشگاهی تعریف نشده است.")
    try:
        parsed, row = recorded_json_call(
            store=store, task_type=AIRequest.TaskType.REASONING, prompt_id="mobile_quick_reply", prompt_version="1",
            provider=text_provider(store, gateway.CUSTOMER, kind=TEXT), models=models_for(TASK_REASONING), system=ASK_SYSTEM,
            prompt=ask_prompt(question, facts), validate=ask_valid, validation_message="پاسخِ دستیار ناقص بود")
    except gateway.PolicyBlocked as exc:
        raise NotesUnavailable(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise NotesUnavailable(str(exc)[:300]) from exc
    replies = [{"text": str(r).strip()[:400]} for r in parsed.get("replies", []) if str(r).strip()][:3]
    engine = getattr(row, "via", "") or ""
    return {"replies": replies, "notes": str(parsed.get("notes", "")).strip()[:400], "engine": engine}

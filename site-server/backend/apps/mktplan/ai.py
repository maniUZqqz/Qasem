"""پولیشِ متنِ پیش‌نویس‌ها با هوش مصنوعی — به ترتیبِ تنظیمِ مالک: اول گرهٔ پردازش (Ollama روی GPU)، بعد متیس.

همان مسیریابِ بانکِ ایده (``apps.ideabank.ai``): هر شکستی (متیسِ بی‌اعتبار ۴۰۲، گرهٔ خاموش، سیاستِ داده) یک جملهٔ فارسی می‌شود و پیش‌نویسِ قاعده‌محور
همان‌طور می‌ماند؛ کار «منتظرِ هوش مصنوعی» (``ai_wait``) علامت می‌خورد و تیکِ پس‌زمینه بعداً، وقتی گره یا متیس برگشت، دوباره امتحان می‌کند.
زیرِ آزمون هیچ‌وقت شبکه صدا زده نمی‌شود.
"""
from __future__ import annotations

import json
import logging
import re

from apps.ideabank import ai as idea_ai

from . import drafts

logger = logging.getLogger(__name__)

PROMPT_ID = "mktplan_polish"
SYSTEM = (
    "You are a senior Persian marketing copywriter. Rewrite the given DRAFT in natural, warm, concise Persian (fa) in the brand voice described. "
    "Keep every [bracket slot] exactly as is. NEVER invent prices, discounts, percentages, statistics, results, guarantees, awards or customer quotes; "
    "use only the facts given. Keep the same structure and the same line labels. Reply with ONLY this JSON: {\"draft\": \"...\"}"
)


def available(store) -> tuple[bool, str]:
    """هوش مصنوعی الان قابلِ استفاده است؟ (از پایگاه‌داده تصمیم می‌گیرد؛ ۶۰ ثانیه کَش)"""
    return idea_ai.status(store)


def _prompt(f: dict, draft: str, kind: str) -> str:
    facts = {k: f[k] for k in ("name", "business", "about", "audience", "tone", "tagline", "values", "do_words", "dont_words", "site") if f.get(k)}
    facts["products"] = [p["name"] for p in f.get("products", [])][:6]
    return (f"Content kind: {kind}\nBrand facts (use ONLY these): {json.dumps(facts, ensure_ascii=False)}\n"
            f"Words the brand never says: {', '.join(f.get('dont_words') or []) or '-'}\n\nDRAFT:\n{draft}")


def _ask(store, prompt: str):
    """⇒ (JSON، info). از همان مسیریابِ ایده‌ها می‌گذرد؛ فقط اعتبارسنجیِ جواب فرق دارد."""
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from apps.brandchar.inject import with_persona
    from services.ai import gateway
    from services.ai.priority import TEXT
    from services.ai.router import TASK_REASONING, models_for

    provider = gateway.text_provider(store, kind=TEXT)
    parsed, _row = recorded_json_call(
        store=store, task_type=AIRequest.TaskType.REASONING, prompt_id=PROMPT_ID, prompt_version="1", provider=provider,
        models=models_for(TASK_REASONING), prompt=prompt, system=with_persona(store, SYSTEM, "caption"),
        validate=lambda d: (isinstance(d, dict) and isinstance(d.get("draft"), str) and len(d["draft"].strip()) > 20, ["draft خالی است"]),
        validation_message="پولیش ناقص بود")
    return parsed


def polish(store, f: dict, draft: str, kind: str, *, ask=None) -> tuple[str | None, str]:
    """⇒ (متنِ تازه یا None، دلیلِ فارسی). هیچ‌وقت استثنا نمی‌دهد."""
    from django.conf import settings

    if getattr(settings, "IS_TEST", False) and ask is None:
        return None, "زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود."
    try:
        parsed = (ask or (lambda s, p: idea_ai.run_bounded(("mktplan", getattr(s, "pk", 0)), lambda: _ask(s, p))))(store, _prompt(f, draft, kind))
    except idea_ai.AIUnavailable as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — متیسِ بی‌اعتبار، گرهٔ خاموش، سیاستِ داده…
        return None, idea_ai.reason_text(exc)
    new = re.sub(r"\n{3,}", "\n\n", str(parsed.get("draft") or "")).strip()
    if len(new) < 20:
        return None, "هوش مصنوعی جوابِ قابل‌استفاده نداد."
    # حفظِ جای‌گیرها و رد کردنِ متنی که ادعای تازه آورده است
    old_slots, new_slots = set(re.findall(r"\[[^\]]+\]", draft)), set(re.findall(r"\[[^\]]+\]", new))
    if old_slots - new_slots:
        return None, "هوش مصنوعی جای‌گیرهای [ ] را برداشت؛ متنِ قبلی ماند."
    problems = drafts.check(new, f)
    old_problems = set(drafts.check(draft, f))
    fresh = [p for p in problems if p not in old_problems]
    if fresh:
        return None, "متنِ هوش مصنوعی ادعای تازه داشت (" + fresh[0] + ")؛ متنِ قبلی ماند."
    return new, ""

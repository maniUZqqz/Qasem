"""جادوگرِ هوش مصنوعیِ شخصیتِ گفتار: از پروفایلِ فروشگاه و واقعیت‌های تأییدشدهٔ برند یک پیش‌نویس می‌سازد.

* مدل فقط «لحن و ساختار» می‌نویسد؛ قیمت، آمار، وعدهٔ نتیجه و نظرِ مشتری را نمی‌داند و اجازهٔ ساختنشان را ندارد. هر جملهٔ جوابش از نگهبانِ ادعا (``persona.normalize``) می‌گذرد.
* هوش مصنوعی در دسترس نباشد (متیس ۴۰۲، گرهٔ خاموش، سیاستِ داده، زمانِ آزمون) ⇒ همان پیش‌نویسِ قاعده‌محور (``persona.draft``) با یک جملهٔ فارسی که می‌گوید چرا.
  بارِ بعد که هوش مصنوعی برگشت، همین دکمه دوباره آن را امتحان می‌کند؛ چیزی «قفل» نمی‌شود.
* خروجی ذخیره نمی‌شود؛ کاربر می‌بیند و خودش «ذخیره» را می‌زند.
"""
from __future__ import annotations

import logging
from typing import Callable

from . import persona as P

logger = logging.getLogger(__name__)
PROMPT_ID = "brandchar_persona"

SYSTEM = (
    "You are a brand-voice strategist for Persian-language small businesses. Reply with ONE JSON object only. "
    "You describe HOW the brand speaks (tone, values, words to prefer and avoid, greeting, sign-off, sample lines). "
    "You may only use the facts you are given. NEVER invent prices, statistics, percentages, results, awards, customer reviews, medical claims or the words 'best'/'first'. "
    "Write all text values in natural Persian. Keep every sentence short."
)

SCHEMA_HINT = (
    '{"name": str, "archetype": one of %s, "secondary": same set or "", "tagline": str, "summary": str, "tone": {"formality":0-100,"humor":0-100,"energy":0-100,"detail":0-100,"warmth":0-100},'
    ' "values": [str], "do_words": [str], "dont_words": [str], "catchphrases": [str], "emoji": "none|rare|moderate|lots", "address": "to|shoma", "greeting": str, "signoff": str,'
    ' "sample_lines": [{"situation": one of %s, "text": str}]}' % (list(P.ARCHETYPES), list(P.SITUATIONS))
)


def build_prompt(store, base: dict, sources: list[dict], brief: str = "") -> str:
    lines = [f"Brand: {getattr(store, 'name', '')}", f"Business type: {getattr(store, 'business_type', '')}", f"Description: {(getattr(store, 'description', '') or '')[:500]}",
             f"Audience: {getattr(store, 'target_audience', '')}"]
    prof = getattr(store, "profile", None) if hasattr(store, "profile") else None
    if prof is not None:
        lines.append(f"Registered tone: {getattr(prof, 'tone', '')} / {getattr(prof, 'brand_voice', '')}")
    if sources:
        lines.append("VERIFIED FACTS (the only facts you may rely on):")
        lines += [f"- {s['fact']}  [{s['source']}]" for s in sources]
    if brief.strip():
        lines.append(f"Owner's note: {brief.strip()[:400]}")
    lines.append("A rule-based starting draft you may improve (keep facts, fix voice):")
    lines.append(str({k: base[k] for k in ("name", "archetype", "tone", "values", "do_words", "dont_words", "catchphrases", "greeting", "signoff")}))
    lines.append("Return JSON with this shape: " + SCHEMA_HINT)
    return "\n".join(lines)


def _valid(d) -> tuple[bool, list[str]]:
    if not isinstance(d, dict):
        return False, ["not a dict"]
    miss = [k for k in ("archetype", "tone", "values") if not d.get(k)]
    return (not miss), [f"missing {k}" for k in miss]


def default_ask(store, prompt: str) -> tuple[dict, dict]:
    """⇒ (JSON، {label}). هر شکستی ⇒ ``AIUnavailable`` با دلیلِ فارسی. زیرِ آزمون هیچ‌وقت شبکه صدا نمی‌زند."""
    from apps.ideabank import ai as IA

    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        raise IA.AIUnavailable("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")

    def go():
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from apps.photoedit import translate
        from services.ai import gateway
        from services.ai.priority import TEXT
        from services.ai.router import TASK_REASONING, models_for

        provider = gateway.text_provider(store, kind=TEXT)
        parsed, _row = recorded_json_call(store=store, task_type=AIRequest.TaskType.REASONING, prompt_id=PROMPT_ID, prompt_version="1", provider=provider,
                                          models=models_for(TASK_REASONING), prompt=prompt, system=SYSTEM, validate=_valid, validation_message="شخصیتِ پیشنهادی ناقص بود")
        return parsed, (translate._describe(provider) or {})

    try:
        return IA.run_bounded(("persona", getattr(store, "pk", 0) or 0), go)
    except IA.AIUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — متیسِ بی‌اعتبار (۴۰۲)، گرهٔ خاموش، سیاستِ داده…
        raise IA.AIUnavailable(IA.reason_text(exc)) from exc


def _without_ai(store, base: dict, out: dict, brief: str, why: str) -> dict:
    """هوش مصنوعی در کار نیست: «توضیحِ دلخواه» را بی‌صدا دور نمی‌ریزیم. واژه‌های روشنِ لحن (شوخ، رسمی، کوتاه …) روی لغزنده‌ها اعمال می‌شود و یادداشت می‌گوید
    چه چیزی اعمال شد و چه چیزی نخوانده ماند. چیزی جز لغزنده‌های لحن عوض نمی‌شود (هیچ واقعیتی ساخته نمی‌شود)."""
    brief = " ".join(str(brief or "").split())
    out["brief"] = {"given": bool(brief), "applied": [], "used_by_ai": False}
    if not brief:
        return out
    persona = dict(out["persona"])
    tone, applied = P.apply_brief_tone(persona.get("tone") or {}, brief)
    if applied:
        out["persona"] = P.normalize({**persona, "tone": tone})
    out["brief"]["applied"] = applied
    if applied:
        out["notes"] = [*out["notes"], f"توضیحِ شما بدونِ هوش مصنوعی فقط برای لحن خوانده شد و این‌ها اعمال شد: {'، '.join(applied)}. بقیهٔ توضیح نخوانده ماند؛ با برگشتِ هوش مصنوعی دکمه را دوباره بزنید."]
    else:
        out["notes"] = [*out["notes"], "توضیحِ شما در این پیش‌نویس استفاده نشد، چون هوش مصنوعی در دسترس نیست و واژهٔ روشنی از لحن (مثلِ شوخ، رسمی، کوتاه، پرانرژی) در آن نبود. "
                                       "لغزنده‌ها را دستی تنظیم کنید یا با برگشتِ هوش مصنوعی دوباره «پیش‌نویس بساز» را بزنید."]
    return out


def draft(store, *, brief: str = "", use_ai: bool = True, ask: Callable | None = None) -> dict:
    """⇒ {persona، sources، notes، origin: facts|rule|ai، ai: {used، reason، label}، brief: {given، applied، used_by_ai}}. ``ask`` را آزمون تزریق می‌کند."""
    base = P.draft(store)
    out = {**base, "ai": {"used": False, "reason": "", "label": ""}, "brief": {"given": bool((brief or "").strip()), "applied": [], "used_by_ai": False}}
    if not use_ai:
        out["ai"]["reason"] = "هوش مصنوعی خواسته نشد."
        return _without_ai(store, base, out, brief, out["ai"]["reason"])
    prompt = build_prompt(store, base["persona"], base["sources"], brief)
    try:
        if ask is None:
            parsed, info = default_ask(store, prompt)
        else:
            parsed, info = ask(store, prompt), {}
    except Exception as exc:  # noqa: BLE001
        reason = getattr(exc, "args", [""])[0] or str(exc) or exc.__class__.__name__
        out["ai"]["reason"] = str(reason)[:240]
        out["notes"] = [*base["notes"], f"هوش مصنوعی در دسترس نبود ({out['ai']['reason']}). پیش‌نویسِ قاعده‌محور آماده است؛ بعداً دوباره امتحان کنید."]
        return _without_ai(store, base, out, brief, out["ai"]["reason"])
    if not isinstance(parsed, dict):
        out["ai"]["reason"] = "پاسخِ مدل قابلِ‌استفاده نبود."
        return _without_ai(store, base, out, brief, out["ai"]["reason"])
    # واقعیت‌های تأییدشده از پیش‌نویس می‌ماند: نام/شعار فقط وقتی از سند آمده‌اند عوض نمی‌شوند
    merged = {**base["persona"]}
    for k, v in parsed.items():
        if v in (None, "", [], {}):
            continue
        if base["origin"] == "facts" and k in ("name", "tagline", "catchphrases", "archetype", "secondary"):
            continue
        merged[k] = v
    out["persona"] = P.normalize(merged)
    out["origin"] = "facts" if base["origin"] == "facts" else "ai"
    out["ai"] = {"used": True, "reason": "", "label": (info or {}).get("label", "")}
    out["brief"]["used_by_ai"] = bool((brief or "").strip())
    out["notes"] = [*base["notes"], "این پیش‌نویس را هوش مصنوعی بهتر کرد؛ جمله‌های دارایِ قیمت، آمار یا وعدهٔ نتیجه خودکار حذف شده‌اند. هر چیزی را که قبول ندارید ویرایش کنید."]
    return out

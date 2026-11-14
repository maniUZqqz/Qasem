"""حالتِ «هوش مصنوعی»: ایده به فارسی ⇒ پارامترهای ترکیب (یا کدِ Remotion).

همهٔ فراخوانی‌ها از مسیریابِ متنِ پروژه می‌گذرند (لوکال روی گرهٔ پردازش ⇄ متیس؛ services.ai.gateway.text_provider). اعتبارِ متیس
تمام شده است (HTTP 402): این‌جا هیچ‌وقت خطا نمی‌ترکد — پیامِ روشنِ فارسی می‌دهد و برای «پارامترها» یک پیش‌نویسِ ساده از روی خودِ متنِ کاربر
می‌سازد (بی‌هوش‌مصنوعی)، تا صفحه کار کند و وقتی هوش مصنوعی برگشت، همان مسیر خودکار فعال شود. حالتِ قالبی اصلاً به AI نیاز ندارد.
"""
from __future__ import annotations

import json
import logging
import re

from . import assets, catalog, safety, specs

logger = logging.getLogger(__name__)

MSG_UNAVAILABLE = "هوش مصنوعی الان در دسترس نیست"
CALL_TIMEOUT = 150


class AIUnavailable(Exception):
    pass


def get_provider(store, kind: str | None = None):
    from django.conf import settings

    from services.ai import gateway

    fn = gateway.text_provider
    if getattr(settings, "IS_TEST", False) and getattr(fn, "__module__", "") == gateway.__name__:
        raise RuntimeError("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    return fn(store, kind=kind) if kind else fn(store)        # kind="code": the owner's coder model (qwen3-coder) first, like the site builder


def explain(exc: Exception) -> str:
    text = str(exc or "").strip()
    try:                                   # یک جملهٔ کوتاه («سرورِ پردازش خاموش است؛ متیس: …») به‌جای متنِ بلندِ تکراریِ هر دو مسیر
        from apps.thumbs import hooks

        short = hooks.reason_from_exception(exc, text, limit=200)
        if short:
            return short
    except Exception:  # noqa: BLE001
        pass
    if exc.__class__.__name__ in ("AllProvidersFailed", "PolicyBlocked") and text:
        return text[:400]
    try:
        from services.ai import priority

        return priority.classify(exc).sentence()[:400]
    except Exception:  # noqa: BLE001
        return (text or exc.__class__.__name__)[:300]


SYSTEM_SCRIPT = (
    "You write short motion-graphics video scripts as strict JSON for a code-driven video engine. "
    "Reply with ONE JSON object and nothing else (no markdown). Language of all on-screen text: {lang_name}. "
    "Never invent facts, prices, statistics or testimonials: use only what the user gave you. "
    "Schema: {{\"title\": str, \"scenes\": [scene, ...]}} with 2 to {max_scenes} scenes. A scene is one of: "
    "{{\"type\":\"title\",\"duration\":3-5,\"kicker\":str?,\"title\":str,\"subtitle\":str?}}, "
    "{{\"type\":\"list\",\"duration\":5-9,\"title\":str,\"items\":[2-5 short strs],\"numbered\":bool}}, "
    "{{\"type\":\"quote\",\"duration\":4-6,\"text\":str,\"author\":str?}}, "
    "{{\"type\":\"stat\",\"duration\":3-5,\"value\":\"number\",\"suffix\":str?,\"prefix\":str?,\"label\":str}}, "
    "{{\"type\":\"compare\",\"duration\":5-7,\"title\":str?,\"before_label\":str,\"after_label\":str,\"before\":str,\"after\":str}}, "
    "{{\"type\":\"product\",\"duration\":5-7,\"name\":str,\"price\":str?,\"features\":[<=4 strs],\"badge\":str?}}, "
    "{{\"type\":\"app\",\"duration\":5-7,\"caption\":str,\"bullets\":[<=4 strs]}}, "
    "{{\"type\":\"logo\",\"duration\":3,\"tagline\":str?}}, "
    "{{\"type\":\"cta\",\"duration\":3-5,\"title\":str,\"button\":str,\"note\":str?}}. "
    "Keep every text short (a title under 8 words). Start with a title or stat scene, end with a cta or logo scene. "
    "Total length about {seconds} seconds."
)


def _json_from(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("پاسخِ هوش مصنوعی JSON نبود.")
    return json.loads(m.group(0))


def script_from_idea(store, idea: str, *, style: str, aspect: str = "9:16", lang: str = "fa", seconds: int = 24,
                     provider=None, brand: dict | None = None) -> dict:
    """⇒ {"spec", "source": "ai"|"rules", "message", "title"}."""
    idea = (idea or "").strip()
    if len(idea) < 3:
        raise specs.SpecError("ایده را بنویسید (حداقل چند کلمه).")
    idea = idea[:2000]
    st = catalog.get(style)
    if not st:
        raise specs.SpecError("سبک را انتخاب کنید.")
    base = {"style": style, "aspect": aspect, "lang": lang, "fps": 30, "brand": brand or {}}
    try:
        prov = provider if provider is not None else get_provider(store)
        avail = getattr(prov, "availability", None)
        if callable(avail):
            ok, why = avail()
            if not ok:
                raise AIUnavailable(why or MSG_UNAVAILABLE)
        sys_prompt = SYSTEM_SCRIPT.format(lang_name="Persian (Farsi)" if lang == "fa" else "English", max_scenes=8, seconds=seconds)
        ctx = f"Brand: {store.name}. " + (f"About: {store.description[:300]}. " if getattr(store, "description", "") else "")
        user = f"{ctx}\nVisual style: {st['name_en']} ({st['about']}).\nIdea (Persian):\n{idea}"
        raw = prov.generate(user, system=sys_prompt, temperature=0.5, num_predict=1800, timeout=CALL_TIMEOUT)
        data = _json_from(raw if isinstance(raw, str) else str(raw or ""))
        scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("پاسخِ هوش مصنوعی صحنه نداشت.")
        spec = specs.normalize_spec({**base, "scenes": scenes[: specs.MAX_SCENES]})
        return {"spec": spec, "source": "ai", "message": "", "title": str(data.get("title") or "")[:120]}
    except Exception as exc:  # noqa: BLE001 — هر شکستِ مسیر ⇒ پیش‌نویسِ ساده
        logger.info("motion ai: falling back to rules (%s)", exc)
        msg = f"{MSG_UNAVAILABLE}: {explain(exc)}" if not isinstance(exc, (ValueError, specs.SpecError)) else "پاسخِ هوش مصنوعی قابل‌استفاده نبود"
        spec = specs.normalize_spec({**base, "scenes": rules_scenes(idea, lang)})
        return {"spec": spec, "source": "rules", "title": "",
                "message": msg + ". یک پیش‌نویسِ ساده از روی متنِ خودتان ساخته شد؛ ویرایشش کنید یا بعداً دوباره امتحان کنید."}


#: «سه مزیت: الف، ب و ج» / «چهار قدم تا اولین برنامه: …» / "three benefits: …" ⇒ عنوانِ فهرست + بدنه
_COUNT = r"(?:[۰-۹0-9]+|دو|سه|چهار|پنج|شش|two|three|four|five|six)"
_NOUN = r"(?:مزیت|نکته|قدم|گام|دلیل|ویژگی|امکان|مرحله|راه|مورد|حرکت|ترفند|benefits?|tips?|steps?|reasons?|features?|moves?)(?:‌ها)?"
_LIST_INTRO = re.compile(r"^(?P<head>" + _COUNT + r"\s+" + _NOUN + r"(?:\s+[^\s:：]+){0,4})\s*[:：]\s*(?P<body>.+)$", re.S | re.I)
#: جمله‌ای که «دستور به سازنده» است نه متنِ روی صفحه («در پایان دعوت به ثبت‌نام»)
_CTA_SENTENCE = re.compile(r"^(?:و\s+|and\s+)?(?:در\s+(?:پایان|آخر|انتها)|پایان|آخر|انتها|at the end|in the end|finally|lastly)\b", re.I)
_CTA_KINDS = (
    (("ثبت‌نام", "ثبت نام", "عضویت", "sign up", "signup", "register"), ("همین حالا ثبت‌نام کنید", "ثبت‌نام"), ("Sign up now", "Sign up")),
    (("خرید", "سفارش", "buy", "order"), ("همین حالا سفارش دهید", "سفارش"), ("Order now", "Order")),
    (("تماس", "contact", "call us"), ("با ما تماس بگیرید", "تماس"), ("Get in touch", "Contact")),
    (("دانلود", "نصب", "download", "install"), ("همین حالا دانلود کنید", "دانلود"), ("Download now", "Download")),
    (("مشاوره", "advice", "consult"), ("مشاوره بگیرید", "مشاوره"), ("Get advice", "Ask us")),
)


def _fit(text: str, words: int, chars: int) -> str:
    """متن را روی مرزِ واژه می‌برد و هیچ‌وقت وسطِ عبارت («بیش از | …») یا وسطِ واژه نمی‌شکند."""
    text = re.sub(r"\s+", " ", text or "").strip(" -•\t،,;؛:")
    if len(text.split()) <= words and len(text) <= chars:
        return text
    try:
        from apps.thumbs import phrases

        head, _ = phrases.clip(text, words, chars)
        if head:
            return head
    except Exception:  # noqa: BLE001
        pass
    cut = " ".join(text.split()[:words])[:chars]
    return cut.rsplit(" ", 1)[0] if " " in cut and len(cut) >= chars else cut


def _items(body: str) -> list[str]:
    """«الف، ب، و ج» ⇒ [الف، ب، ج]. جداکننده «،» است؛ «و»ِ آغازِ بند حذف می‌شود. در فهرستِ «الف، ب، ج و د» (بدونِ ویرگول پیش از «و») آخرین
    بند فقط وقتی دو نیم‌شدنی باشد (دست‌کم دو واژه در هر طرف) و فهرست دست‌کم سه بند داشته باشد، در آخرین «و» شکسته می‌شود؛ «برنامهٔ ورزشی و غذایی»
    (واژهٔ تک‌کلمه‌ای بعد از «و») هرگز نمی‌شکند."""
    parts = [re.sub(r"^\s*(?:و|and)\s+", "", x, flags=re.I).strip(" -•\t.؛;") for x in re.split(r"[،,\n]+", body)]
    parts = [x for x in parts if x]
    if len(parts) >= 3 and not re.match(r"^\s*(?:و|and)\s+", re.split(r"[،,\n]+", body)[-1].strip() or "", re.I):
        left, sep, right = parts[-1].rpartition(" و ") if " و " in parts[-1] else parts[-1].rpartition(" and ")
        if sep and len(left.split()) >= 2 and len(right.split()) >= 2:
            parts[-1:] = [left, right]
    return [_fit(x, 14, 100) for x in parts][:5]


def _cta_from(sentence: str, lang: str) -> tuple[str, str]:
    low = sentence.lower()
    for keys, fa_pair, en_pair in _CTA_KINDS:
        if any(k in low for k in keys):
            return fa_pair if lang == "fa" else en_pair
    return ("همین حالا شروع کنید", "شروع") if lang == "fa" else ("Get started", "Start")


def rules_scenes(idea: str, lang: str = "fa") -> list[dict]:
    """بدونِ هوش مصنوعی: متنِ کاربر را به صحنه تقسیم می‌کند (عنوان، فهرست، دعوت به اقدام).

    «معرفیِ چغر؛ سه مزیت: الف، ب و ج. در پایان دعوت به ثبت‌نام.» ⇒ عنوان «معرفیِ چغر»، فهرستِ «سه مزیت» با بندهای کامل و
    دعوتِ «همین حالا ثبت‌نام کنید» با دکمهٔ «ثبت‌نام» (جمله‌های دستوری مثلِ «در پایان …» روی صفحه نمی‌آیند)."""
    parts = [p.strip(" -•\t") for p in re.split(r"[\n؛;.!؟?]+", idea) if p.strip(" -•\t")]
    if not parts:
        parts = [idea.strip()]
    first, rest = parts[0], parts[1:]
    fa = lang == "fa"
    list_title, items, cta_src, others = "", [], "", []
    title_src = first
    m = _LIST_INTRO.match(first)
    if m:                                        # «چهار قدم تا اولین برنامه: …»: هم عنوانِ ویدیو است هم عنوانِ فهرست
        words = m.group("head").split()
        list_title, items = " ".join(words[:2]), _items(m.group("body"))
        title_src = m.group("head") if len(words) > 2 else ""
    for part in rest:
        m = _LIST_INTRO.match(part)
        if m and not items:
            list_title, items = " ".join(m.group("head").split()[:2]), _items(m.group("body"))
        elif _CTA_SENTENCE.match(part):
            cta_src = cta_src or part
        else:
            others.append(part)
    scenes: list[dict] = []
    if title_src:
        scenes.append({"type": "title", "duration": 4, "title": _fit(title_src, 12, 90)})
    elif not items:
        scenes.append({"type": "title", "duration": 4, "title": _fit(idea, 12, 90)})
    if not items and others:                     # بدونِ «سه مزیت:»: بقیهٔ جمله‌ها بندهای فهرست‌اند (اگر چند تا باشد، آخری دعوت)
        if len(others) >= 2 and not cta_src:
            cta_src = others.pop()
        items = [_fit(x, 14, 100) for x in others[:5]]
    if items:
        scenes.append({"type": "list", "duration": round(min(9.0, 3 + 1.3 * len(items)), 1), "title": list_title or ("نکته‌ها" if fa else "Highlights"),
                       "items": items, "numbered": bool(list_title)})
    if cta_src or len(scenes) > 1:
        title, button = _cta_from(cta_src, lang)
        scenes.append({"type": "cta", "duration": 4, "title": title, "button": button})
    else:
        scenes.append({"type": "cta", "duration": 3, "title": "شروع کنید" if fa else "Get started", "button": "ادامه" if fa else "Go"})
    return scenes


SYSTEM_CODE = (
    "You write ONE Remotion 4 composition as a single TSX file. Reply with only the code (no markdown fences). Rules: "
    "import only from \"react\", \"remotion\", \"@remotion/shapes\", \"@remotion/paths\", \"@remotion/noise\" and \"nm-motion\". "
    "No network, no fetch, no window/document access, no external images or fonts. Export `config` = "
    "{{width, height, fps, durationInFrames}} and `export default` a React component. Animate with useCurrentFrame, interpolate, spring, Sequence. "
    "Persian text must be written as plain strings inside elements with direction:'rtl' (never split Persian words into letters). "
    "Use inline styles and SVG only. Keep it under 150 lines."
)


def code_from_idea(store, idea: str, *, style: str = "", aspect: str = "9:16", provider=None) -> dict:
    idea = (idea or "").strip()[:2000]
    if len(idea) < 3:
        raise specs.SpecError("توضیحِ ویدیو را بنویسید.")
    w, h = specs.ASPECTS.get(aspect, (1080, 1920))
    try:
        prov = provider if provider is not None else get_provider(store, kind="code")
        st = catalog.get(style)
        hint = f" Use the look of the '{st['name_en']}' style (colours {st['palette']}, fonts {st['font']['latin']}/{st['font']['fa']})." if st else ""
        user = f"Canvas {w}x{h}, 30 fps, about 6 seconds.{hint}\nVideo idea (Persian):\n{idea}"
        raw = prov.generate(user, system=SYSTEM_CODE, temperature=0.3, num_predict=2600, timeout=CALL_TIMEOUT)
        code = re.sub(r"^```(?:tsx|typescript|ts|jsx|js)?\s*|\s*```$", "", (raw if isinstance(raw, str) else str(raw or "")).strip(), flags=re.I)
        if "export default" not in code:
            raise ValueError("کدِ نوشته‌شده ساختارِ لازم را نداشت.")
        try:
            safety.scan(code)
        except safety.UnsafeCode as exc:
            return {"code": code, "source": "ai", "warning": f"کدِ نوشته‌شده قاعده‌های امنیتی را رعایت نکرد: {exc}"}
        return {"code": code, "source": "ai", "warning": ""}
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailable(f"{MSG_UNAVAILABLE}: {explain(exc)}") from exc


__all__ = ["script_from_idea", "code_from_idea", "rules_scenes", "AIUnavailable", "assets"]

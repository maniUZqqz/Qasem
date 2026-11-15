"""حالتِ «هوش مصنوعی»: ایده به فارسی ⇒ پارامترهای ترکیب (یا کدِ Remotion).

همهٔ فراخوانی‌ها از مسیریابِ متنِ پروژه می‌گذرند (لوکال روی گرهٔ پردازش ⇄ متیس؛ services.ai.gateway.text_provider). اعتبارِ متیس
تمام شده است (HTTP 402): این‌جا هیچ‌وقت خطا نمی‌ترکد — پیامِ روشنِ فارسی می‌دهد و برای «پارامترها» یک پیش‌نویسِ ساده از روی خودِ متنِ کاربر
می‌سازد (بی‌هوش‌مصنوعی)، تا صفحه کار کند و وقتی هوش مصنوعی برگشت، همان مسیر خودکار فعال شود. حالتِ قالبی اصلاً به AI نیاز ندارد.
"""
from __future__ import annotations

import json
import logging
import re

from . import assets, catalog, components, motionlib, patch as patch_mod, promptkit, safety, specs

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
    if kind == "vision":                                       # the owner's qwen3-vl on the node (Metis vision as the fallback)
        return gateway.vision_provider(store)
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


def _json_from(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("پاسخِ هوش مصنوعی JSON نبود.")
    return json.loads(m.group(0))


def _call_json(prov, user: str, system: str, schema: dict, *, temperature: float, num_predict: int, images=None):
    """مدل را با شمای JSON صدا می‌زند (Ollama: format=schema؛ متیس: json_mode) و JSON را برمی‌گرداند."""
    kw = dict(system=system, temperature=temperature, num_predict=num_predict, timeout=CALL_TIMEOUT, json_schema=schema, json_mode=True)
    if images:
        kw["images"] = images
    try:
        raw = prov.generate(user, **kw)
    except TypeError:                           # a provider that does not know structured output: the same call without the schema (the prompt still carries it)
        raw = prov.generate(user, **{k: v for k, v in kw.items() if k not in ("json_schema", "json_mode")})
    return _json_from(raw if isinstance(raw, str) else str(raw or ""))


def salvage_scenes(scenes: list, base: dict) -> tuple:
    """هر صحنه جداگانه اعتبارسنجی می‌شود؛ صحنهٔ خراب دور ریخته می‌شود نه کلِ طرح. ⇒ (spec معتبر, یادداشت‌ها)."""
    good, notes = [], []
    for i, sc in enumerate(scenes[: specs.MAX_SCENES]):
        if not isinstance(sc, dict) or sc.get("type") not in components.COMPONENTS:     # an invented component name = a model that is not following the catalogue: refuse the whole answer
            raise specs.SpecError(f"نوعِ صحنهٔ «{sc.get('type') if isinstance(sc, dict) else sc}» در کتابخانه نیست.")
        try:
            specs.normalize_scene(sc, i)
            good.append(sc)
        except specs.SpecError as exc:
            notes.append(f"صحنهٔ {i + 1} کنار گذاشته شد: {exc}")
    if not good:
        raise specs.SpecError("هیچ‌کدام از صحنه‌های پیشنهادی معتبر نبود.")
    return specs.normalize_spec({**base, "scenes": good}), notes


def polish(spec: dict) -> dict:
    """«صیقلِ کارگردان» روی هر طرحی (هوش مصنوعی یا قاعده‌ای): پلتفرم، حرکتِ دوربین، تأکیدِ عددها؛ فقط چیزهایی که کاربر نگذاشته."""
    out = dict(spec)
    if not out.get("platform") and out.get("aspect") in motionlib.DEFAULT_PLATFORM:
        out["platform"] = motionlib.DEFAULT_PLATFORM[out["aspect"]]
    scenes = []
    for i, sc in enumerate(spec["scenes"]):
        sc = dict(sc)
        if "camera" not in sc and sc["type"] in ("title", "kinetic_title", "quote", "stat", "image_hero", "logo", "counter") and i % 2 == 0:
            sc["camera"] = {"move": "push-in", "amount": 0.35}
        elif "camera" not in sc and sc["type"] in ("product", "app", "price_card") and i % 2 == 1:
            sc["camera"] = {"move": "drift", "amount": 0.4}
        if "emphasis" not in sc and sc["type"] in ("title", "kinetic_title", "cta", "quote"):
            text = str(sc.get("title") or sc.get("text") or "")
            nums = re.findall(r"[\d۰-۹][\d۰-۹.,٬]*", text)
            if nums:
                sc["emphasis"] = nums[:2]
        scenes.append(sc)
    out["scenes"] = scenes
    return specs.normalize_spec(out)


def script_from_idea(store, idea: str, *, style: str, aspect: str = "9:16", lang: str = "fa", seconds: int = 24,
                     provider=None, brand: dict | None = None, platform: str = "", about: str = "") -> dict:
    """⇒ {"spec", "source": "ai"|"rules", "message", "title", "components", "prompt_chars"}."""
    idea = (idea or "").strip()
    if len(idea) < 3:
        raise specs.SpecError("ایده را بنویسید (حداقل چند کلمه).")
    idea = idea[:2000]
    st = catalog.get(style)
    if not st:
        raise specs.SpecError("سبک را انتخاب کنید.")
    base = {"style": style, "aspect": aspect, "lang": lang, "fps": 30, "brand": brand or {}, "platform": platform}
    kit = None
    try:
        prov = provider if provider is not None else get_provider(store)
        avail = getattr(prov, "availability", None)
        if callable(avail):
            ok, why = avail()
            if not ok:
                raise AIUnavailable(why or MSG_UNAVAILABLE)
        kit = promptkit.build_prompt(idea, style=style, aspect=aspect, lang=lang, seconds=seconds, brand_name=getattr(store, "name", ""),
                                     about=about or (getattr(store, "description", "") or ""), platform=platform)
        data = _call_json(prov, kit["user"], kit["system"], kit["schema"], temperature=0.4, num_predict=2400)
        scenes = data.get("scenes") if isinstance(data, dict) else None
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("پاسخِ هوش مصنوعی صحنه نداشت.")
        spec, notes = salvage_scenes(scenes, base)
        return {"spec": polish(spec), "source": "ai", "message": "؛ ".join(notes), "title": str(data.get("title") or "")[:120],
                "components": kit["ids"], "prompt_chars": kit["chars"]}
    except Exception as exc:  # noqa: BLE001 — هر شکستِ مسیر ⇒ پیش‌نویسِ ساده
        logger.info("motion ai: falling back to rules (%s)", exc)
        msg = f"{MSG_UNAVAILABLE}: {explain(exc)}" if not isinstance(exc, (ValueError, specs.SpecError)) else "پاسخِ هوش مصنوعی قابل‌استفاده نبود"
        spec = polish(specs.normalize_spec({**base, "scenes": rules_scenes(idea, lang)}))
        return {"spec": spec, "source": "rules", "title": "", "components": (kit or {}).get("ids", []), "prompt_chars": (kit or {}).get("chars", 0),
                "message": msg + ". یک پیش‌نویسِ ساده از روی متنِ خودتان ساخته شد؛ ویرایشش کنید یا بعداً دوباره امتحان کنید."}


def patch_from_chat(store, plan: dict, text: str, *, provider=None) -> dict:
    """«تیتر بزرگ‌تر شود» ⇒ {"ops", "say", "source": "ai"|"rules", "message"}. مدل فقط patch می‌نویسد؛ هر patch پیش از برگشت روی طرح آزموده می‌شود.
    مدل در دسترس نباشد یا patch معتبر نبود ⇒ قاعده‌های فارسیِ patch.rules_patch."""
    text = (text or "").strip()
    if len(text) < 2:
        raise specs.SpecError("بنویسید چه چیزی عوض شود.")
    note = ""
    try:
        prov = provider if provider is not None else get_provider(store)
        avail = getattr(prov, "availability", None)
        if callable(avail):
            ok, why = avail()
            if not ok:
                raise AIUnavailable(why or MSG_UNAVAILABLE)
        kit = promptkit.build_patch_prompt(plan, text)
        data = _call_json(prov, kit["user"], kit["system"], kit["schema"], temperature=0.2, num_predict=900)
        ops = data.get("ops") if isinstance(data, dict) else None
        if not isinstance(ops, list) or not ops:
            raise ValueError("مدل تغییری پیشنهاد نداد.")
        patch_mod.apply_patch(plan, ops)                         # آزمایشی: نامعتبر ⇒ PatchError ⇒ قاعده‌ها
        return {"ops": ops[: patch_mod.MAX_OPS], "say": str(data.get("say") or "انجام شد.")[:240], "source": "ai", "message": ""}
    except Exception as exc:  # noqa: BLE001
        note = f"{MSG_UNAVAILABLE}: {explain(exc)}" if not isinstance(exc, (ValueError, patch_mod.PatchError)) else "پیشنهادِ مدل قابل‌اعمال نبود"
    res = patch_mod.rules_patch(text, plan)
    res.update(source="rules", message=note + ("؛ با قاعده‌های ساده انجام شد." if res["ops"] else "."))
    return res


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

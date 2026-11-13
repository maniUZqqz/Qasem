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


def rules_scenes(idea: str, lang: str = "fa") -> list[dict]:
    """بدونِ هوش مصنوعی: متنِ کاربر را به صحنه تقسیم می‌کند (عنوان، فهرست، دعوت به اقدام)."""
    parts = [p.strip(" -•\t") for p in re.split(r"[\n؛;.!؟?]+", idea) if p.strip(" -•\t")]
    if not parts:
        parts = [idea.strip()]
    title = parts[0][:140]
    rest = parts[1:]
    scenes: list[dict] = [{"type": "title", "duration": 4, "title": title}]
    if rest:
        items = [x[:100] for x in rest[:5]]
        last = None
        if len(rest) >= 2:
            last = rest[-1]
            items = [x[:100] for x in rest[:-1][:5]]
        if items:
            scenes.append({"type": "list", "duration": min(9, 3 + 1.3 * len(items)), "title": "نکته‌ها" if lang == "fa" else "Highlights", "items": items})
        if last:
            scenes.append({"type": "cta", "duration": 4, "title": last[:140], "button": "همین حالا" if lang == "fa" else "Start now"})
    else:
        scenes.append({"type": "cta", "duration": 3, "title": "شروع کنید" if lang == "fa" else "Get started", "button": "ادامه" if lang == "fa" else "Go"})
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

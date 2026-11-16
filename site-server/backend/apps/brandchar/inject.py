"""تزریقِ شخصیتِ برند به هر تولیدکننده‌ای که «به نامِ برند» می‌نویسد — **یک** تابعِ مشترک، یک بلوکِ کران‌دار.

``with_persona(store, system, kind)`` پرامپتِ سیستمیِ هر تولیدکننده را با یک بلوکِ کوتاه (پیش‌فرض ≤ ۹۰۰ نویسه) پسوند می‌کند: نامِ شخصیت، کهن‌الگو، لحن،
مخاطب‌گیری (تو/شما)، سیاستِ ایموجی، واژه‌های بگو/نگو، ارزش‌ها و شعارها (و برای گفت‌وگو، سلام و خداحافظی). اگر شخصیتی نباشد یا خاموش باشد، پرامپت **بی‌تغییر** برمی‌گردد.

بلوک فقط «لحن» است؛ همیشه این جمله را دارد که قیمت، آمار، وعدهٔ نتیجه و نظرِ مشتری از خودت نساز. کران: وقتی جا کم است بخش‌ها به ترتیبِ اولویتِ معکوس کنار می‌روند
(کم‌اهمیت‌ترین اول)، و آخرِ کار برشِ سخت.

جاهایی که این تابع صدا زده می‌شود در ``INJECTION_POINTS`` ثبت است (و آزمون هر کدام را می‌سنجد): کپشن، ایجنتِ فروش، بانکِ ایده، ایده‌های ترند، تامنیل، اسکریپتِ موشن، سایت‌ساز.
"""
from __future__ import annotations

import logging

from . import persona as P

logger = logging.getLogger(__name__)

MAX_CHARS = 900
MARKER = "BRAND PERSONA"

#: همهٔ تولیدکننده‌های متنی که لحنِ برند را می‌گیرند: کلید ⇒ (نامِ فارسی، مسیرِ تابع، kind)
INJECTION_POINTS: dict[str, tuple[str, str, str]] = {
    "captions": ("کپشنِ محصول", "apps.content.tasks.generate_captions_task", "caption"),
    "sales_agent": ("ایجنتِ فروش و پاسخ‌های صندوقِ پیام", "apps.customers.agent.run_sales_agent", "sales"),
    "ideabank": ("بانکِ ایده (ایده بساز)", "apps.ideabank.ai._ask_router", "ideas"),
    "igtrends": ("ایده‌هایی که از ترندِ اینستاگرام می‌آید", "apps.igtrends.ideas.ai_brief", "ideas"),
    "thumbnails": ("عنوان‌های تامنیل", "apps.thumbs.ideation._default_ask", "thumbnail"),
    "motion_script": ("متنِ گوینده و صحنه‌های موشن", "apps.motion.ai.script_from_idea", "motion"),
    "site_builder": ("متنِ سایتِ ساخته‌شده با هوش مصنوعی", "apps.ai_engine.services._call", "site"),
}

KIND_GUIDE = {
    "caption": "Write the caption in this voice. Use a catchphrase only if it fits naturally; never force it.",
    "sales": "Answer the customer in this voice. Greet with the greeting on the first message; sign off with the sign-off when closing. Never promise what the shop rules forbid.",
    "ideas": "Phrase the ideas and hooks in this voice.",
    "thumbnail": "Titles: very short, in this voice, no claims, no invented numbers.",
    "motion": "Narration and on-screen text in this voice: short spoken sentences.",
    "site": "Website copy (headlines, short descriptions, button labels) in this voice.",
    "generic": "Write in this voice.",
}
KINDS_WITH_GREETING = {"sales", "motion", "site"}


def persona_row(store):
    """ردیفِ فعالِ شخصیت یا None (هیچ خطایی بالا نمی‌رود: تولیدِ متن هرگز به‌خاطرِ لحن نمی‌ایستد)."""
    if store is None:
        return None
    try:
        from .models import BrandPersona

        row = BrandPersona.objects.filter(store=store, active=True).first()
    except Exception:  # noqa: BLE001 — جدولِ شخصیت هنوز مهاجرت نشده یا دیتابیس در دسترس نیست
        logger.debug("brandchar persona lookup failed", exc_info=True)
        return None
    if row is None or not (row.data or {}):
        return None
    return row


def _pct(v: int) -> str:
    return str(int(v))


def sections(p: dict, kind: str) -> list[tuple[str, str]]:
    """بخش‌های بلوک به ترتیبِ اولویت: [(کلید، متن)]."""
    a = P.ARCHETYPES.get(p.get("archetype") or "", {})
    out: list[tuple[str, str]] = []
    head = f"{MARKER} (tone of voice only, never facts): you speak as «{p['name']}»" if p.get("name") else f"{MARKER} (tone of voice only, never facts)"
    if a:
        head += f" - archetype {a['en']} ({a['fa']})"
    out.append(("head", head + "."))
    tw = P.tone_words(p.get("tone") or {})
    if tw:
        out.append(("tone", "Tone: " + "، ".join(tw) + "."))
    out.append(("address", "Address the reader with " + ("«تو» (informal)" if p.get("address") == "to" else "«شما» (polite)") + "; write Persian."))
    emoji = p.get("emoji") or "rare"
    out.append(("emoji", {"none": "No emoji.", "rare": "Emoji: at most one per message.", "moderate": "Emoji: 1-3 per message.", "lots": "Emoji are welcome."}[emoji]))
    out.append(("guide", KIND_GUIDE.get(kind, KIND_GUIDE["generic"])))
    if p.get("do_words"):
        out.append(("do", "Prefer words: " + "، ".join(p["do_words"][:8]) + "."))
    if p.get("dont_words"):
        out.append(("dont", "Never use: " + "، ".join(p["dont_words"][:8]) + "."))
    if p.get("values"):
        out.append(("values", "Values: " + "، ".join(p["values"][:4]) + "."))
    if p.get("catchphrases"):
        out.append(("catch", "Signature phrases (optional): " + " | ".join(p["catchphrases"][:3])))
    if kind in KINDS_WITH_GREETING:
        if p.get("greeting"):
            out.append(("greeting", "Greeting: " + p["greeting"]))
        if p.get("signoff"):
            out.append(("signoff", "Sign-off: " + p["signoff"]))
    if p.get("summary"):
        out.append(("summary", "About the voice: " + p["summary"]))
    return out


#: وقتی جا کم است اول این‌ها می‌افتند (از چپ)
DROP_ORDER = ("summary", "signoff", "greeting", "catch", "values", "dont", "do", "emoji", "tone", "guide", "address")
SAFETY = "Do not invent prices, statistics, result promises or customer reviews."


def block_from_data(data: dict, kind: str = "generic", max_chars: int = MAX_CHARS) -> str:
    p = P.normalize(data)
    secs = sections(p, kind)
    keep = [k for k, _ in secs]

    def render() -> str:
        return "\n".join(["", *[t for k, t in secs if k in keep], SAFETY]).strip()

    text = render()
    for k in DROP_ORDER:
        if len(text) <= max_chars:
            break
        if k in keep:
            keep.remove(k)
            text = render()
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 1)].rstrip() + "…"
    return text


def block(store, kind: str = "generic", max_chars: int = MAX_CHARS) -> str:
    row = persona_row(store)
    if row is None:
        return ""
    return block_from_data(row.data, kind, max_chars)


def with_persona(store, system: str | None, kind: str = "generic", max_chars: int = MAX_CHARS) -> str | None:
    """``system`` + بلوکِ شخصیت (یا خودِ ``system`` اگر شخصیتی نیست). بدونِ ``system`` فقط بلوک برمی‌گردد. هیچ‌وقت استثنا نمی‌دهد."""
    try:
        b = block(store, kind, max_chars)
    except Exception:  # noqa: BLE001
        logger.debug("brandchar persona block failed", exc_info=True)
        return system
    if not b:
        return system
    return f"{system}\n\n{b}" if system else b


def store_of_project(project):
    """پروژهٔ سایت‌ساز ⇒ فروشگاهِ بسته‌شده (``SiteBinding``) یا None."""
    try:
        from .models import SiteBinding

        row = SiteBinding.objects.filter(project_slug=getattr(project, "slug", "")).select_related("store").first()
        return row.store if row else None
    except Exception:  # noqa: BLE001
        return None

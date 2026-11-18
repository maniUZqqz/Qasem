"""پیش‌نویسِ متنی بدونِ هوش مصنوعی — فقط از واقعیت‌های فروشگاه (``facts.store_facts``) و قالب‌های بی‌ادعا.

هرجا چیزی را فقط خودِ مالک می‌داند (قیمت، پیشنهاد، نظرِ مشتری، قدم‌های دقیقِ استفاده) جای‌گیرِ «[…]» می‌ماند؛ هیچ عدد، درصد، قیمت یا نظری ساخته
نمی‌شود. این متن‌ها «نقطهٔ شروعِ قابلِ تأیید»اند؛ وقتی هوش مصنوعی (گرهٔ پردازش یا متیس) در دسترس باشد ``ai.polish`` همان‌ها را با لحنِ شخصیتِ برند
بازنویسی می‌کند (و اگر نبود، همین‌ها می‌مانند).
"""
from __future__ import annotations

import re
from typing import Any

from apps.ideabank import guard

OPT_OUT = "برای لغو دریافتِ پیام، «لغو» را بفرستید."
SLOT = "[پیشنهادِ واقعیِ شما]"


def _name(f) -> str:
    return f["name"] or "فروشگاه ما"


def _one_liner(f) -> str:
    return (f.get("one_liner") or f.get("about") or f.get("summary") or f.get("business") or "").strip()


def _clip(text: str, n: int) -> str:
    """تا n نویسه، در مرزِ واژه؛ اگر بریده شد «…» می‌گذارد."""
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ،؛:")
    return cut + "…"


def _product(f) -> str:
    return f["flagship"] or "محصولِ ما"


def _site(f) -> str:
    return f["site"] or "[نشانیِ سایت یا اپِ شما]"


# ----------------------------------------------------------------- پروفایل

def bio_versions(f: dict) -> list[dict]:
    name, one, aud, cta = _name(f), _one_liner(f), f["audience_short"], f["cta"]
    first = re.split(r"[.؛:]", one)[0].strip() if one else ""
    cands = [
        ("معرفی", f"{name}\n{first or f['business'] or 'نام و حوزهٔ کارتان را بنویسید'}\n{cta} 👇"),
        ("برای مخاطب", f"برای {aud}\n{first or name}\nلینکِ شروع 👇"),
        ("شعار", f"{f['tagline'] or name}\n{f['business'] or first or ''}\nشروع از لینکِ زیر 👇".replace("\n\n", "\n")),
    ]
    out = []
    for label, text in cands:
        text = text.strip()[:150].rstrip()
        out.append({"label": label, "text": text, "chars": len(text)})
    return out


def highlights(f: dict) -> list[dict]:
    p = _product(f)
    return [
        {"name": "معرفی", "what": f"چند اسلاید: {_name(f)} چیست و برای چه کسی است."},
        {"name": "چطور کار می‌کند", "what": f"مسیرِ استفاده از {p} قدم‌به‌قدم."},
        {"name": "پرسش‌ها", "what": "پاسخ‌های کوتاه به پرسش‌های پرتکرار (از قوانینِ فروشگاه)."},
        {"name": "پشتِ صحنه", "what": "کارِ روزمرهٔ تیم؛ بدونِ ادعا."},
        {"name": "شروع کنید", "what": f"لینکِ شروع و راهِ تماس: {_site(f)}"},
    ]


def profile_draft(f: dict) -> str:
    lines = ["بایو (سقفِ ۱۵۰ نویسه؛ هر سه نسخه زیرِ سقف است):", ""]
    for v in bio_versions(f):
        lines += [f"نسخهٔ «{v['label']}» ({v['chars']} نویسه):", v["text"], ""]
    lines.append("هایلایت‌های پیشنهادی:")
    for i, h in enumerate(highlights(f), 1):
        lines.append(f"  {i}) {h['name']} — {h['what']}")
    lines += ["", f"پستِ سنجاق‌شده: یک پستِ «معرفی» + یک پستِ «چطور کار می‌کند» + یک پستِ «شروع کنید» ({_site(f)})",
              "فقط پیش‌نویس است؛ چیزی خودکار منتشر نمی‌شود."]
    return "\n".join(lines)


# ----------------------------------------------------------------- محتوا (پست / کاروسل / استوری / ریلز)

def _pillar_lines(pillar: str, f: dict) -> tuple[str, list[str], str]:
    n, p, aud, one = _name(f), _product(f), f["audience_short"], _one_liner(f)
    cta = f["cta"]
    if pillar == "intro":
        return (f"{n}؛ {f['tagline'] or one or 'یک معرفیِ کوتاه'}",
                [f"{n} چیست؟ {one or '[یک جمله دربارهٔ کارتان]'}", f"برای چه کسی؟ {aud}", f"از کجا شروع کنم؟ {_site(f)}"], cta)
    if pillar == "how":
        return (f"با {p} از کجا شروع کنم؟",
                ["قدمِ ۱: [نخستین قدمِ مشتری]", "قدمِ ۲: [قدمِ بعد]", f"قدمِ ۳: [نتیجهٔ کار — بدونِ وعدهٔ اغراق‌آمیز]"], f"شروع: {_site(f)}")
    if pillar == "objection":
        return (f"یک نگرانیِ رایجِ {aud}",
                ["نگرانی را با زبانِ خودِ مخاطب بنویسید: [نگرانیِ واقعی]", f"پاسخِ صادقانه: {f['values'][0] if f['values'] else '[پاسخِ شما]'}",
                 "بدونِ مقایسه با رقیب و بدونِ تضمین"], cta)
    if pillar == "faq":
        return (f"سه پرسشِ پرتکرار دربارهٔ {p}",
                ["پرسش ۱ و پاسخِ کوتاه: [از قوانینِ فروشگاه]", "پرسش ۲ و پاسخِ کوتاه: [از قوانینِ فروشگاه]", "پرسش ۳ و پاسخِ کوتاه: [از قوانینِ فروشگاه]"],
                "پرسشِ دیگری دارید؟ همین‌جا بپرسید.")
    if pillar == "offer":
        return (f"دعوت به شروع با {n}",
                [f"پیشنهادِ واقعی: {SLOT}", f"برای چه کسی؟ {aud}", f"چطور شروع کنم؟ {_site(f)}"], cta)
    if pillar == "behind":
        return (f"پشتِ صحنهٔ {n}",
                ["یک کارِ روزمره را نشان دهید: [کارِ واقعیِ تیم]", "چرا این کار را می‌کنید؟ [دلیلِ واقعی]", "از مخاطب بپرسید چه چیزی را بیشتر ببیند."], cta)
    if pillar == "process":
        return (f"کارِ تکراری یا مسیرِ ساده‌تر؟",
                ["قبل: [کارِ تکراریِ مخاطب]", f"بعد: همان کار با {p}", "فقط دربارهٔ «روندِ کار»؛ عددِ ساعت یا درصد ننویسید."], cta)
    if pillar == "series":
        return ("چند فریمِ تعاملی",
                [f"فریم ۱: پرسش از {aud}", "فریم ۲: نظرسنجی (دو گزینه)", "فریم ۳: جعبهٔ سؤال"], cta)
    return (n, [one or "[یک جمله]"], cta)


def hashtags_for(f: dict, limit: int = 6) -> list[str]:
    """هشتگ‌های پیشنهادی فقط از نام و حوزه و مخاطب و محصولِ خودِ فروشگاه (بدونِ هشتگِ ساختگیِ پرطرفدار)."""
    from apps.content import hashtags as H

    srcs = [f.get("name", ""), f.get("flagship", ""), " ".join((f.get("business") or "").split()[:3]), " ".join((f.get("audience_short") or "").split()[:3])]
    out: list[str] = []
    for s in srcs:
        words = [w for w in H.clean(re.sub(r"[^\w\u200c\s]", " ", s)).split("_") if w][:3]
        while words and words[-1] in ("و", "با", "برای", "از", "در", "به", "که"):      # هشتگِ نیمه‌کاره («…_و») نمی‌ماند
            words.pop()
        tag = "_".join(words)
        if tag and len(tag) >= 3 and tag not in out and not any(ch.isdigit() for ch in tag):
            out.append(tag)
    return ["#" + t for t in out[:limit]]


def caption_block(f: dict, pillar: str) -> str:
    hook, _beats, cta = _pillar_lines(pillar, f)
    cap = "\n".join([hook, _one_liner(f) or "[یک جمله دربارهٔ کارتان]", cta])
    tags = " ".join(hashtags_for(f))
    return "کپشنِ پیشنهادی:\n" + cap + (("\nهشتگ‌های پیشنهادی: " + tags) if tags else "")


def content_draft(kind: str, pillar: str, f: dict) -> str:
    hook, beats, cta = _pillar_lines(pillar, f)
    frames = {"carousel": "اسلاید", "story": "فریم", "reel": "صحنه", "post": "نکته"}.get(kind, "نکته")
    head = {"carousel": "کاروسل (قابِ ۴:۵)", "story": "استوری (۹:۱۶)", "reel": "ریلز (۹:۱۶، ۱۵ تا ۲۵ ثانیه)", "post": "پستِ تصویری"}.get(kind, kind)
    lines = [f"نوع: {head}", f"قلاب (جملهٔ اول): {hook}", ""]
    lines += [f"  {i}) {frames} — {b}" for i, b in enumerate(beats, 1)]
    lines += ["", f"دعوت به اقدام: {cta}", "", caption_block(f, pillar), "", "فقط پیش‌نویس است؛ چیزی خودکار منتشر نمی‌شود. هرچه در [ ] آمده را خودتان پر کنید."]
    return "\n".join(lines)


def strip_markup(text: str) -> str:
    """متنی که به گوینده می‌رسد: بدونِ «https://» (نشانیِ سایت همان‌طور که مردم می‌گویند)، بدونِ جای‌گیرِ [ ] و فاصله‌های اضافه."""
    t = re.sub(r"https?://", "", str(text or ""), flags=re.I)
    t = re.sub(r"([A-Za-z0-9])/(?=\s|$)", r"\1", t)             # «panel.example.ir/» ⇒ «panel.example.ir»
    t = re.sub(r"\[[^\]]*\]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def spoken(text: str) -> str:
    """مثلِ ``strip_markup``؛ «برچسب: متن» هم برای گوینده «برچسب، متن» می‌شود (دونقطه را گوینده نمی‌خواند)."""
    return strip_markup(text).replace(": ", "، ").replace(" + ", " و ").strip(" ،")


def _spoken_beats(pillar: str, f: dict) -> list[str]:
    """جمله‌هایی از زاویه که **برای گفتن** نوشته شده‌اند.

    بندهای ``_pillar_lines`` سه جور است: جملهٔ خواندنی (دربارهٔ برند، مخاطب، نشانی)، جای‌گیرِ [ ] برای مالک، و **دستورِ نویسنده** («بدونِ مقایسه با
    رقیب…»، «عددِ ساعت یا درصد ننویسید»، «از مخاطب بپرسید…»، «نظرسنجی (دو گزینه)»، یا پاسخی که از «ارزش‌های شخصیتِ برند» می‌آید). فقط جورِ اول را می‌خوانیم؛
    دو جورِ دیگر هرگز به صدا نمی‌رسد (پیش‌تر «پیش‌نویس را پیش‌نویس بگو» و «//panel…» روی صدا رفته بود)."""
    n, p, aud, one = _name(f), _product(f), f["audience_short"], _one_liner(f)
    site = f.get("site") or ""
    if pillar == "intro":
        out = [f"{n} چیست؟ {one}"] if one else []
        out.append(f"برای چه کسی؟ {aud}")
        if site:
            out.append(f"از کجا شروع کنم؟ {site}")
        return out
    if pillar == "offer":
        out = [f"برای چه کسی؟ {aud}"]
        if site:
            out.append(f"چطور شروع کنم؟ {site}")
        return out
    if pillar == "process":
        return [f"همان کار با {p}"]
    return []                                 # how / objection / faq / behind / series: بندها جای‌گیر یا دستورِ نویسنده است؛ چیزی برای خواندن نیست


def reel_script(f: dict, pillar: str) -> str:
    """متنِ گویندهٔ یک ریلزِ ۱۵ تا ۲۵ ثانیه‌ای (چند جملهٔ کوتاه، بدونِ عدد و ادعا و بدونِ دستورِ نویسنده)."""
    hook, _beats, cta = _pillar_lines(pillar, f)
    h = spoken(hook)
    parts = [h.rstrip("؟?.") + ("؟" if hook.rstrip().endswith(("؟", "?")) else ".")]
    for b in _spoken_beats(pillar, f):
        text = spoken(b)
        if text and len(text) < 160:
            parts.append(text.rstrip(".") + ".")
    parts.append(spoken(cta).rstrip(".") + ".")
    text = " ".join(x for x in parts if x)
    return re.sub(r"\s+", " ", text)[:600]


_NARR_LINE = re.compile(r"^[ \t•\-–]*متنِ گویندگی[^:\n]*:\s*(.+)$", re.M)
_NARR_BEAT = re.compile(r"^[ \t•\-–]*نریشن\s*:\s*(.+)$", re.M)


def narration_from_draft(draft: str) -> str:
    """متنِ گویندهٔ یک ریلز از پیش‌نویسِ خودش: خطِ «متنِ گویندگی (پیشنهادی): …» یا خط‌های «نریشن: …». نبود ⇒ ""."""
    text = str(draft or "")
    m = _NARR_LINE.search(text)
    if m:
        cand = m.group(1)
    else:
        beats = [b.strip() for b in _NARR_BEAT.findall(text) if b.strip()]
        cand = " ".join(b.rstrip(".") + "." for b in beats)
    cand = strip_markup(cand)
    return cand[:600] if len(cand) > 20 else ""


def motion_spec(f: dict, pillar: str) -> dict:
    """سندِ قالبیِ موشن (سه صحنه: عنوان، فهرست، دعوت)."""
    hook, _beats, cta = _pillar_lines(pillar, f)
    # روی صفحهٔ ویدیو فقط جمله‌های خواندنی می‌آید (نه دستورِ نویسنده مثل «بدونِ مقایسه با رقیب…» یا «پیش‌نویس را پیش‌نویس بگو»)
    items = [spoken(b)[:70] for b in _spoken_beats(pillar, f)][:4] or [x for x in (_clip(_one_liner(f), 70), f["audience_short"]) if x][:3]
    cta = strip_markup(cta)
    has_logo = bool(f.get("has_logo"))                      # فروشگاهِ بی‌لوگو: «show_logo» خاموش (وگرنه رندر «فروشگاه لوگو ندارد» می‌دهد)
    return {
        "style": "glassmorphism", "aspect": "9:16", "fps": 30, "lang": "fa",
        "brand": {"use_brand_colors": True, "show_logo": has_logo, "name": f["name"], **({"logo": "store-logo"} if has_logo else {})},
        "scenes": [
            {"type": "title", "duration": 4.0, "kicker": _name(f)[:40], "title": hook[:80], "subtitle": (f["tagline"] or _one_liner(f))[:90]},
            {"type": "list", "duration": 7.0, "title": "در یک نگاه", "items": items, "numbered": True},
            {"type": "cta", "duration": 4.0, "title": cta[:60], "button": "شروع", "note": ""},
        ],
        "platform": "reels",
    }


#: پس‌زمینه‌های آمادهٔ «تامنیل‌ساز» (apps.thumbs.aibg.PRESETS) برای هر حوزه؛ دستورِ انگلیسی و رنگ‌های برند را خودِ همان بخش می‌سازد،
#: پس هیچ توضیحِ فارسی‌ای به مدلِ تصویر نمی‌رسد (FLUX فارسی را خوب نمی‌فهمد) و ترجمه به هوش مصنوعی وابسته نیست.
_BG_BY_FIELD = (
    (("ورزش", "باشگاه", "تناسب", "بدنساز", "مربی", "gym", "fitness"), ("gym_blur", "tech_gradient", "studio_light", "cinematic_fog")),
    (("غذا", "آشپز", "کافه", "رستوران", "شیرینی", "نان", "food"), ("kitchen_warm", "pastel_paper", "studio_light", "luxury_dark")),
    (("نرم‌افزار", "نرمافزار", "اپ", "فناوری", "هوش مصنوعی", "دیجیتال", "software", "tech"), ("tech_gradient", "studio_light", "cinematic_fog", "pastel_paper")),
    (("طلا", "جواهر", "لوکس", "عطر", "luxury"), ("luxury_dark", "cinematic_fog", "studio_light", "pastel_paper")),
    (("گیاه", "طبیعت", "ارگانیک", "کوه", "nature"), ("nature_bokeh", "pastel_paper", "studio_light", "cinematic_fog")),
)
_BG_DEFAULT = ("studio_light", "pastel_paper", "tech_gradient", "cinematic_fog")
_PILLAR_ORDER = ("intro", "how", "objection", "faq", "offer", "behind", "process", "series")


def bg_preset(f: dict, pillar: str) -> str:
    """کلیدِ پس‌زمینهٔ آماده برای این فروشگاه و زاویه (هر زاویه یک حالِ‌وهوای متفاوت)."""
    blob = " ".join([f.get("business", ""), f.get("about", ""), f.get("name", "")]).lower()
    options = next((o for words, o in _BG_BY_FIELD if any(w in blob for w in words)), _BG_DEFAULT)
    idx = _PILLAR_ORDER.index(pillar) if pillar in _PILLAR_ORDER else 0
    return options[idx % len(options)]


# ----------------------------------------------------------------- پیام‌ها

def email_draft(f: dict, pillar: str) -> str:
    n, aud, site = _name(f), f["audience_short"], _site(f)
    hook, beats, cta = _pillar_lines(pillar, f)
    subject = hook[:70]
    one = _one_liner(f) or "[یک جمله دربارهٔ کارتان]"
    body = ["سلام،", "", one if one.startswith(n) else f"{n}: {one}", ""]
    body += [f"• {re.sub(chr(10), ' ', b)}" for b in beats]
    body += ["", f"{cta}: {site}", "", "با احترام،", n, "", "اگر نمی‌خواهید این ایمیل‌ها را دریافت کنید، همین ایمیل را با عنوانِ «لغو» پاسخ دهید."]
    return f"موضوع: {subject}\n\n" + "\n".join(body)


def sms_text(f: dict, pillar: str = "offer") -> str:
    n, site = _name(f), f["site"] or "[لینک]"
    base = f"{n}: {_clip(f['tagline'] or _one_liner(f) or '[پیامِ کوتاه]', 70).rstrip('.')}. {site}"
    return f"{base}\n{OPT_OUT}"


def dm_text(f: dict) -> str:
    n, aud = _name(f), f["audience_short"]
    return (f"سلام، وقتتان بخیر. من از طرفِ {n} پیام می‌دهم؛ {_clip(_one_liner(f), 190) or '[یک جملهٔ معرفی]'} "
            f"فکر کردم شاید برای {aud} مفید باشد. اگر خواستید توضیحِ کوتاهی بفرستم، بنویسید. (برای نفرستادنِ پیام‌های بعدی، «لغو» را بنویسید.)")


def testimonial_request(f: dict) -> str:
    return (f"سلام! از اینکه از {_name(f)} استفاده کردید ممنونیم. اگر راضی بودید، می‌شود یکی دو جمله دربارهٔ تجربهٔ خودتان بنویسید "
            "و اجازه بدهید با نامِ شما (یا بی‌نام) در شبکه‌ها بگذاریم؟ هر چه نوشتید همان را منتشر می‌کنیم؛ چیزی تغییر نمی‌کند.")


def thumb_content(f: dict, pillar: str) -> dict:
    hook, _beats, _cta = _pillar_lines(pillar, f)
    return {"title": hook[:60], "subtitle": (f["tagline"] or _one_liner(f))[:70], "kicker": _name(f)[:24]}


def check(text: str, f: dict) -> list[str]:
    """هشدارِ ادعاهای پرخطر (عدد/درصد/قیمتی که در منبع نیست) و واژه‌های «نگو»ی شخصیتِ برند. بازنویسی نمی‌کند."""
    from apps.common.fatext import contains_phrase
    from .facts import source_blob

    out = list(guard.problems(text, source_blob(f)))
    for w in f.get("dont_words") or []:
        if w and contains_phrase(text, w, ignore_negated=True):
            out.append(f"واژهٔ «{w}» در فهرستِ «نگو»ی شخصیتِ برند است")
    return out[:6]

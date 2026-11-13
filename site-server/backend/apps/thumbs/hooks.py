"""فرمول‌های آمادهٔ «قلاب» (عنوانِ تامنیل) و مفهومِ تصویری — بخشِ بدونِ هوش مصنوعیِ ایده‌پردازی.

وقتی هوش مصنوعی در دسترس نیست (اعتبارِ متیس تمام شده، سرورِ پردازش خاموش، سیاستِ «فقط لوکال»…) ایده‌ها از همین‌جا می‌آید:
فرمول‌های فارسیِ آزموده‌شده برای عنوانِ کوتاهِ کلیک‌خور + یک مفهومِ تصویری برای هر سبک + دستورِ پس‌زمینهٔ تصویرساز.

اصلِ ایمنی: **هیچ عددِ آماری، قیمت، درصد یا ادعای تأییدنشده‌ای ساخته نمی‌شود.** تنها عددِ ممکن «تعدادِ موردهای یک فهرست» است
(سبکِ عدد/لیست) که مالک باید با محتوای واقعی یکی کند، و قیمتِ محصول فقط وقتی می‌آید که خودِ محصول قیمت دارد و کاربر خواسته باشد.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from . import typo

STOP_TAIL = " .؛،:!؟?-–—"
#: دستورِ تصویرساز باید فقط حروفِ لاتین و نشانه‌گذاریِ ساده داشته باشد
ASCII_PROMPT = re.compile(r"^[A-Za-z0-9 ,.'\-:;()/&+!?\"]+$")


@dataclass(frozen=True)
class Formula:
    key: str
    label: str                 # نامِ فارسیِ الگو
    title: str                 # قالبِ عنوان: {t} موضوع، {n} عدد، {o} دیگری، {a} مخاطب
    subtitle: str
    kicker: str
    styles: tuple[str, ...]    # سبک‌های مناسب (به ترتیبِ ترجیح)
    needs_number: bool = False
    needs_other: bool = False
    needs_audience: bool = False
    product_only: bool = False


FORMULAS: tuple[Formula, ...] = (
    Formula("list_mistakes", "فهرستِ اشتباه‌ها", "{n} اشتباهِ رایج در {m}", "قبل از شروع ببینید", "فهرست", ("number_list", "face_text"), needs_number=True),
    Formula("list_tips", "فهرستِ نکته‌ها", "{n} نکته دربارهٔ {m}", "کوتاه و کاربردی", "راهنما", ("number_list", "pinterest_collage"), needs_number=True),
    Formula("list_ideas", "فهرستِ ایده‌ها", "{n} ایده برای {m}", "برای ذخیره‌کردن", "ایده", ("pinterest_collage", "number_list"), needs_number=True),
    Formula("question_works", "سؤالِ «جواب می‌دهد؟»", "{m} واقعاً جواب می‌دهد؟", "پاسخ را ببینید", "پرسش", ("question_hook", "face_text")),
    Formula("question_why", "سؤالِ «چرا؟»", "چرا همه دربارهٔ {m} حرف می‌زنند؟", "", "کنجکاوی", ("question_hook", "face_text")),
    Formula("question_start", "سؤالِ «از کجا شروع کنیم؟»", "{m} را از کجا شروع کنیم؟", "قدم اول", "شروع", ("question_hook", "minimal_luxury")),
    Formula("curiosity", "شکافِ کنجکاوی", "آنچه دربارهٔ {m} باید بدانید", "", "بخوانید", ("face_text", "cinema_poster", "news_bold")),
    Formula("before_after", "قبل و بعد", "{m}؛ قبل و بعد", "تفاوت را ببینید", "نتیجه", ("split_ba", "face_text")),
    Formula("steps", "قدم‌به‌قدم", "{m} را قدم‌به‌قدم یاد بگیرید", "ساده و مرحله‌به‌مرحله", "آموزش", ("face_text", "number_list", "minimal_luxury")),
    Formula("big_mistake", "اشتباهِ بزرگ", "اشتباهِ بزرگ در {m}", "نکنید", "هشدار", ("face_text", "news_bold", "sticker_outline")),
    Formula("versus", "رویارویی", "{t} یا {mo}؟", "کدام بهتر است؟", "مقایسه", ("versus", "split_ba"), needs_other=True),
    Formula("for_audience", "برای یک مخاطب", "{m} برای {a}", "", "ویژهٔ شما", ("face_text", "product_hero", "minimal_luxury"), needs_audience=True),
    Formula("basics", "از پایه", "{m} را از اول بشناسید", "", "مقدماتی", ("minimal_luxury", "pinterest_collage", "face_text")),
    Formula("news", "خبر / ویژه", "ویژه: {m}", "جزئیات را ببینید", "ویژه", ("news_bold", "face_text")),
    Formula("new_product", "معرفیِ محصول", "{t}", "همین حالا ببینید", "تازه", ("product_hero", "minimal_luxury", "sticker_outline"), product_only=True),
    Formula("product_offer", "محصول با دعوت به اقدام", "{m} را ببینید", "", "پیشنهاد", ("product_hero", "sticker_outline", "pinterest_collage"), product_only=True),
    Formula("poster_story", "پوسترِ معرفی", "{t}", "", "", ("cinema_poster", "neon"), ),
    Formula("neon_night", "حالِ شبانه", "{m}", "", "ویژه", ("neon", "question_hook")),
)

#: سبک‌های ترجیحیِ هر قالب (به ترتیب)
PLATFORM_STYLES = {
    "youtube": ("face_text", "question_hook", "number_list", "split_ba", "versus", "news_bold", "neon"),
    "aparat": ("face_text", "news_bold", "number_list", "question_hook", "split_ba", "versus"),
    "telegram": ("news_bold", "face_text", "number_list", "product_hero", "neon"),
    "ig_portrait": ("minimal_luxury", "product_hero", "sticker_outline", "pinterest_collage", "magazine_cover", "number_list", "quote_card", "face_text", "split_ba"),
    "ig_square": ("sticker_outline", "product_hero", "minimal_luxury", "quote_card", "face_text", "number_list", "versus"),
    "story": ("neon", "face_text", "sticker_outline", "magazine_cover", "question_hook", "quote_card", "product_hero", "number_list"),
    "pinterest": ("pinterest_collage", "number_list", "cinema_poster", "retro_poster", "minimal_luxury", "magazine_cover", "product_hero", "quote_card"),
    "poster": ("cinema_poster", "retro_poster", "magazine_cover", "neon", "minimal_luxury", "face_text"),
}

#: مفهومِ تصویریِ هر سبک ({t} = موضوع)
CONCEPTS = {
    "face_text": "نمای نزدیک و خیلی بزرگِ سوژهٔ اصلیِ «{t}» با حالتِ هیجان یا تعجب؛ پس‌زمینهٔ پرنور با پرتوِ رنگی و فقط چند کلمهٔ درشت با لبهٔ ضخیم.",
    "split_ba": "تصویر دوتکه: «قبل» کم‌رنگ و تیره، «بعد» پرنور و رنگی؛ خطِ اریبِ جداکننده و یک عنوانِ کوتاه. بهترین کار با دو عکسِ هم‌زاویه است.",
    "number_list": "یک عددِ غولیِ برجسته با حاشیه، عنوانِ کوتاه زیرش و سوژه‌ای کوچک‌تر در کنار؛ بیننده فوراً می‌فهمد یک فهرستِ مشخص در انتظار است.",
    "question_hook": "علامتِ سؤالِ بزرگ پشتِ سوژه، نورِ نقطه‌ایِ مرموز و عنوانی به شکلِ پرسش؛ سوژه با نگاهِ کنجکاو یا تردید.",
    "minimal_luxury": "زمینهٔ تیره یا کرم، قابِ باریکِ طلایی، «{t}» در مرکز با نورِ ملایم و کلی فضای خالی؛ عنوانی آرام و باوقار.",
    "cinema_poster": "رنگ‌بندیِ فیروزه‌ای-نارنجیِ سینمایی، سوژهٔ بزرگ با لبهٔ نور، عنوانِ درشتِ بلوکی در سومِ پایین و سطرِ ریزِ اعتبارها.",
    "pinterest_collage": "کلاژِ ۳ تا ۴ کارتِ عکسِ سفیدحاشیه با چرخشِ جزئی روی زمینهٔ کاغذی، چسب‌نوار و عنوانِ روی نوارِ هایلایت؛ حسِ «ایدهٔ قابلِ ذخیره».",
    "product_hero": "محصولِ «{t}» بزرگ و تمیز روی نورِ مرکزی با حلقهٔ نور و بازتابِ کف؛ عنوانِ کوتاه و دکمهٔ دعوت به اقدام.",
    "sticker_outline": "رنگ‌های شادِ پاپ، کنفتی، سوژه با حاشیهٔ سفیدِ ضخیمِ استیکری و عنوانی کمی کج با دو لبه.",
    "neon": "زمینهٔ تیرهٔ شبانه با شبکهٔ کفِ پرسپکتیو، نورِ نئونیِ دورِ سوژه و عنوانِ درخشان؛ حالِ فناوری و شب.",
    "news_bold": "عکس در پس‌زمینه، نوارِ اریبِ تیره با لبهٔ قرمز، تیترِ سفیدِ درشت با یک کلمهٔ زرد و برچسبِ «ویژه».",
    "versus": "دو سوژه رو‌به‌روی هم روی دو رنگِ متضاد، «VS» بزرگ در مرکز و نامِ هر طرف زیرِ عکسش.",
    "magazine_cover": "جلدِ مجله دربارهٔ «{t}»: نامِ بزرگ در بالا، سوژه‌ای که سرش کمی روی نام می‌نشیند، یک تیترِ اصلی با نوارِ رنگی و یک تیترِ دوم در پایین.",
    "retro_poster": "پوسترِ چاپیِ قدیمی دربارهٔ «{t}»: کاغذِ کرم، خورشیدِ پرتوی با حلقه‌های هم‌مرکز پشتِ سوژه، نوارِ عنوانِ لبه‌بریده و قابِ دوخطی.",
    "quote_card": "جمله‌ای دربارهٔ «{t}» با علامتِ نقل‌قولِ بزرگ، متنِ وسط‌چین با یک کلمهٔ رنگی، خطِ جداکننده و نامِ گوینده؛ عکسِ گوینده در دایره.",
}

#: دستورِ پس‌زمینهٔ تصویرساز (انگلیسی؛ FLUX نوشتهٔ فارسی نمی‌فهمد و متن نمی‌کشد) — همه «بدونِ متن و آدم»
BG_PROMPTS = {
    "face_text": "vibrant studio backdrop with soft rays of light and a bold saturated colour gradient, strong contrast, empty space on both sides",
    "split_ba": "clean two-tone studio backdrop with a diagonal split of light, bright side and dull side, minimal",
    "number_list": "bold colourful abstract geometric background with halftone dots and diagonal stripes, flat pop-art style",
    "question_hook": "dark moody spotlight background with subtle fog and a glowing centre, mysterious atmosphere, deep shadows",
    "minimal_luxury": "luxury dark studio backdrop with soft golden bokeh light, minimal, elegant, smooth gradient, empty centre",
    "cinema_poster": "cinematic teal and orange atmospheric background, volumetric light beams, drifting fog, film grain, wide empty space",
    "pinterest_collage": "soft pastel paper texture background with natural window light and gentle shadows, flat lay, warm tones",
    "product_hero": "clean product photography backdrop with a soft central spotlight, glossy reflective floor and smooth gradient",
    "sticker_outline": "playful bright pop background with confetti shapes and flat colours, cheerful, high saturation",
    "neon": "cyberpunk neon grid floor in perspective, dark purple and cyan glow, synthwave night sky",
    "news_bold": "dark blurred newsroom background with bokeh lights and a faint blue glow, shallow depth of field",
    "versus": "dramatic split lighting backdrop, cool blue on one side and warm red on the other, energy burst in the middle",
    "magazine_cover": "clean glossy studio backdrop with a soft light gradient and subtle paper texture, elegant fashion magazine mood, empty space",
    "retro_poster": "vintage printed paper texture with a faded sunburst and subtle halftone grain, warm cream and muted colours, retro poster mood, empty centre",
    "quote_card": "soft out-of-focus abstract gradient background with gentle bokeh light, calm and moody, dark tones, plenty of empty space",
}
BG_SUFFIX = ", no text, no letters, no logos, no watermark, no people, high quality, 8k"


def short_topic(topic: str, max_words: int = 4) -> str:
    t = typo.clean(topic).strip(STOP_TAIL)
    t = re.sub(r"[*|]", " ", t)
    words = t.split()
    return " ".join(words[:max_words]) if words else ""


def mark_key(phrase: str) -> str:
    """فقط یک کلمهٔ مهمِ عبارت را برای رنگی‌شدن علامت می‌زند («برنامهٔ ورزشی شخصی» ⇒ «*برنامهٔ* ورزشی شخصی»): بلندترین کلمه."""
    words = typo.clean(phrase).split()
    if not words:
        return ""
    if len(words) == 1:
        return f"*{words[0]}*"
    best = max(range(len(words)), key=lambda i: (len(words[i]), -i))
    return " ".join(f"*{w}*" if i == best else w for i, w in enumerate(words))


_BRACES = re.compile(r"\{[^{}]*\}")


def friendly_reason(text, limit: int = 170) -> str:
    """پیامِ خامِ خطای سرویس (اغلب انگلیسی و JSON) ⇒ یک جملهٔ کوتاهِ فارسی برای کاربر؛ هرگز JSON ِ خام در پنل نیاید."""
    raw = str(text or "")
    low = raw.lower()
    if "402" in raw or "insufficient" in low or "credit" in low:
        return "اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)"
    prev = None
    while prev != raw:                                    # JSON ِ تودرتو را لایه‌لایه پاک کن
        prev, raw = raw, _BRACES.sub("", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" :—-")
    return raw if len(raw) <= limit else raw[: limit - 1].rstrip() + "…"


def fa_digits(value) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def split_versus(topic: str) -> tuple[str, str] | None:
    """«الف یا ب» / «الف در برابر ب» / «الف vs ب» ⇒ (الف، ب)."""
    m = re.split(r"\s+(?:یا|در برابر|دربرابر|یا اینکه|vs\.?|VS)\s+", typo.clean(topic), maxsplit=1)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        return short_topic(m[0], 3), short_topic(m[1], 3)
    return None


def _rot(seed: str, n: int) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % max(1, n)


def preferred_styles(fmt: str) -> tuple[str, ...]:
    return PLATFORM_STYLES.get(fmt) or PLATFORM_STYLES["youtube"]


def bg_prompt(style: str, mood: str = "", colors_en: str = "") -> str:
    base = BG_PROMPTS.get(style) or BG_PROMPTS["face_text"]
    extra = f", colour palette of {colors_en}" if colors_en else ""
    return base + extra + BG_SUFFIX


def rule_ideas(topic: str, *, fmt: str = "youtube", count: int = 6, product: dict | None = None, audience: str = "", store_name: str = "",
               number: int | str | None = None, other: str = "", variation: int = 0) -> list[dict]:
    """ایده‌های قطعی (بدونِ هوش مصنوعی). ⇒ فهرستِ idea ها با سبک‌های گوناگون، به ترتیبِ مناسبِ قالب.

    product = {"name", "price_text"?, "short"?} وقتی ایده برای یک محصول است (قیمت فقط اگر داده شده باشد)."""
    prod = product or {}
    t = short_topic(prod.get("name") or topic)
    if not t:
        return []
    versus = split_versus(topic) if not other else (t, short_topic(other, 3))
    if versus:
        t, other = versus
    n_txt = fa_digits(number) if number not in (None, "", 0) else fa_digits(5)
    pref = list(preferred_styles(fmt))
    forms = []
    for f in FORMULAS:
        if f.needs_other and not other:
            continue
        if f.needs_audience and not audience:
            continue
        if f.product_only and not prod:
            continue
        forms.append(f)

    def rank(f: Formula):
        pos = [pref.index(s) for s in f.styles if s in pref]
        return (min(pos) if pos else 99, _rot(f"{topic}|{f.key}|{variation}", 1000))

    forms.sort(key=rank)
    ideas: list[dict] = []
    used_styles: dict[str, int] = {}
    done: set[str] = set()
    for limit in (1, 2, 99):                # اول از هر سبک یکی (تنوع)، بعد دومی، بعد هرچه ماند
        for f in forms:
            if len(ideas) >= count:
                break
            style = next((s for s in f.styles if s in pref), f.styles[0])
            if f.key in done or used_styles.get(style, 0) >= limit:
                continue
            ideas.append(_idea(f, style, t=t, n_txt=n_txt, other=other, audience=audience, prod=prod, store_name=store_name))
            done.add(f.key)
            used_styles[style] = used_styles.get(style, 0) + 1
    return ideas


def _idea(f: Formula, style: str, *, t: str, n_txt: str, other: str, audience: str, prod: dict, store_name: str) -> dict:
    title = f.title.format(t=t, m=mark_key(t), n=n_txt, o=other, mo=mark_key(other), a=short_topic(audience, 4))
    sub = f.subtitle
    if prod.get("short") and f.key in ("new_product", "product_offer"):
        sub = short_topic(prod["short"], 8)
    idea = {
        "title": title, "subtitle": sub, "kicker": f.kicker, "number": n_txt if f.needs_number else "",
        "badge": prod.get("price_text", "") if prod and f.key == "new_product" else "",
        "tagline": "", "credits": "", "cta": "دیدن و سفارش" if prod and f.key in ("new_product", "product_offer") else "",
        "style": style, "formula": f.key, "formula_label": f.label, "source": "rules",
        "concept": CONCEPTS.get(style, "").format(t=t),
        "bg_prompt_en": bg_prompt(style),
        "mood": "",
        "label_a": "", "label_b": "",
    }
    if style == "cinema_poster":
        idea["tagline"] = "داستانی که باید دید"
        if store_name:
            idea["credits"] = f"یک تولیدِ {store_name}"
    if style == "versus" and other:
        idea["label_a"], idea["label_b"] = t, other
        idea["title"] = f"{t} یا {other}؟"
    if style == "split_ba":
        idea["label_a"], idea["label_b"] = "بعد", "قبل"
    return idea

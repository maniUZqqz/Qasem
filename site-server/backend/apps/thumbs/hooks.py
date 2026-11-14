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

from . import phrases, typo

STOP_TAIL = " .؛،:!؟?-–—"
#: دستورِ تصویرساز باید فقط حروفِ لاتین و نشانه‌گذاریِ ساده داشته باشد
ASCII_PROMPT = re.compile(r"^[A-Za-z0-9 ,.'\-:;()/&+!?\"]+$")


@dataclass(frozen=True)
class Formula:
    key: str
    label: str                 # نامِ فارسیِ الگو
    title: str                 # قالبِ عنوان: {m} موضوعِ علامت‌خورده، {t} موضوعِ ساده، {n} عدد، {mo} دیگری، {a} مخاطب، {q} «؟» برای جمله‌های پرسشی
    subtitle: str              # زیرعنوانِ پیش‌فرض (اگر باقیِ موضوع جای‌گرفتنی باشد، آن جایگزین می‌شود)
    kicker: str
    styles: tuple[str, ...]    # سبک‌های مناسب (به ترتیبِ ترجیح)
    needs_number: bool = False
    needs_other: bool = False
    needs_audience: bool = False
    product_only: bool = False
    #: noun = فقط برای موضوعِ اسمی («برنامهٔ ورزشی»)، clause = فقط برای جمله («چطور … بسازیم؟»)، both = هر دو
    kinds: str = "noun"
    needs_lead: bool = False   # فقط وقتی موضوع با عدد و واژهٔ فهرست شروع شده («۷ اشتباه در …»)
    tail_sub: bool = True      # باقیِ موضوعِ بریده‌شده می‌تواند زیرعنوان شود


FORMULAS: tuple[Formula, ...] = (
    Formula("list_mistakes", "فهرستِ اشتباه‌ها", "{n} اشتباهِ رایج در {m}", "قبل از شروع ببینید", "فهرست", ("number_list", "face_text"), needs_number=True),
    Formula("list_tips", "فهرستِ نکته‌ها", "{n} نکته دربارهٔ {m}", "کوتاه و کاربردی", "راهنما", ("number_list", "pinterest_collage"), needs_number=True),
    Formula("list_ideas", "فهرستِ ایده‌ها", "{n} ایده برای {m}", "برای ذخیره‌کردن", "ایده", ("pinterest_collage", "number_list"), needs_number=True),
    Formula("list_given", "فهرستِ شما", "{n} {L} {p} {m}", "قبل از شروع ببینید", "فهرست", ("number_list", "face_text", "pinterest_collage"),
            needs_number=True, needs_lead=True),
    Formula("question_works", "سؤالِ «جواب می‌دهد؟»", "{m} واقعاً جواب می‌دهد؟", "پاسخ را ببینید", "پرسش", ("question_hook", "face_text")),
    Formula("question_why", "سؤالِ «چرا؟»", "چرا همه دربارهٔ {m} حرف می‌زنند؟", "ماجرا را ببینید", "کنجکاوی", ("question_hook", "face_text")),
    Formula("question_start", "سؤالِ «از کجا شروع کنیم؟»", "{m} را از کجا شروع کنیم؟", "قدمِ اول", "شروع", ("question_hook", "minimal_luxury")),
    Formula("curiosity", "شکافِ کنجکاوی", "آنچه دربارهٔ {m} باید بدانید", "پیش از شروع بخوانید", "بخوانید", ("face_text", "cinema_poster", "news_bold")),
    Formula("before_after", "قبل و بعد", "{m}؛ قبل و بعد", "تفاوت را ببینید", "نتیجه", ("split_ba", "face_text"), tail_sub=False),
    Formula("steps", "قدم‌به‌قدم", "{m} را قدم‌به‌قدم یاد بگیرید", "ساده و مرحله‌به‌مرحله", "آموزش", ("face_text", "number_list", "minimal_luxury")),
    Formula("big_mistake", "اشتباهِ بزرگ", "اشتباهِ بزرگ در {m}", "نکنید", "هشدار", ("face_text", "news_bold", "sticker_outline")),
    Formula("versus", "رویارویی", "{t} یا {mo}؟", "کدام بهتر است؟", "مقایسه", ("versus", "split_ba"), needs_other=True, kinds="both", tail_sub=False),
    Formula("for_audience", "برای یک مخاطب", "{m} برای {a}", "یک راهنمای کوتاه", "ویژهٔ شما", ("face_text", "product_hero", "minimal_luxury"),
            needs_audience=True, tail_sub=False),
    Formula("basics", "از پایه", "{m} را از اول بشناسید", "از قدمِ اول", "مقدماتی", ("minimal_luxury", "pinterest_collage", "face_text")),
    Formula("news", "خبر / ویژه", "ویژه: {m}", "جزئیات را ببینید", "ویژه", ("news_bold", "face_text")),
    Formula("new_product", "معرفیِ محصول", "{t}", "همین حالا ببینید", "تازه", ("product_hero", "minimal_luxury", "sticker_outline"), product_only=True, kinds="both"),
    Formula("product_offer", "محصول با دعوت به اقدام", "{m} را ببینید", "همین حالا ببینید", "پیشنهاد", ("product_hero", "sticker_outline", "pinterest_collage"),
            product_only=True, kinds="both"),
    Formula("poster_story", "پوسترِ معرفی", "{t}", "یک معرفیِ کوتاه", "", ("cinema_poster", "neon"), kinds="both"),
    Formula("neon_night", "حالِ شبانه", "{m}", "همین حالا ببینید", "ویژه", ("neon", "question_hook"), kinds="both"),
    # موضوعِ جمله‌ای («چطور …؟»، «چرا …؟»): خودِ جمله عنوانِ خوبی است؛ قالب‌های «{موضوع} را از اول بشناسید» برایش بی‌معنی‌اند
    Formula("clause_direct", "خودِ پرسش", "{m}{q}", "پاسخ را ببینید", "پرسش", ("question_hook", "face_text"), kinds="clause", tail_sub=False),
    Formula("clause_news", "پرسشِ ویژه", "ویژه: {m}{q}", "جزئیات را ببینید", "ویژه", ("news_bold", "face_text"), kinds="clause", tail_sub=False),
    Formula("clause_calm", "آموزشِ آرام", "{m}{q}", "قدم‌به‌قدم", "آموزش", ("minimal_luxury", "pinterest_collage"), kinds="clause", tail_sub=False),
    Formula("clause_pop", "آموزشِ شاد", "{m}{q}", "همین حالا ببینید", "ببینید", ("sticker_outline", "magazine_cover"), kinds="clause", tail_sub=False),
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
    """موضوع را کوتاه می‌کند، ولی هیچ‌وقت روی واژهٔ ناتمام (حرفِ اضافه، «و»، کسرهٔ اضافه…) نمی‌برد."""
    return phrases.clip(phrases.split_paren(topic)[0], max_words)[0]


def mark_key(phrase: str) -> str:
    return phrases.mark_key(phrase)


_BRACES = re.compile(r"\{[^{}]*\}")
#: جمله‌های بلندِ سرویس ⇒ معادلِ کوتاهِ فارسی (تا پیام وسطِ کلمه بریده نشود)
_COMPACT = (
    ("(کلیدِ پیش‌فرض .env)", ""),
    ("(پیش‌فرض .env)", ""),
    ("API سازگار با OpenAI", "سرویسِ هوش مصنوعی"),
    ("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — ", ""),
    ("سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ این داده به سرویسِ بیرونی (متیس) را نمی‌دهد.", "سیاستِ دادهٔ فروشگاه اجازهٔ استفاده از متیس را نمی‌دهد."),
    ("(صفحهٔ «سرورهای پردازش» در پنل وضعیت را نشان می‌دهد). بدون سرورِ پردازش، مدلِ لوکال پاسخ نمی‌دهد.", ""),
)
_PARTS = re.compile(r"(?<=[؛.!؟])\s+|\s+[—–]\s+")


def fit_text(raw: str, limit: int) -> str:
    """متن را تا سقفِ limit حرف کوتاه می‌کند **بدونِ بریدنِ وسطِ کلمه**: اول بندهای کامل (تا «؛» / «.» / «—»)، بعد تا نزدیک‌ترین
    مرزِ واژه (روی واژهٔ ناتمام هم تمام نمی‌شود) و فقط در این حالتِ دوم «…» می‌آید."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if len(s) <= limit:
        return s
    out = ""
    for part in _PARTS.split(s):
        cand = f"{out} {part}".strip() if out else part
        if len(cand) <= limit:
            out = cand
        else:
            break
    if out:
        return out.rstrip("؛ ").rstrip()
    cut = s[: max(1, limit - 1)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    head, _ = phrases.clip(cut, 999)
    return (head or cut).rstrip(" ,،؛:-—") + "…"


def friendly_reason(text, limit: int = 170) -> str:
    """پیامِ خامِ خطای سرویس (اغلب انگلیسی و JSON) ⇒ یک جملهٔ کوتاهِ فارسی برای کاربر؛ هرگز JSON ِ خام در پنل نیاید
    و هرگز وسطِ کلمه بریده نمی‌شود."""
    raw = str(text or "")
    low = raw.lower()
    if "402" in raw or "insufficient" in low or "credit" in low:
        return "اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)"
    prev = None
    while prev != raw:                                    # JSON ِ تودرتو را لایه‌لایه پاک کن
        prev, raw = raw, _BRACES.sub("", raw)
    for long_, short in _COMPACT:
        raw = raw.replace(long_, short)
    raw = re.sub(r"\s+", " ", raw).strip(" :—-")
    return fit_text(raw, limit)


def reason_from_exception(exc, fallback_text: str = "", limit: int = 240) -> str:
    """خطای مسیریابِ هوش مصنوعی ⇒ یک جملهٔ کوتاه: «سرورِ پردازش خاموش است؛ متیس: سیاستِ داده اجازه نمی‌دهد».
    اگر خطا فهرستِ شکستِ هر مسیر (``failures``) دارد از همان‌ها ساخته می‌شود (نه از متنِ بلندِ خام)."""
    fails = getattr(exc, "failures", None)
    if isinstance(fails, dict) and fails:
        try:
            from services.ai import priority

            labels, names = priority.LABELS, priority.PROVIDER_LABEL
        except Exception:  # noqa: BLE001
            labels, names = {}, {}
        parts = []
        for prov, f in fails.items():
            if f is None:
                continue
            msg = labels.get(getattr(f, "kind", "")) or friendly_reason(getattr(f, "message", ""), 90)
            name = str(names.get(prov, prov or ""))
            if name and name not in msg and "سرورِ پردازش" not in msg:
                msg = f"{name}: {msg}"
            parts.append(msg)
        if parts:
            return fit_text("؛ ".join(parts), limit)
    return friendly_reason(fallback_text or str(exc or ""), limit)


def fa_digits(value) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


_VS = re.compile(r"\s+(?:یا اینکه|در برابر|دربرابر|در مقابل|یا|vs\.?|VS)\s+")


def split_versus(topic: str) -> tuple[str, str] | None:
    """«الف یا ب» / «الف در برابر ب» / «الف vs ب» ⇒ (الف، ب). «یا»یِ داخلِ پرانتز هم حساب می‌شود
    («برنامهٔ تکی (فقط ورزشی یا فقط غذایی)» ⇒ («فقط ورزشی»، «فقط غذایی»))."""
    main, inner = phrases.split_paren(topic)
    for part in (main, inner):
        m = _VS.split(part, maxsplit=1)
        if len(m) == 2 and m[0].strip() and m[1].strip():
            a, b = phrases.clip(m[0], 3)[0], phrases.clip(m[1], 3)[0]
            if a and b:
                return a, b
    return None


def _rot(seed: str, n: int) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % max(1, n)


def preferred_styles(fmt: str) -> tuple[str, ...]:
    return PLATFORM_STYLES.get(fmt) or PLATFORM_STYLES["youtube"]


def bg_prompt(style: str, mood: str = "", colors_en: str = "") -> str:
    base = BG_PROMPTS.get(style) or BG_PROMPTS["face_text"]
    extra = f", colour palette of {colors_en}" if colors_en else ""
    return base + extra + BG_SUFFIX


MAX_TITLE_WORDS = 8


def _frame_words(title: str, aud_words: int = 0, other_words: int = 0) -> int:
    """چند واژه از عنوان را «قالب» پر کرده (غیر از جای موضوع) ⇒ بودجهٔ واژهٔ موضوع = سقف − این."""
    t, n = title, 0
    for key, cnt in (("{n}", 1), ("{L}", 1), ("{p}", 1), ("{a}", aud_words), ("{mo}", other_words)):
        if key in t:
            n += cnt
            t = t.replace(key, "")
    for key in ("{m}", "{t}", "{q}"):
        t = t.replace(key, "")
    return n + len(t.split())


def audience_phrase(audience: str) -> str:
    """مخاطبِ فروشگاه («مربی‌های باشگاه و مربی‌های شخصی که …؛ و ورزشکارانی که …») ⇒ اولین گروهِ کوتاه و کامل («مربی‌های باشگاه»)."""
    first = re.split(r"[؛;،,.\n]|\s+که\s+|\s+و\s+", phrases.split_paren(audience)[0], maxsplit=1)[0]
    head, _ = phrases.clip(first, 3, 26)
    return head if head else ""


def rule_ideas(topic: str, *, fmt: str = "youtube", count: int = 6, product: dict | None = None, audience: str = "", store_name: str = "",
               number: int | str | None = None, other: str = "", variation: int = 0) -> list[dict]:
    """ایده‌های قطعی (بدونِ هوش مصنوعی). ⇒ فهرستِ idea ها با سبک‌های گوناگون، به ترتیبِ مناسبِ قالب.

    product = {"name", "price_text"?, "short"?} وقتی ایده برای یک محصول است (قیمت فقط اگر داده شده باشد).
    عنوان‌ها هیچ‌وقت وسطِ جمله تمام نمی‌شوند؛ باقیِ موضوعِ بلند (مثلاً «برای مبتدی‌ها در خانه») زیرعنوان می‌شود."""
    prod = product or {}
    src = prod.get("name") or topic
    tp = phrases.parse_topic(src)
    if not tp.main:
        return []
    other = phrases.clip(other, 3)[0] if other else ""
    versus = (phrases.clip(tp.main, 3)[0], other) if other else split_versus(src)
    left = ""
    if versus:
        left, other = versus
    if number not in (None, "", 0):
        n_txt = fa_digits(number)
    else:
        n_txt = tp.lead_n or fa_digits(5)
    aud = audience_phrase(audience)
    pref = list(preferred_styles(fmt))
    forms = []
    for f in FORMULAS:
        if f.needs_other and not other:
            continue
        if f.needs_audience and (not aud or " برای " in f" {tp.main} "):         # «… برای … برای مربی‌ها» بی‌معنی است
            continue
        if f.product_only and not prod:
            continue
        if f.needs_lead and not tp.lead_n:
            continue
        if tp.lead_n and f.needs_number and not f.needs_lead:         # «۷ اشتباه در …» ⇒ فقط فهرستِ خودِ کاربر، با همان واژه‌ها
            continue
        if f.kinds == "noun" and tp.kind == "clause" and not prod:
            continue
        if f.kinds == "clause" and tp.kind != "clause":
            continue
        forms.append(f)

    def rank(f: Formula):
        pos = [pref.index(s) for s in f.styles if s in pref]
        return (min(pos) if pos else 99, _rot(f"{topic}|{f.key}|{variation}", 1000))

    forms.sort(key=rank)
    ideas: list[dict] = []
    used_styles: dict[str, int] = {}
    done: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for limit in (1, 2, 99):                # اول از هر سبک یکی (تنوع)، بعد دومی، بعد هرچه ماند
        for f in forms:
            if len(ideas) >= count:
                break
            style = next((s for s in f.styles if s in pref), f.styles[0])
            if f.key in done or used_styles.get(style, 0) >= limit:
                continue
            idea = _idea(f, style, tp=tp, n_txt=n_txt, other=other, left=left, aud=aud, prod=prod, store_name=store_name)
            key = (typo.plain(idea["title"]), style)
            if key in seen:                  # همان عنوان با همان سبک دوباره نیاید
                continue
            seen.add(key)
            ideas.append(idea)
            done.add(f.key)
            used_styles[style] = used_styles.get(style, 0) + 1
    return ideas


def _idea(f: Formula, style: str, *, tp, n_txt: str, other: str, left: str, aud: str, prod: dict, store_name: str) -> dict:
    budget = max(2, MAX_TITLE_WORDS - _frame_words(f.title, len(aud.split()), len(other.split())))
    if f.kinds == "clause" or (tp.kind == "clause" and f.key in ("poster_story", "neon_night")):
        budget = 9                                          # جمله‌ها را کامل نگه می‌داریم (خودشان عنوان‌اند)
    head, rest = phrases.clip(tp.main, budget, 60)
    if f.key == "versus":
        head, rest = left, ""
    q = "؟" if (tp.question and not tp.main.rstrip().endswith(("؟", "?"))) else ""
    head = head.rstrip("؟?")
    title = f.title.format(t=head, m=mark_key(head), n=n_txt, o=other, mo=mark_key(other), a=aud, L=tp.lead_noun, p=tp.lead_prep or "برای", q=q)
    sub = f.subtitle
    tail = phrases.tail_phrase(rest) if (rest and f.tail_sub) else ""
    if prod and f.key in ("new_product", "product_offer"):
        sub = phrases.first_clause(prod.get("short") or "") or phrases.clip(tp.inner, 6, 40)[0] or tail or f.subtitle
    elif tail:
        sub = tail
    elif tp.inner:
        sub = phrases.first_clause(tp.inner, 8, 46) or f.subtitle         # «چغر؛ دستیار هوش مصنوعیِ مربی‌ها» ⇒ عنوان «چغر»، زیرعنوان «دستیار هوش مصنوعیِ مربی‌ها»
    idea = {
        "title": re.sub(r"\s+", " ", title).strip(), "subtitle": sub, "kicker": f.kicker, "number": n_txt if f.needs_number else "",
        "badge": prod.get("price_text", "") if prod and f.key == "new_product" else "",
        "tagline": "", "credits": "", "cta": "دیدن و سفارش" if prod and f.key in ("new_product", "product_offer") else "",
        "style": style, "formula": f.key, "formula_label": f.label, "source": "rules",
        "concept": CONCEPTS.get(style, "").format(t=head),
        "bg_prompt_en": bg_prompt(style),
        "mood": "",
        "label_a": "", "label_b": "",
    }
    if style == "cinema_poster":
        idea["tagline"] = "داستانی که باید دید"
        if store_name:
            idea["credits"] = f"یک تولیدِ {store_name}"
    if style == "versus" and other:
        a = left or phrases.clip(tp.main, 3)[0]
        idea["label_a"], idea["label_b"] = a, other
        idea["title"] = f"{a} یا {other}؟"
    if style == "split_ba":
        idea["label_a"], idea["label_b"] = "بعد", "قبل"
    return idea

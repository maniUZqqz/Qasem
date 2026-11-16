"""کتابخانهٔ قطعه‌های آماده (component library): هر «صحنه» یکی از این قطعه‌هاست؛ مدل فقط قطعه را برمی‌دارد و عددهایش را می‌گذارد.

هر قطعه: شناسه (همان کلیدِ `motion/remotion/src/registry.ts`)، نامِ فارسی، گروه، شمای پارامترها (نوع و سقفِ هر فیلد)، نمونهٔ معتبر (برای
بندانگشتی و آزمون)، کلیدواژه‌های «به‌کارِ چه چیزی می‌آید» (برای انتخابِ قطعه‌های مرتبط در پرامپت) و قاعدهٔ مدت.

انواعِ فیلد (kind): str (حداکثر طول) · num (کمینه/بیشینه) · int · bool · enum · ref (تصویرِ مجاز) · strs (فهرستِ متن) · objs (فهرستِ شیء با فیلدهای خودش).
یک آزمون (tests_lib.py) می‌سنجد که این فهرست با registry.ts یکی باشد، هر نمونه معتبر باشد و هر فیلد یک سقفِ طول داشته باشد.
"""
from __future__ import annotations

import json
from pathlib import Path

ICON_NAMES: tuple = ()
ICON_LABELS: dict = {}
EMOJI_NAMES: tuple = ()
EMOJI_LABELS: dict = {}
try:  # فهرستِ آیکون‌ها از همان فایلی می‌آید که موتورِ رندر می‌خواند (Lucide، مجوزِ ISC)
    _ic = json.loads((Path(__file__).resolve().parents[3] / "motion" / "remotion" / "src" / "icons.generated.json").read_text(encoding="utf-8"))
    ICON_NAMES = tuple(_ic["icons"].keys())
    ICON_LABELS = dict(_ic.get("labels") or {})
except (OSError, ValueError, KeyError):  # pragma: no cover - فایلِ تولیدشده در مخزن هست
    pass
try:  # ایموجی‌ها: گرافیکِ برداریِ Twemoji (CC-BY 4.0)، از همان فایلی که موتور می‌خواند
    _em = json.loads((Path(__file__).resolve().parents[3] / "motion" / "remotion" / "src" / "emoji.generated.json").read_text(encoding="utf-8"))
    EMOJI_NAMES = tuple(_em["emoji"].keys())
    EMOJI_LABELS = dict(_em.get("labels") or {})
except (OSError, ValueError, KeyError):  # pragma: no cover
    pass

PLATFORM_NAMES = ("instagram", "telegram", "whatsapp", "website", "youtube", "aparat", "eitaa", "rubika", "phone", "email", "app")
STICKER_KINDS = ("burst", "circle", "tag", "emoji")
STICKER_COLORS = ("accent", "accent2", "accent3")


def S(n: int, **kw) -> dict:
    return {"kind": "str", "max": n, **kw}


def N(lo: float, hi: float, **kw) -> dict:
    return {"kind": "num", "min": lo, "max": hi, **kw}


def I(lo: int, hi: int, **kw) -> dict:  # noqa: E743
    return {"kind": "int", "min": lo, "max": hi, **kw}


B = {"kind": "bool"}
REF = {"kind": "ref"}


def E(*choices, **kw) -> dict:
    return {"kind": "enum", "choices": tuple(choices), **kw}


def L(n: int, item: int = 100) -> dict:
    return {"kind": "strs", "max_items": n, "item_max": item}


def O(n: int, **fields) -> dict:  # noqa: E743
    return {"kind": "objs", "max_items": n, "fields": fields}


def _c(id, label, group, fields, sample, *, need=(), read=(), overlay=False, use="", about="", dur=(3, 5, 9), items=None):
    return {"id": id, "label": label, "group": group, "fields": fields, "sample": sample, "need": tuple(need), "read": tuple(read),
            "overlay": overlay, "use": use, "about": about, "dur": dur, "items": items}


COMPONENTS: dict = {}


def _add(*a, **k):
    c = _c(*a, **k)
    COMPONENTS[c["id"]] = c


# ───────────────────────────────────────────── ۹ نوعِ کلاسیکِ صحنه (فیلدها و سقف‌ها همان نسخهٔ ۱)
_add("title", "کارتِ عنوان", "scene", {"kicker": S(60), "title": S(140), "subtitle": S(220)},
     {"type": "title", "duration": 4, "kicker": "معرفی", "title": "عنوانِ ویدیوی شما", "subtitle": "یک جملهٔ کوتاه که مخاطب را نگه می‌دارد"},
     need=("title",), read=("kicker", "title", "subtitle"), use="عنوان شروع معرفی opening title intro headline", about="big title card: kicker, title, subtitle", dur=(3, 4, 6))
_add("list", "فهرست / مراحل", "scene", {"title": S(100), "items": L(6, 120), "numbered": B},
     {"type": "list", "duration": 7, "title": "سه قدمِ ساده", "items": ["قدمِ اول", "قدمِ دوم", "قدمِ سوم"], "numbered": True},
     need=("items",), read=("title", "items"), use="فهرست مراحل قدم نکته مزیت list steps benefits tips", about="titled list of short lines (numbered or bullets)", dur=(4, 7, 11))
_add("quote", "نقل‌قول", "scene", {"text": S(320), "author": S(80)},
     {"type": "quote", "duration": 5, "text": "جمله‌ای که می‌ارزد به یاد بماند.", "author": "نام"},
     need=("text",), read=("text", "author"), use="نقل قول جمله شعار quote slogan saying", about="one quotation with author", dur=(3, 5, 8))
_add("stat", "عددِ بزرگ", "scene", {"kicker": S(60), "value": S(24), "decimals": I(0, 3), "prefix": S(12), "suffix": S(12), "label": S(160), "count_up": B},
     {"type": "stat", "duration": 4, "kicker": "عدد", "value": "1300", "suffix": "+", "label": "توضیحِ عدد"},
     need=("value",), read=("kicker", "label"), use="عدد آمار تعداد درصد stat number count metric", about="one big counting number with label (value is a number string)", dur=(3, 4, 6))
_add("compare", "قبل و بعد", "scene", {"title": S(100), "before_label": S(24), "after_label": S(24), "before": S(140), "after": S(140), "before_image": REF, "after_image": REF},
     {"type": "compare", "duration": 6, "title": "قبل و بعد", "before_label": "قبل", "after_label": "بعد", "before": "وضعیتِ قبل", "after": "وضعیتِ بعد"},
     read=("title", "before_label", "after_label", "before", "after"), use="قبل بعد مقایسه تفاوت before after versus", about="two-panel before/after text comparison", dur=(4, 6, 9))
_add("product", "معرفیِ محصول", "scene", {"name": S(100), "price": S(40), "features": L(4, 120), "badge": S(30), "image": REF},
     {"type": "product", "duration": 6, "name": "نامِ محصول", "price": "", "features": ["ویژگیِ اول", "ویژگیِ دوم"], "badge": ""},
     need=("name",), read=("name", "price", "features", "badge"), use="محصول کالا ویژگی product showcase feature", about="product name, price, up to 4 features, optional photo", dur=(4, 6, 9))
_add("logo", "لوگو (استینگ)", "scene", {"title": S(80), "tagline": S(160)},
     {"type": "logo", "duration": 3, "tagline": "شعارِ برند"},
     read=("title", "tagline"), use="لوگو شعار برند پایان logo sting brand tagline", about="brand logo reveal with tagline", dur=(2, 3, 5))
_add("app", "نمایشِ اپ در قابِ گوشی", "scene", {"caption": S(120), "bullets": L(4, 120), "screenshot": REF},
     {"type": "app", "duration": 6, "caption": "اپِ شما، در یک نگاه", "bullets": ["قابلیتِ اول", "قابلیتِ دوم", "قابلیتِ سوم"]},
     need=("caption", "bullets"), read=("caption", "bullets"), use="اپ اپلیکیشن گوشی نرم افزار app screenshot phone mockup", about="phone frame with screenshot, caption and bullets", dur=(4, 6, 9))
_add("cta", "دعوت به اقدام", "scene", {"title": S(140), "button": S(40), "note": S(120)},
     {"type": "cta", "duration": 4, "title": "همین حالا شروع کنید", "button": "ثبت‌نام", "note": ""},
     need=("title",), read=("title", "button", "note"), use="دعوت ثبت نام خرید تماس پایان call to action signup buy end", about="closing call to action with button", dur=(3, 4, 6))

# ───────────────────────────────────────────── قطعه‌های داده
_add("bar_chart", "نمودارِ میله‌ایِ رشدکننده", "data",
     {"title": S(100), "bars": O(6, label=S(40), value=N(0, 1e9)), "unit": S(16), "show_values": B, "horizontal": B, "note": S(160)},
     {"type": "bar_chart", "duration": 6, "title": "مقایسهٔ سه گزینه", "bars": [{"label": "الف", "value": 40}, {"label": "ب", "value": 65}, {"label": "ج", "value": 90}], "unit": "٪"},
     need=("bars",), read=("title", "note"), items="bars", use="نمودار میله مقایسه هزینه توکن رشد آمار bar chart compare cost growth data", about="bars grow from zero; bars=[{label,value}] up to 6", dur=(4, 6, 9))
_add("line_chart", "نمودارِ خطیِ در حالِ کشیده‌شدن", "data",
     {"title": S(100), "points": O(8, label=S(24), value=N(-1e9, 1e9)), "unit": S(16), "note": S(160)},
     {"type": "line_chart", "duration": 6, "title": "روندِ ماهانه", "points": [{"label": "اول", "value": 10}, {"label": "دوم", "value": 25}, {"label": "سوم", "value": 22}, {"label": "چهارم", "value": 48}]},
     need=("points",), read=("title", "note"), items="points", use="نمودار خطی روند رشد زمان line chart trend over time", about="line draws itself; points=[{label,value}] up to 8", dur=(4, 6, 9))
_add("donut", "نمودارِ دونات", "data",
     {"title": S(100), "slices": O(5, label=S(40), value=N(0, 1e9)), "center_label": S(30)},
     {"type": "donut", "duration": 6, "title": "سهمِ هر بخش", "slices": [{"label": "الف", "value": 50}, {"label": "ب", "value": 30}, {"label": "ج", "value": 20}], "center_label": "کل"},
     need=("slices",), read=("title", "center_label"), items="slices", use="دونات دایره سهم درصد بخش donut pie share", about="donut/pie; slices=[{label,value}] up to 5", dur=(4, 6, 9))
_add("counter", "شمارنده با واحد", "data",
     {"kicker": S(60), "items": O(3, value=S(24), unit=S(16), label=S(60), decimals=I(0, 3)), "note": S(160)},
     {"type": "counter", "duration": 5, "kicker": "در یک نگاه", "items": [{"value": "1300", "unit": "+", "label": "حرکت"}, {"value": "60", "unit": "ثانیه", "label": "ساخت برنامه"}]},
     need=("items",), read=("kicker", "note"), items="items", use="شمارنده عدد واحد آمار counter numbers units", about="1-3 counting numbers with unit and label", dur=(3, 5, 8))
_add("progress_ring", "حلقهٔ پیشرفت", "data",
     {"title": S(100), "value": N(0, 100), "unit": S(8), "label": S(160)},
     {"type": "progress_ring", "duration": 5, "title": "پیشرفت", "value": 72, "label": "از مسیرِ هدف"},
     need=("value",), read=("title", "label"), use="حلقه پیشرفت درصد هدف ring progress percent goal", about="ring fills to value (0-100)", dur=(3, 5, 7))
_add("progress_bars", "نوارهای پیشرفت", "data",
     {"title": S(100), "items": O(5, label=S(40), value=N(0, 100))},
     {"type": "progress_bars", "duration": 6, "title": "مهارت‌ها", "items": [{"label": "قدرت", "value": 80}, {"label": "استقامت", "value": 60}, {"label": "انعطاف", "value": 45}]},
     need=("items",), read=("title",), items="items", use="نوار پیشرفت مهارت سطح درصد progress bars skills levels", about="labelled bars filling to 0-100", dur=(4, 6, 8))
_add("price_card", "کارتِ قیمت", "data",
     {"name": S(100), "price": S(24), "unit": S(24), "old_price": S(24), "badge": S(30), "features": L(5, 80), "button": S(40)},
     {"type": "price_card", "duration": 6, "name": "بستهٔ نمونه", "price": "۵۰۰", "unit": "تومان", "badge": "پیشنهاد", "features": ["ویژگیِ اول", "ویژگیِ دوم", "ویژگیِ سوم"], "button": "خرید"},
     need=("name",), read=("name", "price", "unit", "old_price", "badge", "features", "button"), use="قیمت بسته تعرفه تخفیف پلن مبلغ price pricing plan offer", about="price card; only use prices the user gave", dur=(4, 6, 9))
_add("comparison_table", "جدولِ مقایسه", "data",
     {"title": S(100), "columns": L(3, 24), "rows": O(6, label=S(40), values=L(3, 24)), "highlight": I(0, 2)},
     {"type": "comparison_table", "duration": 7, "title": "مقایسه", "columns": ["روشِ قدیمی", "با ما"], "rows": [{"label": "سرعت", "values": ["کند", "سریع"]}, {"label": "دقت", "values": ["کم", "زیاد"]}], "highlight": 1},
     need=("rows",), read=("title", "columns", "rows"), items="rows", use="جدول مقایسه ستون ردیف گزینه table compare columns rows", about="table; columns up to 3, rows=[{label,values[]}] up to 6, highlight=column index", dur=(5, 7, 10))
_add("before_after", "قبل و بعدِ تقسیم‌شونده", "data",
     {"title": S(100), "before": S(140), "after": S(140), "before_label": S(24), "after_label": S(24), "before_image": REF, "after_image": REF},
     {"type": "before_after", "duration": 6, "title": "تفاوت را ببینید", "before": "روشِ قبلی", "after": "روشِ تازه", "before_label": "قبل", "after_label": "بعد"},
     need=("before", "after"), read=("title", "before", "after", "before_label", "after_label"), use="قبل بعد تفاوت اسلایدر before after split reveal", about="wipe-split before/after with optional images", dur=(4, 6, 8))
_add("rating", "امتیاز و ستاره", "data",
     {"title": S(100), "score": N(0, 5), "count_label": S(120)},
     {"type": "rating", "duration": 4, "title": "رضایت", "score": 4.5, "count_label": "از نظرِ کاربران"},
     need=("score",), read=("title", "count_label"), use="امتیاز ستاره رضایت rating stars score", about="star rating; use only real scores the user gave", dur=(3, 4, 6))
_add("countdown", "شمارشِ معکوس", "data",
     {"label": S(100), "from": I(1, 10), "finish_text": S(40)},
     {"type": "countdown", "duration": 5, "label": "شروع تا", "from": 3, "finish_text": "شروع!"},
     read=("label", "finish_text"), use="شمارش معکوس شروع لانچ countdown launch timer", about="countdown from N with a finish word", dur=(3, 5, 8))

# ───────────────────────────────────────────── قطعه‌های متن و نمایش
_add("kinetic_title", "تیترِ کلمه‌به‌کلمه (کینتیک)", "text", {"kicker": S(60), "text": S(140), "title": S(140)},
     {"type": "kinetic_title", "duration": 4, "kicker": "ویژه", "text": "با چغر، چغر تر شو"},
     need=("text", "title"), read=("kicker", "text", "title"), use="تیتر کلمه حرکتی کینتیک شعار kinetic title words typography", about="headline whose WORDS pop one by one (never letters); syncs to narration", dur=(3, 4, 6))
_add("lower_third", "نوارِ نام و عنوان (Lower third)", "text", {"name": S(60), "role": S(60)},
     {"type": "lower_third", "duration": 4, "name": "نامِ شخص", "role": "سمت یا توضیح"},
     need=("name",), read=("name", "role"), overlay=True, use="نام سمت شخص گوینده lower third name title speaker", about="name+role bar; best as an overlay on another scene", dur=(3, 4, 6))
_add("checklist", "چک‌لیستِ تیک‌دار", "text", {"title": S(100), "items": L(6, 100)},
     {"type": "checklist", "duration": 6, "title": "چه چیزهایی دارد؟", "items": ["مورد اول", "مورد دوم", "مورد سوم"]},
     need=("items",), read=("title", "items"), items="items", use="چک لیست تیک موارد امکانات checklist ticks features", about="items get a drawn tick one after another", dur=(4, 6, 9))
_add("steps", "مراحل / خطِ زمان", "text", {"title": S(100), "steps": O(5, title=S(60), text=S(120)), "layout": E("horizontal", "vertical")},
     {"type": "steps", "duration": 7, "title": "چهار قدم", "steps": [{"title": "ثبت‌نام"}, {"title": "خریدِ توکن"}, {"title": "واردکردنِ اطلاعات"}, {"title": "تولیدِ برنامه"}]},
     need=("steps",), read=("title", "steps"), items="steps", use="مراحل قدم روند خط زمان timeline steps process how it works", about="numbered steps connected by a line; steps=[{title,text?}] up to 5", dur=(5, 7, 10))
_add("icon_grid", "شبکهٔ آیکون", "text", {"title": S(100), "items": O(6, icon=E(*ICON_NAMES), label=S(40))},
     {"type": "icon_grid", "duration": 6, "title": "امکانات", "items": [{"icon": "dumbbell", "label": "تمرین"}, {"icon": "salad", "label": "تغذیه"}, {"icon": "timer", "label": "سرعت"}, {"icon": "list-checks", "label": "خروجی"}]},
     need=("items",), read=("title", "items"), items="items", use="آیکون امکانات ویژگی شبکه icon grid features", about="grid of icon tiles with labels; icon must be a name from the icon list", dur=(4, 6, 9))
_add("feature_cards", "کارتِ ویژگی‌ها", "text", {"title": S(100), "cards": O(4, icon=E(*ICON_NAMES), title=S(60), text=S(120))},
     {"type": "feature_cards", "duration": 7, "title": "چرا؟", "cards": [{"icon": "zap", "title": "سریع", "text": "در کمتر از یک دقیقه"}, {"icon": "target", "title": "اختصاصی", "text": "برای هر ورزشکار"}]},
     need=("cards",), read=("title", "cards"), items="cards", use="ویژگی کارت مزیت دلیل feature cards benefits why", about="cards with icon, title and one line; up to 4", dur=(5, 7, 10))
_add("testimonial", "کارتِ نظرِ مشتری", "text", {"quote": S(320), "name": S(60), "role": S(60), "rating": I(0, 5), "image": REF},
     {"type": "testimonial", "duration": 6, "quote": "نظرِ واقعیِ یک کاربر (نمونه)", "name": "نام", "role": "سمت", "rating": 5},
     need=("quote",), read=("quote", "name", "role"), use="نظر مشتری تجربه رضایت testimonial review customer", about="customer quote card; NEVER invent testimonials", dur=(4, 6, 9))
_add("captions", "زیرنویسِ کلمه‌به‌کلمه", "text", {"title": S(60), "text": S(300), "size": N(30, 120)},
     {"type": "captions", "duration": 5, "text": "این جمله کلمه به کلمه زیرنویس می‌شود"},
     need=("text",), read=("text",), overlay=True, use="زیرنویس کپشن گفتار captions subtitles speech karaoke", about="caption track with the spoken word highlighted (uses narration cues)", dur=(3, 5, 10))
_add("sticker", "استیکر و آیکونِ پاپ", "text", {"kind": E(*STICKER_KINDS), "icon": E(*ICON_NAMES), "emoji": E(*EMOJI_NAMES), "color": E(*STICKER_COLORS), "text": S(20)},
     {"type": "sticker", "duration": 3, "kind": "burst", "emoji": "fire", "text": "جدید"},
     read=("text",), overlay=True, use="استیکر برچسب جدید تخفیف نشان ایموجی شکلک sticker badge new burst emoji", about="pop-in sticker (burst/circle/tag, or kind=emoji for a bouncing colour emoji) with a short text, an icon or an emoji name; overlay", dur=(2, 3, 5))
_add("social_cta", "دعوت در شبکهٔ اجتماعی", "text", {"title": S(140), "platform": E(*PLATFORM_NAMES), "handle": S(40), "note": S(80), "button": S(40)},
     {"type": "social_cta", "duration": 4, "title": "ما را دنبال کنید", "platform": "instagram", "handle": "example", "button": "دنبال کردن"},
     need=("handle", "title"), read=("title", "note", "button"), overlay=True, use="دنبال کردن اینستاگرام تلگرام آدرس سایت follow handle social website", about="handle + button; only handles/URLs the user gave", dur=(3, 4, 6))
_add("tags", "برچسب‌ها (تگ‌ها)", "text", {"title": S(100), "tags": L(10, 30)},
     {"type": "tags", "duration": 4, "title": "مناسبِ", "tags": ["باشگاه", "خانه", "مربی"]},
     need=("tags",), read=("title", "tags"), items="tags", use="برچسب هشتگ دسته tags hashtags categories", about="pill tags that pop in", dur=(3, 4, 6))
_add("ticker", "نوارِ متحرک (تیکر)", "text", {"text": S(160), "speed": N(0.3, 3)},
     {"type": "ticker", "duration": 4, "text": "پیشنهادِ ویژه — فقط همین هفته"},
     need=("text",), read=("text",), overlay=True, use="نوار متحرک خبر اعلان ticker marquee banner", about="scrolling text band; overlay or scene", dur=(3, 4, 8))
_add("image_hero", "تصویرِ تمام‌صفحه با عنوان", "text", {"kicker": S(60), "caption": S(140), "image": REF},
     {"type": "image_hero", "duration": 4, "kicker": "ویژه", "caption": "عنوانِ روی تصویر"},
     need=("caption",), read=("kicker", "caption"), use="عکس تمام صفحه تصویر محصول hero image full photo", about="full-bleed image with caption; needs an uploaded image for best result", dur=(3, 4, 6))

_add("brand_character", "شخصیتِ برند", "text",
     {"name": S(40), "text": S(160), "image_a": REF, "image_b": REF, "action": E("wave", "point", "thumbs", "explain", "think"), "arrive": E("left", "right", "bottom"), "side": E("left", "right"), "bubble": B},
     {"type": "brand_character", "duration": 6, "name": "شخصیتِ برند", "text": "سلام! بریم سراغِ نکتهٔ امروز", "action": "wave", "arrive": "left", "side": "right", "bubble": True},
     read=("name", "text"), overlay=True, use="شخصیت برند ماسکوت کاراکتر مربی سلام اشاره حباب گفتار brand character mascot waves points speech bubble",
     about="the brand character (two transparent pose stickers made in the brand-character section) enters, waves / points / thumbs-up and shows a speech bubble whose words appear when they are spoken; overlay or scene", dur=(3, 6, 10))

SCENE_IDS = tuple(COMPONENTS)
CLASSIC = ("title", "list", "quote", "stat", "compare", "product", "logo", "app", "cta")
OVERLAY_IDS = tuple(k for k, c in COMPONENTS.items() if c["overlay"])
GROUP_LABELS = {"scene": "صحنه‌های پایه", "data": "داده و نمودار", "text": "متن و نمایش"}
ITEM_MAX = 120


def get(cid: str):
    return COMPONENTS.get(cid)


def fa_name(cid: str) -> str:
    c = COMPONENTS.get(cid)
    return c["label"] if c else cid


def field_doc(spec: dict) -> str:
    """یک فیلد به‌صورتِ فشرده برای پرامپت: str<=60 · num 0..100 · enum a|b · [{label:str<=40,value:num}]x6"""
    k = spec["kind"]
    if k == "str":
        return f"str<={spec['max']}"
    if k in ("num", "int"):
        lo, hi = spec["min"], spec["max"]
        return f"{k} {lo:g}..{hi:g}" if hi < 1e8 else f"{k}"
    if k == "bool":
        return "bool"
    if k == "enum":
        ch = spec["choices"]
        return "|".join(ch) if len(ch) <= 8 else f"icon name ({len(ch)} choices)"
    if k == "ref":
        return "image ref (omit unless given)"
    if k == "strs":
        return f"[str<={spec['item_max']}]x{spec['max_items']}"
    if k == "objs":
        inner = ",".join(f"{n}:{field_doc(f)}" for n, f in spec["fields"].items())
        return f"[{{{inner}}}]x{spec['max_items']}"
    return k


def _public_fields(fields: dict) -> dict:
    out = {}
    for n, f in fields.items():
        d = {k: (list(v) if isinstance(v, tuple) else v) for k, v in f.items() if k != "fields"}
        if f["kind"] == "objs":
            d["fields"] = _public_fields(f["fields"])
        out[n] = d
    return out


def public_list() -> list:
    """برای API و رابطِ کاربری: فهرستِ قطعه‌ها با شمای فیلدها."""
    out = []
    for c in COMPONENTS.values():
        out.append({"id": c["id"], "label": c["label"], "group": c["group"], "group_label": GROUP_LABELS[c["group"]], "overlay": c["overlay"],
                    "fields": _public_fields(c["fields"]), "sample": c["sample"], "need": list(c["need"]),
                    "duration": {"min": c["dur"][0], "typical": c["dur"][1], "max": c["dur"][2]}, "about": c["about"]})
    return out

"""برازندگیِ هر سبک برای تبلیغِ فروشگاه: کدام تبلیغ، آیا برای عکسِ محصولِ واقعی مجاز است، و پیشنهادِ سبک برای هر نوعِ کسب‌وکار.

کارِ اختصاصیِ NM (در InstAI نیست). همه‌چیز قطعی و دست‌نویس است؛ هیچ آمار و ادعایی نیست، فقط «چرا می‌خورد».

* ``product_safe``: عکسی که محصولِ واقعیِ فروشگاه در آن می‌ماند (نوعِ «عکس محصول» و «بهبود عکس») نباید شکلِ محصول را عوض کند.
  فقط سبک‌های واقع‌گرا/نیمه‌واقع‌گرا که دست‌کم دو تکه‌دستورِ «صحنه و نور» دارند مجازند و فقط همان تکه‌ها به مدل می‌رسد
  (``scene_fragments``)؛ واژه‌های «بازطراحیِ خودِ سوژه» (خط‌دورِ ضخیم، سلی، نقاشی، پوست و چهره…) بیرون ریخته می‌شود.
* ``ad_fit``: کجا به کار می‌آید (عکسِ محصول، پوستر، پست، ریلز، استوری).
* ``suggest(store)``: ۳ تا ۵ سبکِ پیشنهادی از روی «نوعِ کسب‌وکار، توضیحات، مخاطب و رنگ‌های برند»ِ خودِ فروشگاه
  (برای «چغر» هم فقط از همین پروفایل؛ هیچ نگاشتِ ویژه‌ای برای یک فروشگاهِ خاص نیست).
"""
from __future__ import annotations

import colorsys
import re

from .schema import REALISM_ORDER

# ───────────────────────────── صحنه و نور (برای محصولِ واقعی)

#: واژه‌هایی که یعنی «صحنه، نور، فضا، رنگ‌بندی» — فقط تکه‌دستورهایی که یکی از این‌ها را دارند ماندنی‌اند
SCENE = re.compile(
    r"light|\blit\b|bokeh|depth of field|focus|haze|fog|mist|grain|vignette|colou?r grad|palette|shadow|contrast|reflection|atmosph|glow|\brim\b|"
    r"backdrop|background|\bsky\b|bloom|flare|anamorphic|exposure|35mm|\blens\b|volumetric|wet |neon|dusk|sunset|golden hour|moody|illumination|"
    r"steam|smoke|\brain\b|dust|colou?rs?\b|\btone\b|\bfilm\b")
#: واژه‌هایی که خودِ سوژه (محصول) را بازطراحی می‌کنند — اگر در یک تکه باشند آن تکه حذف می‌شود
DENY = re.compile(
    r"skin|\bfaces?\b|\beyes?\b|character|figure|portrait|people|person|puppet|outline|line ?art|linework|\bline\b|\bink\b|\bcel\b|halftone|brush|"
    r"paint|illustrat|drawing|sketch|cartoon|anime|comic|manga|\bflat\b|toon|clay|felt|plush|stitch|pixel|voxel|render|cgi|poly\b|vector|watercolou?r|"
    r"gouache|collage|paper|mosaic|woodblock|crayon|chalk|material|machinery|brass|copper|gears|signage|\bsigns?\b|cityscape|\bcity\b|miniature|toy")
#: سبک‌هایی که حتی با فیلتر، محصول را قاطی می‌کنند (نوردهیِ دوگانه سوژه را با صحنه می‌آمیزد؛ روتوسکوپ خطِ لرزان می‌دهد؛ لایه‌های پارالاکس کادر را می‌شکافند)
PRODUCT_BLOCK = {"double_exposure", "rotoscope_look", "layered_parallax_25d", "comic_ink", "tilt_shift_miniature"}
MIN_SCENE_FRAGMENTS = 2
#: واژه‌ای که همیشه به نورِ سبک اضافه می‌شود تا مدل شکلِ محصول را دست نزند
PRODUCT_GUARD = "the exact same product, unchanged shape, colour and branding"


def fragments(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def scene_fragments(style: dict) -> list[str]:
    """تکه‌دستورهای «صحنه و نور»ِ یک سبک (بدونِ هر واژه‌ای که محصول را بازطراحی کند)."""
    out: list[str] = []
    for f in fragments(style.get("image_positive", "")):
        low = f.lower()
        if SCENE.search(low) and not DENY.search(low) and f not in out:
            out.append(f)
    return out


def product_safe_of(key: str, style: dict) -> bool:
    """برای عکسِ محصولِ واقعی مجاز است؟ (واقع‌گرا/نیمه‌واقع‌گرا + دست‌کم دو تکهٔ صحنه/نور + خارج از فهرستِ مسدود)"""
    if key in PRODUCT_BLOCK:
        return False
    if REALISM_ORDER.index(style["realism"]) > REALISM_ORDER.index("semi_realistic"):
        return False
    return len(scene_fragments(style)) >= MIN_SCENE_FRAGMENTS


#: دستی: سبک‌هایی که فقط برای ویدیو/متن‌حرکتی‌اند
AD_FIT_OVERRIDES = {
    "kinetic_typography": ["reel", "story"],
    "terminal_ascii": ["reel", "story"],
}


def ad_fit_of(key: str, style: dict) -> list[str]:
    if key in AD_FIT_OVERRIDES:
        return list(AD_FIT_OVERRIDES[key])
    suit = style.get("suitability") or []
    fit: list[str] = []
    if style.get("product_safe"):
        fit.append("product_photo")
    vertical = (style.get("gen") or {}).get("aspect") == "9:16"       # «استوری» عمودی است؛ سبکی که طبیعتاً افقی/مربع است برایش توصیه نمی‌شود
    if "image" in suit:
        fit += ["poster", "social_post"]
        if vertical:
            fit.append("story")
    if "video" in suit:
        fit.append("reel")
    return fit


def with_fit(key: str, style: dict) -> dict:
    """ردیفِ سبک + ``product_safe`` و ``ad_fit``."""
    s = dict(style)
    s["product_safe"] = product_safe_of(key, s)
    s["ad_fit"] = ad_fit_of(key, s)
    return s


# ───────────────────────────── پیشنهاد برای هر نوعِ کسب‌وکار

#: (کلید، عنوانِ فارسی، واژه‌های کلیدی، [(سبک، چرا می‌خورد)])
BUSINESS = [
    ("tech", "نرم‌افزار و فناوری", ("نرم افزار", "اپلیکیشن", "اپ ", "دیجیتال", "موبایل", "لپ تاپ", "کامپیوتر", "فناوری", "تکنولوژی", "سایت", "هوش مصنوعی", "برنامه نویسی", "software", "app"),
     [("flat_vector_motion", "تصویرسازیِ تخت و تمیز؛ برای توضیحِ یک سرویس یا اپ ساده و خوانا می‌ماند"),
      ("glassmorphism_ui", "شیشهٔ مات و نرم؛ ظاهرِ آشنای رابط‌های امروزی"),
      ("isometric_diorama", "مینیاتورِ سه‌بعدیِ مرتب؛ برای نشان‌دادنِ یک سامانه با اجزای کوچک"),
      ("cgi_motion_graphics", "سه‌بعدیِ براق و مدرن؛ برای آگهیِ جدی و حرفه‌ای"),
      ("blueprint_technical", "نقشهٔ فنی؛ حسِ دقت و مهندسی")]),
    ("fitness", "ورزش و تناسب اندام", ("ورزش", "باشگاه", "مربی", "تناسب", "بدنسازی", "تمرین", "تغذیه ورزشی", "یوگا", "دویدن", "fitness", "gym"),
     [("cinematic_realistic", "نورِ سینمایی و عمقِ میدانِ کم؛ تصویرِ جدی و انگیزشی"),
      ("duotone_gradient", "دو رنگِ پرکنتراست؛ پوسترِ پرانرژی و ساده"),
      ("neo_brutalism", "کادرهای خام و ضخیم؛ حسِ قدرت و صراحت"),
      ("constructivist_poster", "قطرهای تند و رنگِ محدود؛ شکلِ پوسترهای تبلیغاتیِ قدیمی با انرژی"),
      ("pop_art_halftone", "نقطه‌های چاپی و رنگِ تند؛ جوان و پرجنب‌وجوش")]),
    ("fashion", "پوشاک و مد", ("پوشاک", "لباس", "مد ", "مانتو", "کفش", "کیف", "شلوار", "پیراهن", "روسری", "فشن", "clothing", "fashion"),
     [("duotone_gradient", "دو رنگِ مدرن؛ مناسبِ پوسترِ فصل و کالکشن"),
      ("pop_art_halftone", "رنگِ تند و نقطه‌های چاپی؛ نگاهِ جوان"),
      ("art_deco_gilded", "خطوطِ زراندود و متقارن؛ حسِ لوکس"),
      ("y2k_bubble_chrome", "کروم و حباب؛ حسِ مدِ اوایلِ دههٔ ۲۰۰۰"),
      ("cinematic_realistic", "نورِ فیلم؛ عکسِ مجله‌ای")]),
    ("food", "غذا، کافه و قنادی", ("غذا", "رستوران", "کافه", "قنادی", "شیرینی", "نان", "آشپز", "قهوه", "فست فود", "کیک", "چای", "عسل", "میوه", "food", "cafe"),
     [("documentary_real", "نورِ طبیعیِ گرم؛ غذا همان‌طور که هست دیده می‌شود"),
      ("gouache_storybook", "گواشِ نرم و رنگارنگ؛ حسِ دست‌ساز و صمیمی"),
      ("groovy_70s", "رنگ‌های گرم و گردِ دههٔ هفتاد؛ اشتهاآور و شاد"),
      ("linocut_print", "چاپِ دستی؛ حسِ سنتی و محلی"),
      ("paper_collage", "کولاژِ کاغذی؛ ساده و خوش‌رنگ")]),
    ("beauty", "زیبایی و مراقبت", ("زیبایی", "آرایش", "سالن", "مو ", "پوست", "عطر", "ناخن", "کرم", "لاک", "beauty", "cosmetic"),
     [("photoreal_cgi", "بازتابِ نرم و روشنایی استودیویی؛ ظاهرِ تبلیغِ محصولِ مراقبتی"),
      ("art_nouveau_botanical", "خطوطِ گیاهیِ ظریف؛ حسِ لطیف"),
      ("holographic_foil", "درخششِ رنگین‌کمانی؛ مدرن و جذاب"),
      ("kawaii_pastel", "پاستلیِ نرم؛ شاد و ملایم"),
      ("duotone_gradient", "دو رنگِ ملایم؛ تمیز و ساده")]),
    ("jewelry", "طلا، جواهر و لوکس", ("طلا", "جواهر", "زیورآلات", "ساعت", "نقره", "لوکس", "الماس", "jewel", "luxury"),
     [("art_deco_gilded", "زراندود و متقارن؛ حسِ شکوه"),
      ("photoreal_cgi", "بازتاب‌های دقیق؛ فلز و سنگ درخشان دیده می‌شود"),
      ("noir_bw", "سیاه‌وسفیدِ پرکنتراست؛ جدی و گران‌قیمت"),
      ("chrome_metal_type", "کرومِ براق؛ حسِ فلز"),
      ("persian_miniature", "ریزه‌کاریِ ایرانی؛ سنتی و ارزشمند")]),
    ("kids", "کودک و اسباب‌بازی", ("کودک", "اسباب بازی", "نوزاد", "مهدکودک", "بچه", "عروسک", "toy", "kids"),
     [("kids_crayon_doodle", "مدادشمعیِ کودکانه؛ ساده و شاد"),
      ("claymation_stopmotion", "خمیرِ بازی؛ لمس‌کردنی و بامزه"),
      ("felt_plush_stopmotion", "نمد و پارچه؛ نرم و گرم"),
      ("kawaii_pastel", "پاستلی و گرد؛ مناسبِ نوزاد"),
      ("toy_brick_3d", "بلوک‌های رنگی؛ بازیگوش")]),
    ("handmade", "صنایع دستی و هنر", ("صنایع دستی", "سفال", "فرش", "گلیم", "هنر", "نقاشی", "گالری", "قلمکار", "منبت", "خوشنویسی", "handmade", "craft"),
     [("persian_miniature", "نگارگریِ ایرانی؛ هم‌خوان با هنرِ سنتی"),
      ("paper_cutout", "برشِ کاغذی؛ دست‌ساز و ساده"),
      ("mosaic_tiles", "موزاییک و کاشی؛ نقشِ تکرارشونده"),
      ("embroidery_textile", "گلدوزی؛ حسِ بافت و نخ"),
      ("stained_glass", "شیشهٔ رنگی؛ رنگ‌های روشن و خطوطِ تیره")]),
    ("home", "خانه، دکور و ساختمان", ("مبلمان", "دکور", "خانه", "لوازم خانگی", "ساختمان", "املاک", "کابینت", "فرش", "پرده", "تزئینات", "furniture", "decor"),
     [("isometric_diorama", "مینیاتورِ سه‌بعدیِ اتاق؛ چیدمان دیده می‌شود"),
      ("midcentury_modern_2d", "گرافیکِ مدرنِ نیمهٔ قرن؛ تمیز و گرم"),
      ("bauhaus_geometric", "هندسهٔ ساده؛ نظمِ خانه"),
      ("photoreal_cgi", "رندرِ نزدیک به عکس؛ مواد و نور واقعی"),
      ("low_poly_3d", "سه‌بعدیِ ساده؛ مناسبِ نقشه و طرح")]),
    ("travel", "گردشگری و سفر", ("گردشگری", "سفر", "هتل", "آژانس", "تور", "اقامتگاه", "travel", "hotel"),
     [("vintage_travel_poster", "پوسترِ سفرِ قدیمی؛ مقصد را زیبا نشان می‌دهد"),
      ("watercolour_storybook", "آبرنگِ نرم؛ حسِ آرامش"),
      ("cineview_widescreen", "کادرِ عریضِ سینمایی؛ منظره پرشکوه می‌شود"),
      ("impressionist_oil", "رنگ‌روغنِ نرم؛ منظره‌ها دل‌نشین می‌شود"),
      ("ukiyoe_woodblock", "چاپِ دستیِ ژاپنی؛ برای مقصدهای دور")]),
    ("education", "آموزش و کتاب", ("آموزش", "کلاس", "دوره", "کتاب", "مدرسه", "دانشگاه", "مشاوره", "کتابفروشی", "course", "education"),
     [("whiteboard_explainer", "طرحِ دست‌نویس؛ توضیحِ ساده و قدم‌به‌قدم"),
      ("chalkboard_classroom", "تختهٔ کلاس؛ حسِ آموزش"),
      ("infographic_data", "نمودار و نشان؛ مناسبِ نشان‌دادنِ مراحل"),
      ("flat_vector_motion", "تصویرسازیِ تخت؛ خوانا و ساده"),
      ("corporate_flat_people", "آدم‌های ساده و تخت؛ پیامِ رسمی و دوستانه")]),
    ("auto", "خودرو، ابزار و صنعت", ("خودرو", "ماشین", "ابزار", "صنعتی", "قطعات", "لاستیک", "تعمیرگاه", "موتور", "car", "tools"),
     [("blueprint_technical", "نقشهٔ فنی؛ حسِ دقت"),
      ("photoreal_cgi", "رندرِ نزدیک به عکس؛ فلز و بازتاب"),
      ("cgi_motion_graphics", "سه‌بعدیِ براق؛ مدرن"),
      ("neo_brutalism", "طراحیِ خام و ضخیم؛ حسِ سختی و استقامت"),
      ("steampunk_brass", "برنج و چرخ‌دنده؛ مکانیکی و قدیمی")]),
    ("entertainment", "موسیقی، بازی و رویداد", ("موسیقی", "کنسرت", "رویداد", "بازی", "گیم", "سرگرمی", "جشن", "music", "game", "event"),
     [("vaporwave_synth", "غروبِ نئونی؛ شبِ شاد"),
      ("neon_sign_glow", "تابلوی نئونی؛ جلبِ توجه"),
      ("pixel_art_16bit", "پیکسلی؛ برای بازی و سرگرمی"),
      ("graffiti_street", "گرافیتی؛ جوان و خیابانی"),
      ("glitch_datamosh", "خرابیِ دیجیتال؛ تند و مدرن")]),
    ("health", "سلامت و درمان", ("پزشک", "سلامت", "دندان", "درمانگاه", "دارو", "داروخانه", "درمان", "clinic", "health"),
     [("flat_vector_motion", "تصویرسازیِ تخت و آرام؛ مناسبِ پیامِ سلامت"),
      ("corporate_flat_people", "آدم‌های ساده؛ لحنِ دوستانه و رسمی"),
      ("infographic_data", "نشان و نمودار؛ توضیحِ مراحل"),
      ("watercolour_storybook", "آبرنگِ نرم؛ آرامش‌بخش"),
      ("line_art_mono", "خطِ ساده و تک‌رنگ؛ تمیز")]),
]

#: وقتی هیچ واژهٔ کلیدی نخورد (یا پروفایل خالی است): انتخاب‌های عمومی که با هر کسب‌وکاری می‌خورند
GENERIC = ("عمومی", [("flat_vector_motion", "تصویرسازیِ تخت و خوانا؛ برای هر پیامی کار می‌کند"),
                      ("cinematic_realistic", "نورِ سینمایی؛ تصویرِ جدی و حرفه‌ای"),
                      ("duotone_gradient", "دو رنگ؛ ساده و پرکنتراست"),
                      ("pop_art_halftone", "رنگِ تند؛ جلبِ توجه"),
                      ("paper_collage", "کولاژِ کاغذی؛ دست‌ساز و دوستانه")])

_AR = str.maketrans({"ي": "ی", "ك": "ک", "‌": " ", "ـ": "", "-": " "})


def fold(text: str) -> str:
    """حروفِ عربی/فارسی و نیم‌فاصله یکی می‌شود (جست‌وجو و واژه‌یابی)."""
    t = str(text or "").translate(_AR).lower()
    return t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def _score(text: str, words: tuple[str, ...]) -> int:
    t = f" {fold(text)} "
    return sum(1 for w in words if fold(w) in t)


def _profile_texts(store) -> dict[str, str]:
    prof = getattr(store, "profile", None)
    vis = getattr(prof, "visual_preferences", None) or {}
    return {
        "business_type": getattr(store, "business_type", "") or "",
        "description": getattr(store, "description", "") or "",
        "target_audience": getattr(store, "target_audience", "") or "",
        "visual": " ".join(str(v) for v in vis.values() if isinstance(v, (str, int))) if isinstance(vis, dict) else "",
    }


def business_matches(store) -> list[tuple[int, tuple]]:
    """گروه‌های کسب‌وکارِ فروشگاه، به ترتیبِ امتیاز. نوعِ کسب‌وکار ۳ برابر، توضیحات و مخاطب ۱ برابر."""
    t = _profile_texts(store)
    scored = []
    for row in BUSINESS:
        s = 3 * _score(t["business_type"], row[2]) + _score(t["description"], row[2]) + _score(t["target_audience"], row[2]) + _score(t["visual"], row[2])
        if s:
            scored.append((s, row))
    scored.sort(key=lambda x: (-x[0], [r[0] for r in BUSINESS].index(x[1][0])))
    return scored


def _hex_rgb(c: str) -> tuple[float, float, float]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def brand_primary(store) -> str:
    colors = getattr(store, "colors", None)
    vals: list = []
    if isinstance(colors, dict):
        vals = [colors.get(k) for k in ("primary", "main", "brand", "secondary")] + list(colors.values())
    elif isinstance(colors, (list, tuple)):
        vals = list(colors)
    for v in vals:
        if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v.strip()):
            return v.strip().upper()
    return ""


def nearest_themes(color: str, themes: dict[str, dict], n: int = 2) -> list[str]:
    """تم‌هایی که رنگِ اصلیِ آن‌ها به رنگِ برند نزدیک‌تر است (فاصلهٔ فام و روشنایی)."""
    if not color:
        return []
    h, s, v = colorsys.rgb_to_hsv(*_hex_rgb(color))

    def dist(key: str) -> float:
        pal = themes[key]["palette"]
        if len(pal) < 2:
            return 9.0
        h2, s2, v2 = colorsys.rgb_to_hsv(*_hex_rgb(pal[1]))
        dh = min(abs(h - h2), 1 - abs(h - h2))
        return dh * 4 + abs(s - s2) * 0.6 + abs(v - v2) * 0.6
    return sorted(themes, key=dist)[:n]

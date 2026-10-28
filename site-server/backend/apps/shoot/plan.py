"""تحلیلِ محصول ⇐ برنامهٔ عکاسی و فیلم‌برداری (shot plan).

یک برنامه = نوعِ محصول و ویژگی‌های فروش + فهرستِ مرتبِ «زاویه‌های عکس» + «نماهای ویدیو» (حرکت، مدت، سرعت،
فاصله) + متنِ تبلیغ. هر قلم یک دستورِ کوتاهِ فارسی، یک مشخصهٔ «فلش/نمودار» برای پنل (overlay) و یک «شرطِ قبول»
(check) دارد.

هوش مصنوعی (بینایی + متن، از دروازهٔ services.ai.gateway) پیشنهاد می‌دهد، ولی هیچ‌چیزِ خروجیِ مدل مستقیم به
پنل نمی‌رسد: `validate_plan` هر قلم را با فهرستِ بستهٔ زاویه‌ها و حرکت‌ها می‌سنجد، عددها را محدود می‌کند، دستورِ
خالی یا بلند را با دستورِ قطعیِ همان زاویه عوض می‌کند و اگر چیزی کم بود از «الگوی آمادهٔ همان دسته» پر می‌کند.
بی‌هوش مصنوعی هم (`template_plan`) همیشه یک برنامهٔ کامل هست.
"""
from __future__ import annotations

import base64
import io
import logging
import re

logger = logging.getLogger(__name__)

PLAN_VERSION = 1
MAX_PHOTOS = 9
MAX_VIDEO = 6
MIN_PHOTOS = 3
MIN_VIDEO = 2

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).translate(_FA_DIGITS)


DIRECTION_FA = {"right": "راست", "left": "چپ", "up": "بالا", "down": "پایین"}

# ───────────────────────────── زاویه‌های عکس

#: yaw = جای گوشی دورِ محصول نسبت به روبه‌رو (درجه، مثبت = راست)، pitch = ارتفاع (۰ هم‌سطح، ۹۰ بالای سر)
ANGLES: dict[str, dict] = {
    "front": dict(title="روبه‌رو", yaw=0, pitch=0, distance="medium", arrow="none",
                  instruction="گوشی را صاف و روبه‌روی محصول، هم‌ارتفاعِ وسطش بگیر؛ محصول وسطِ کادر باشد.",
                  check=dict(min_fill=0.12, max_fill=0.92, centered=True)),
    "three_quarter": dict(title="۴۵ درجه", yaw=45, pitch=10, distance="medium", arrow="orbit_right",
                          instruction="از روبه‌رو، گوشی را ۴۵ درجه به راست ببر و دوباره رو به محصول بگیر.",
                          check=dict(min_fill=0.12, max_fill=0.92, centered=True)),
    "side": dict(title="پهلو", yaw=90, pitch=0, distance="medium", arrow="orbit_right",
                 instruction="۹۰ درجه به راست برو تا محصول را از پهلو ببینی؛ گوشی هم‌ارتفاعِ محصول.",
                 check=dict(min_fill=0.1, max_fill=0.92, centered=True)),
    "back": dict(title="پشت", yaw=180, pitch=0, distance="medium", arrow="orbit_right",
                 instruction="محصول را ۱۸۰ درجه بچرخان (یا پشتش برو) و پشتِ آن را صاف بگیر.",
                 check=dict(min_fill=0.12, max_fill=0.92, centered=True)),
    "top": dict(title="از بالا", yaw=0, pitch=90, distance="medium", arrow="up",
                instruction="گوشی را بالای محصول ببر و صاف رو به پایین بگیر (موازیِ میز).",
                check=dict(min_fill=0.1, max_fill=0.92, centered=True)),
    "detail": dict(title="جزئیات (نزدیک)", yaw=20, pitch=15, distance="close", arrow="in",
                   instruction="تا حدودِ ۱۵ سانتی‌متری نزدیک شو و از جنس و جزئیات عکس بگیر؛ روی همان نقطه ضربه بزن تا فوکوس شود.",
                   check=dict(min_fill=0.0, max_fill=1.0, centered=False)),
    "label": dict(title="برچسب و لوگو", yaw=0, pitch=0, distance="close", arrow="in",
                  instruction="برچسب یا لوگو را صاف و خوانا بگیر؛ نورِ چراغ رویش برق نزند.",
                  check=dict(min_fill=0.0, max_fill=1.0, centered=False)),
    "scale": dict(title="در دست (اندازه)", yaw=0, pitch=10, distance="medium", arrow="none",
                  instruction="محصول را در دست بگیر تا اندازه‌اش معلوم شود؛ دست و محصول هر دو در کادر.",
                  check=dict(min_fill=0.1, max_fill=0.95, centered=True)),
    "lifestyle": dict(title="در محیطِ استفاده", yaw=30, pitch=15, distance="far", arrow="out",
                      instruction="محصول را جایی بگذار که استفاده می‌شود (میز، اتاق، دست) و از کمی دورتر بگیر.",
                      check=dict(min_fill=0.03, max_fill=1.0, centered=False)),
}

# ───────────────────────────── حرکت‌های ویدیو

MOVES: dict[str, dict] = {
    "orbit": dict(title="چرخش دورِ محصول", duration=5, speed="slow", distance_cm=40, degrees=90, direction="right"),
    "push_in": dict(title="نزدیک شدن", duration=4, speed="slow", distance_cm=60, direction="in"),
    "pull_out": dict(title="دور شدن", duration=4, speed="slow", distance_cm=25, direction="out"),
    "pan": dict(title="چرخشِ افقیِ گوشی (پَن)", duration=4, speed="slow", distance_cm=50, direction="right"),
    "tilt": dict(title="چرخشِ عمودیِ گوشی (تیلت)", duration=4, speed="slow", distance_cm=40, direction="up"),
    "reveal": dict(title="نمایانی (ریویل)", duration=4, speed="medium", distance_cm=40, direction="right"),
    "hand": dict(title="کار با دست", duration=5, speed="medium", distance_cm=35, direction="none"),
}
SPEED_FA = {"slow": "آرام", "medium": "معمولی", "fast": "تند"}


def _arrow_for(move: str, direction: str) -> str:
    if move == "orbit":
        return "orbit_left" if direction == "left" else "orbit_right"
    if move == "push_in":
        return "in"
    if move == "pull_out":
        return "out"
    if move in ("pan", "reveal"):
        return "left" if direction == "left" else "right"
    if move == "tilt":
        return "down" if direction == "down" else "up"
    return "none"


def move_instruction(shot: dict) -> str:
    """دستورِ قطعیِ فارسی برای یک نما (وقتی مدل چیزی نداد یا بد داد)."""
    move = shot["move"]
    sec = fa_num(shot["duration"])
    speed = SPEED_FA.get(shot.get("speed", "slow"), "آرام")
    direction = DIRECTION_FA.get(shot.get("direction", "right"), "راست")
    dist = fa_num(shot.get("distance_cm") or 40)
    if move == "orbit":
        return (f"{speed} {fa_num(shot.get('degrees') or 90)} درجه دورِ محصول به {direction} بچرخ، {sec} ثانیه؛ "
                f"فاصله را حدودِ {dist} سانتی‌متر ثابت نگه دار.")
    if move == "push_in":
        return f"از حدودِ {dist} سانتی‌متری، {speed} به محصول نزدیک شو تا کادر پر شود؛ {sec} ثانیه."
    if move == "pull_out":
        return f"از نزدیک (حدودِ {dist} سانتی‌متر) شروع کن و {speed} عقب برو تا کلِ محصول دیده شود؛ {sec} ثانیه."
    if move == "pan":
        return f"خودت جابه‌جا نشو؛ فقط گوشی را {speed} به {direction} بچرخان تا محصول از کنار وارد کادر شود؛ {sec} ثانیه."
    if move == "tilt":
        start = "پایین" if shot.get("direction") != "down" else "بالا"
        return f"گوشی را از {start}ِ محصول شروع کن و {speed} به {direction} بچرخان؛ {sec} ثانیه."
    if move == "reveal":
        return (f"اول دستت (یا یک کاغذ) جلوی دوربین باشد، بعد {speed} به {direction} کنار برو تا محصول نمایان شود؛ "
                f"{sec} ثانیه.")
    action = shot.get("action") or "بچرخان یا استفاده کن"
    return f"گوشی را ثابت نگه دار و با دستِ دیگر محصول را {action}؛ {sec} ثانیه."


def move_cues(shot: dict) -> list[dict]:
    """راهنمای «حینِ ضبط» (ثانیه ⇐ جمله)."""
    move, d = shot["move"], float(shot["duration"])
    mid = round(d / 2, 1)
    middle = {
        "orbit": "همین‌طور آرام بچرخ…",
        "push_in": "آرام نزدیک‌تر شو…",
        "pull_out": "آرام عقب‌تر برو…",
        "pan": "آرام بچرخان…",
        "tilt": "آرام ادامه بده…",
        "reveal": "حالا کنار برو…",
        "hand": "آرام، بی‌عجله…",
    }.get(move, "ادامه بده…")
    cues = [{"at": 0.0, "text": "شروع"}, {"at": mid, "text": middle}]
    if d >= 4:
        cues.append({"at": round(max(mid + 0.5, d - 1.2), 1), "text": "ثابت بمان، تقریباً تمام"})
    return cues


# ───────────────────────────── دسته‌ها و الگوهای آماده

CATEGORIES = {
    "generic": "کالای عمومی", "apparel": "پوشاک", "shoes": "کفش", "cosmetics": "آرایشی و بهداشتی",
    "electronics": "لوازمِ الکترونیکی", "food": "خوراکی و نوشیدنی", "jewelry": "زیورآلات و ساعت",
    "home": "خانه و دکور", "bag": "کیف و چمدان",
}

KEYWORDS = {
    "apparel": ["پیراهن", "تیشرت", "تی‌شرت", "لباس", "شلوار", "مانتو", "کت", "هودی", "دامن", "پلیور", "ژاکت", "روسری",
                "شال", "جوراب", "shirt", "dress", "hoodie", "jacket", "pants", "scarf"],
    "shoes": ["کفش", "کتانی", "صندل", "بوت", "دمپایی", "shoe", "sneaker", "boot", "sandal"],
    "cosmetics": ["کرم", "سرم", "رژ", "عطر", "ادکلن", "شامپو", "لوسیون", "آرایش", "ماسک", "صابون", "ریمل", "perfume",
                  "cream", "serum", "lotion", "shampoo", "lipstick"],
    "electronics": ["گوشی", "هدفون", "هندزفری", "شارژر", "کابل", "اسپیکر", "لپ‌تاپ", "لپتاپ", "موس", "کیبورد", "پاوربانک",
                    "ساعت هوشمند", "phone", "headphone", "earbud", "charger", "speaker", "laptop", "mouse", "keyboard"],
    "food": ["قهوه", "چای", "عسل", "شکلات", "خشکبار", "ادویه", "زعفران", "کیک", "نان", "غذا", "آجیل", "خرما", "کلوچه",
             "مربا", "روغن", "coffee", "tea", "honey", "chocolate", "spice", "cake"],
    "jewelry": ["انگشتر", "گردنبند", "دستبند", "گوشواره", "طلا", "نقره", "ساعت", "جواهر", "ring", "necklace", "bracelet",
                "earring", "watch", "jewel"],
    "home": ["گلدان", "ظرف", "لیوان", "ماگ", "فرش", "کوسن", "چراغ", "شمع", "دکور", "قاب", "بشقاب", "vase", "mug", "lamp",
             "candle", "decor"],
    "bag": ["کیف", "کوله", "چمدان", "bag", "backpack", "wallet", "suitcase"],
}

TEMPLATES: dict[str, dict] = {
    "generic": {
        "photos": ["front", "three_quarter", "side", "back", "top", "detail", "label", "scale", "lifestyle"],
        "video": [("push_in", {}), ("orbit", {"degrees": 90}), ("hand", {"action": "بچرخان تا همهٔ جهت‌ها دیده شود"}),
                  ("pull_out", {})],
        "setup": {"background": "زمینهٔ سادهٔ روشن (کاغذ یا پارچهٔ سفید/کرم)",
                  "lighting": "نورِ نرمِ پنجره از کنار؛ فلاش خاموش"},
    },
    "apparel": {
        "photos": ["front", "back", "three_quarter", "detail", "label", "lifestyle"],
        "video": [("reveal", {}), ("tilt", {"direction": "down", "duration": 5}), ("push_in", {"duration": 3}),
                  ("hand", {"action": "بکش یا تا کن تا جنسِ پارچه دیده شود"})],
        "setup": {"background": "دیوارِ ساده یا رگال؛ لباس صاف و اتوشده",
                  "lighting": "نورِ روزِ کنارِ پنجره؛ سایهٔ تند نباشد"},
    },
    "shoes": {
        "photos": ["side", "three_quarter", "front", "back", "top", "detail", "lifestyle"],
        "video": [("orbit", {"degrees": 180, "duration": 6}), ("push_in", {}),
                  ("hand", {"action": "بردار و کفِ آن را نشان بده"}), ("pull_out", {})],
        "setup": {"background": "سطحِ ساده (چوب یا کاغذِ روشن)؛ بند را مرتب کن",
                  "lighting": "نورِ نرم از جلو-کنار"},
    },
    "cosmetics": {
        "photos": ["front", "three_quarter", "back", "label", "detail", "scale", "lifestyle"],
        "video": [("push_in", {}), ("orbit", {"degrees": 180, "duration": 6}),
                  ("hand", {"action": "در را باز کن و کمی از محصول را روی دست نشان بده"}), ("reveal", {})],
        "setup": {"background": "سطحِ براق یا سنگیِ روشن؛ چند برگ یا حوله برای حال‌وهوا",
                  "lighting": "نورِ نرم؛ مراقبِ بازتابِ چراغ روی بطری باش"},
    },
    "electronics": {
        "photos": ["front", "three_quarter", "back", "side", "detail", "top", "scale", "lifestyle"],
        "video": [("reveal", {}), ("orbit", {"degrees": 180, "duration": 6}),
                  ("hand", {"action": "روشن کن یا دکمه‌اش را بزن"}), ("push_in", {"duration": 3})],
        "setup": {"background": "سطحِ تیره یا خاکستریِ ساده؛ گردگیری‌شده",
                  "lighting": "نورِ نرم از کنار؛ اثرِ انگشت روی بدنه نباشد"},
    },
    "food": {
        "photos": ["top", "three_quarter", "front", "detail", "scale", "lifestyle"],
        "video": [("tilt", {"direction": "down"}), ("push_in", {}),
                  ("hand", {"action": "بریز، بردار یا سرو کن"}), ("pull_out", {})],
        "setup": {"background": "میزِ چوبی یا پارچهٔ کتان؛ یک فنجان یا ظرفِ ساده کنارش",
                  "lighting": "نورِ گرمِ پنجره از پشت-کنار"},
    },
    "jewelry": {
        "photos": ["front", "three_quarter", "detail", "scale", "lifestyle"],
        "video": [("orbit", {"degrees": 360, "duration": 8}), ("push_in", {}),
                  ("hand", {"action": "به دست کن یا آرام بچرخان تا برق بزند"}), ("tilt", {})],
        "setup": {"background": "مخمل یا پارچهٔ تیره؛ سطحِ کاملاً تمیز",
                  "lighting": "یک نورِ کوچکِ کناری برای درخشش"},
    },
    "home": {
        "photos": ["front", "three_quarter", "side", "detail", "lifestyle", "scale"],
        "video": [("pull_out", {}), ("pan", {}), ("orbit", {"degrees": 90}), ("hand", {"action": "استفاده کن"})],
        "setup": {"background": "گوشه‌ای از خانه که به محصول می‌آید",
                  "lighting": "نورِ طبیعیِ روز"},
    },
    "bag": {
        "photos": ["front", "three_quarter", "side", "back", "detail", "top", "scale", "lifestyle"],
        "video": [("orbit", {"degrees": 180, "duration": 6}), ("hand", {"action": "زیپ را باز کن و داخلش را نشان بده"}),
                  ("push_in", {}), ("reveal", {})],
        "setup": {"background": "سطح یا دیوارِ ساده؛ کیف را کمی پُر کن تا فرمش بماند",
                  "lighting": "نورِ نرمِ پنجره"},
    },
}

GENERAL_TIPS = [
    "لنزِ گوشی را با پارچهٔ نرم تمیز کن.",
    "گوشی را عمودی بگیر؛ ویدیو برای استوری و ریلز است.",
    "حرکت‌ها آرام باشد؛ تند بچرخی تار می‌شود.",
]


def detect_category(*texts: str) -> str:
    """دسته از روی کلیدواژه‌ها؛ نام (اولین متن) سه برابرِ توضیح وزن دارد («ماگ … مناسبِ قهوه» ⇐ خانه، نه خوراکی).
    کلیدواژهٔ کوتاه (≤۳ حرف) فقط به‌عنوانِ کلمهٔ کامل («کت» در «کتانی» یا «رژ» در «انرژی» حساب نمی‌شود)."""
    prepared = []
    for i, t in enumerate(texts):
        blob = (t or "").lower()
        prepared.append((3 if i == 0 else 1, blob, set(re.findall(r"[\w‌]+", blob))))
    best, top = "generic", 0
    for cat, words in KEYWORDS.items():
        score = 0
        for weight, blob, tokens in prepared:
            for w in words:
                w = w.lower()
                if (w in tokens) if len(w) <= 3 else (w in blob):
                    score += weight
        if score > top:
            best, top = cat, score
    return best


def _clip_text(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


def _num(value, default, low, high):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return max(low, min(high, x))


# ───────────────────────────── ساختنِ قلم‌ها

def photo_item(angle: str, *, instruction: str = "", tip: str = "") -> dict:
    spec = ANGLES[angle]
    text = _clip_text(instruction, 200)
    return {
        "key": f"p_{angle}", "kind": "photo", "angle": angle, "title": spec["title"],
        "instruction": text if len(text) >= 8 else spec["instruction"],
        "tip": _clip_text(tip, 160),
        "overlay": {"arrow": spec["arrow"], "yaw": spec["yaw"], "pitch": spec["pitch"], "distance": spec["distance"]},
        "check": dict(spec["check"]),
    }


def video_item(index: int, move: str, params: dict | None = None, *, instruction: str = "", caption: str = "",
               cues=None, tip: str = "") -> dict:
    base = MOVES[move]
    p = dict(params or {})
    duration = round(_num(p.get("duration"), base["duration"], 2, 12), 1)
    shot = {
        "key": f"v{index}", "kind": "video", "move": move, "title": base["title"],
        "duration": duration,
        "speed": p.get("speed") if p.get("speed") in SPEED_FA else base["speed"],
        "distance_cm": int(_num(p.get("distance_cm"), base["distance_cm"], 10, 200)),
    }
    if move == "orbit":
        shot["degrees"] = int(_num(p.get("degrees"), base["degrees"], 15, 360))
        shot["direction"] = p.get("direction") if p.get("direction") in ("left", "right") else "right"
    elif move in ("pan", "reveal"):
        shot["direction"] = p.get("direction") if p.get("direction") in ("left", "right") else "right"
    elif move == "tilt":
        shot["direction"] = p.get("direction") if p.get("direction") in ("up", "down") else "up"
    elif move == "push_in":
        shot["direction"] = "in"
    elif move == "pull_out":
        shot["direction"] = "out"
    else:
        shot["direction"] = "none"
        shot["action"] = _clip_text(p.get("action"), 80)
    text = _clip_text(instruction, 220)
    shot["instruction"] = text if len(text) >= 8 else move_instruction(shot)
    shot["pre"] = f"{shot['title']}. {shot['instruction']}"
    shot["caption"] = _clip_text(caption, 60)
    shot["tip"] = _clip_text(tip, 160)
    shot["overlay"] = {"arrow": _arrow_for(move, shot["direction"]), "yaw": shot.get("degrees", 0)
                       if move == "orbit" else 0, "pitch": 0,
                       "distance": "close" if move == "pull_out" else "far" if move == "push_in" else "medium"}
    good = []
    for c in cues or []:
        if not isinstance(c, dict):
            continue
        try:
            at = float(c.get("at"))
        except (TypeError, ValueError):
            continue
        txt = _clip_text(c.get("text"), 60)
        if 0 <= at <= duration and txt:
            good.append({"at": round(at, 1), "text": txt})
    shot["cues"] = sorted(good, key=lambda c: c["at"])[:5] if len(good) >= 2 else move_cues(shot)
    shot["check"] = {"min_seconds": round(max(1.5, duration * 0.7), 1)}
    return shot


def _fallback_features(product) -> list[str]:
    out = []
    for attr in getattr(product, "attributes", None).all() if hasattr(product, "attributes") else []:
        out.append(_clip_text(f"{attr.key}: {attr.value}", 60))
    text = (getattr(product, "short_description", "") or "") + "\n" + (getattr(product, "description", "") or "")
    for part in re.split(r"[\n.،؛!؟]+", text):
        part = _clip_text(part, 60)
        if 6 <= len(part) and part not in out:
            out.append(part)
        if len(out) >= 4:
            break
    for tag in getattr(product, "tags", None) or []:
        if len(out) >= 4:
            break
        if isinstance(tag, str) and tag.strip():
            out.append(_clip_text(tag, 40))
    return out[:5]


def _price_text(product) -> str:
    try:
        price = int(float(getattr(product, "price", 0) or 0))
    except (TypeError, ValueError):
        price = 0
    if price <= 0:
        return ""
    return fa_num(f"{price:,}").replace(",", "٬") + " تومان"


def default_voiceover(name: str, features: list[str], cta: str) -> str:
    parts = [f"{name}."] if name else []
    if features:
        parts.append("، ".join(f.split(":")[-1].strip() for f in features[:3]) + ".")
    parts.append(cta.rstrip(".") + ".")
    return _clip_text(" ".join(parts), 300)


def template_plan(product, category: str | None = None, *, purpose: str = "ad") -> dict:
    name = getattr(product, "name", "") or ""
    cat = category if category in TEMPLATES else detect_category(
        name, getattr(product, "description", ""), getattr(product, "brand", ""))
    t = TEMPLATES[cat]
    features = _fallback_features(product)
    plan = {
        "version": PLAN_VERSION,
        "product_type": CATEGORIES[cat] if cat != "generic" else (name or CATEGORIES[cat]),
        "category": cat,
        "category_label": CATEGORIES[cat],
        "features": features,
        "setup": {"background": t["setup"]["background"], "lighting": t["setup"]["lighting"],
                  "tips": list(GENERAL_TIPS)},
        "photos": [photo_item(a) for a in t["photos"][:MAX_PHOTOS]],
        "video": [video_item(i, move, params) for i, (move, params) in enumerate(t["video"][:MAX_VIDEO], 1)],
        "ad": {"headline": _clip_text(name, 60), "cta": "همین حالا سفارش بده",
               "voiceover": default_voiceover(name, features, "همین حالا سفارش بده"), "music_mood": "شاد و آرام",
               "price": _price_text(product)},
    }
    _assign_captions(plan)
    return plan


def _assign_captions(plan: dict) -> None:
    feats = [f for f in plan.get("features") or [] if f]
    for i, shot in enumerate(plan.get("video") or []):
        if not shot.get("caption"):
            if i == 0:
                shot["caption"] = plan["ad"].get("headline", "")
            elif i - 1 < len(feats):
                shot["caption"] = _clip_text(feats[i - 1].split(":")[-1], 60)


def validate_plan(raw, product, *, fallback_category: str | None = None) -> tuple[dict, list[str]]:
    """هر خروجی (مدل یا ویرایشِ کاربر) ⇐ برنامهٔ سالم + فهرستِ چیزهایی که اصلاح شد."""
    problems: list[str] = []
    if not isinstance(raw, dict):
        problems.append("برنامه شکلِ درستی نداشت؛ الگوی آماده به کار رفت.")
        raw = {}
    cat = raw.get("category")
    if cat not in TEMPLATES:
        guessed = fallback_category if fallback_category in TEMPLATES else detect_category(
            getattr(product, "name", ""), getattr(product, "description", ""), str(raw.get("product_type") or ""))
        if cat:
            problems.append(f"دستهٔ «{_clip_text(cat, 30)}» ناشناخته بود ⇐ {CATEGORIES[guessed]}")
        cat = guessed
    base = template_plan(product, cat)

    # ویژگی‌ها
    features = []
    for f in raw.get("features") or []:
        f = _clip_text(f, 60)
        if f and f not in features:
            features.append(f)
    features = features[:5] or base["features"]

    # عکس‌ها
    photos, seen = [], set()
    for item in raw.get("photos") or []:
        if not isinstance(item, dict):
            continue
        angle = str(item.get("angle") or item.get("key") or "").replace("p_", "").strip()
        angle = {"45": "three_quarter", "three-quarter": "three_quarter", "macro": "detail", "in_hand": "scale",
                 "hand": "scale"}.get(angle, angle)
        if angle not in ANGLES:
            problems.append(f"زاویهٔ ناشناختهٔ «{_clip_text(angle, 20)}» کنار گذاشته شد.")
            continue
        if angle in seen:
            continue
        seen.add(angle)
        photos.append(photo_item(angle, instruction=item.get("instruction", ""), tip=item.get("tip", "")))
        if len(photos) >= MAX_PHOTOS:
            break
    if len(photos) < MIN_PHOTOS:
        if raw.get("photos"):
            problems.append("زاویه‌های عکس کم بود ⇐ از الگوی آماده پر شد.")
        for p in base["photos"]:
            if p["angle"] not in seen and len(photos) < max(MIN_PHOTOS, len(base["photos"])):
                photos.append(p)
                seen.add(p["angle"])

    # ویدیو
    video = []
    for item in raw.get("video") or []:
        if not isinstance(item, dict):
            continue
        move = str(item.get("move") or "").strip().lower().replace("-", "_")
        move = {"push": "push_in", "pushin": "push_in", "dolly_in": "push_in", "pullout": "pull_out",
                "dolly_out": "pull_out", "rotate": "orbit", "arc": "orbit", "hand_interaction": "hand",
                "interaction": "hand"}.get(move, move)
        if move not in MOVES:
            problems.append(f"حرکتِ ناشناختهٔ «{_clip_text(move, 20)}» کنار گذاشته شد.")
            continue
        video.append(video_item(len(video) + 1, move, item, instruction=item.get("instruction", ""),
                                caption=item.get("caption", ""), cues=item.get("cues"), tip=item.get("tip", "")))
        if len(video) >= MAX_VIDEO:
            break
    if len(video) < MIN_VIDEO:
        if raw.get("video"):
            problems.append("نماهای ویدیو کم بود ⇐ از الگوی آماده پر شد.")
        for shot in base["video"]:
            if len(video) >= max(MIN_VIDEO, len(base["video"])):
                break
            if any(v["move"] == shot["move"] for v in video):
                continue
            video.append(video_item(len(video) + 1, shot["move"], shot, caption=shot.get("caption", "")))
    for i, shot in enumerate(video, 1):   # کلیدها پشتِ سرِ هم
        shot["key"] = f"v{i}"

    setup_raw = raw.get("setup") if isinstance(raw.get("setup"), dict) else {}
    tips = [_clip_text(t, 120) for t in (setup_raw.get("tips") or []) if _clip_text(t, 120)][:4]
    ad_raw = raw.get("ad") if isinstance(raw.get("ad"), dict) else {}
    headline = _clip_text(ad_raw.get("headline"), 60) or base["ad"]["headline"]
    cta = _clip_text(ad_raw.get("cta"), 40) or base["ad"]["cta"]
    plan = {
        "version": PLAN_VERSION,
        "product_type": _clip_text(raw.get("product_type"), 60) or base["product_type"],
        "category": cat, "category_label": CATEGORIES[cat],
        "features": features,
        "setup": {"background": _clip_text(setup_raw.get("background"), 140) or base["setup"]["background"],
                  "lighting": _clip_text(setup_raw.get("lighting"), 140) or base["setup"]["lighting"],
                  "tips": tips or base["setup"]["tips"]},
        "photos": photos, "video": video,
        "ad": {"headline": headline, "cta": cta,
               "voiceover": _clip_text(ad_raw.get("voiceover"), 300) or default_voiceover(headline, features, cta),
               "music_mood": _clip_text(ad_raw.get("music_mood"), 40) or base["ad"]["music_mood"],
               "price": _clip_text(ad_raw.get("price"), 40) or base["ad"]["price"]},
    }
    _assign_captions(plan)
    return plan, problems


# ───────────────────────────── هوش مصنوعی

PROMPT_ID = "shoot.plan"
PROMPT_VERSION = "1"

SYSTEM = (
    "تو کارگردانِ عکاسی و فیلم‌برداریِ محصول برای تبلیغاتِ اینستاگرامی هستی. صاحبِ یک فروشگاهِ کوچک با گوشی "
    "عکس و فیلم می‌گیرد و تو باید به زبانِ ساده و کوتاهِ فارسی بگویی از کدام زاویه‌ها عکس و چه حرکت‌هایی فیلم بگیرد. "
    "فقط JSON برگردان."
)


def build_prompt(product, category_hint: str) -> str:
    attrs = "؛ ".join(f"{a.key}: {a.value}" for a in product.attributes.all()[:12])
    angles = ", ".join(ANGLES)
    moves = ", ".join(MOVES)
    cats = ", ".join(CATEGORIES)
    return f"""محصول:
نام: {product.name}
برند: {product.brand or '-'}
قیمت: {_price_text(product) or '-'}
توضیح: {_clip_text(product.description, 900) or '-'}
ویژگی‌های ثبت‌شده: {attrs or '-'}
حدسِ دسته: {category_hint}

اگر عکس فرستاده شده، از روی عکس بفهم محصول چیست و چه چیزهایی‌اش دیدنی و فروش‌ساز است.
یک برنامهٔ عکاسی و فیلم‌برداری بده. JSON با همین کلیدها:
{{
 "product_type": "نوعِ محصول، فارسی و کوتاه",
 "category": "یکی از: {cats}",
 "features": ["۳ تا ۵ ویژگیِ فروش‌ساز، هرکدام حداکثر ۶ کلمه"],
 "setup": {{"background": "زمینهٔ پیشنهادی", "lighting": "نور", "tips": ["حداکثر ۳ نکته"]}},
 "photos": [{{"angle": "یکی از: {angles}", "instruction": "دستورِ کوتاهِ فارسی (حداکثر ۲۰ کلمه)، مثل «گوشی را ۴۵ درجه به راست ببر»", "tip": "اختیاری"}}],
 "video": [{{"move": "یکی از: {moves}", "duration": 3 تا 8 (ثانیه), "speed": "slow|medium|fast", "distance_cm": عدد, "degrees": "فقط برای orbit (۴۵ تا ۳۶۰)", "direction": "right|left|up|down", "action": "فقط برای hand: با دست چه کند", "instruction": "دستورِ فارسیِ کوتاه، مثل «آرام ۹۰ درجه دورش بچرخ، ۵ ثانیه»", "caption": "متنِ کوتاهِ روی این نما (یک ویژگی)", "cues": [{{"at": ثانیه, "text": "جملهٔ کوتاهِ حینِ ضبط مثل «حالا آرام بچرخ»"}}]}}],
 "ad": {{"headline": "تیترِ تبلیغ (حداکثر ۶ کلمه)", "cta": "دعوت به خرید (حداکثر ۴ کلمه)", "voiceover": "متنِ گوینده برای ۱۰ تا ۱۵ ثانیه", "music_mood": "حال‌وهوای موسیقی"}}
}}
۵ تا ۹ زاویهٔ عکس به ترتیبِ اهمیت (اولی روبه‌رو یا بهترین زاویه) و ۳ تا ۵ نمای ویدیو به ترتیبِ تدوین
(اولی جذاب‌ترین، آخری مناسبِ پایان). فقط کلیدهای گفته‌شده."""


def _image_payload(product, limit: int = 2) -> list[str]:
    from PIL import Image, ImageOps

    out = []
    for pi in list(product.images.all()[:limit]):
        try:
            with pi.image.open("rb") as fh:
                img = ImageOps.exif_transpose(Image.open(fh))
                img = img.convert("RGB")
                img.thumbnail((768, 768))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=85)
                out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception as exc:  # noqa: BLE001 — یک عکسِ خراب نباید تحلیل را بکشد
            logger.info("shoot: product image %s unreadable: %s", pi.pk, exc)
    return out


def friendly_error(exc) -> str:
    """خطای سرویس ⇐ یک جملهٔ کوتاهِ فارسی (نه JSON ِ خام)."""
    text = str(exc)
    if "402" in text or "Insufficient credit" in text:
        return "اعتبارِ سرویسِ هوش مصنوعیِ آنلاین تمام شده (۴۰۲)"
    if "401" in text:
        return "کلیدِ سرویسِ هوش مصنوعی پذیرفته نشد (۴۰۱)"
    if "429" in text:
        return "سهمیهٔ سرویسِ هوش مصنوعی پر شده (۴۲۹)"
    if "پاسخ نداد" in text or "timeout" in text.lower() or "timed out" in text.lower():
        return "سرویسِ هوش مصنوعی دیر جواب داد"
    if "اتصال" in text or "Connection" in text:
        return "به سرویسِ هوش مصنوعی وصل نشد"
    return text[:100]


def ask_model(product) -> tuple[dict | None, str]:
    """(خروجیِ خامِ مدل یا None، توضیح). هیچ خطایی بیرون نمی‌زند."""
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai import gateway
    from services.ai.router import TASK_REASONING, TASK_VISION, models_for

    hint = CATEGORIES[detect_category(product.name, product.description, product.brand)]
    prompt = build_prompt(product, hint)
    images = _image_payload(product)
    attempts = []
    if images:
        attempts.append(("vision", gateway.vision_provider, AIRequest.TaskType.VISION, TASK_VISION, images))
    attempts.append(("text", gateway.text_provider, AIRequest.TaskType.REASONING, TASK_REASONING, None))
    last = "هوش مصنوعی در دسترس نبود"
    for label, getter, task_type, route, imgs in attempts:
        try:
            provider = getter(product.store)
            parsed, _row = recorded_json_call(
                store=product.store, task_type=task_type, prompt_id=PROMPT_ID, prompt_version=PROMPT_VERSION,
                provider=provider, models=models_for(route), prompt=prompt, system=SYSTEM, images=imgs,
                validate=lambda p: (isinstance(p, dict) and bool(p.get("photos") or p.get("video")),
                                    "photos/video"),
                validation_message="برنامهٔ فیلم‌برداری ناقص بود",
            )
            return parsed, ("بینایی + متن" if label == "vision" else "فقط متن (بی‌عکس)")
        except Exception as exc:  # noqa: BLE001 — هر شکست ⇐ تلاشِ بعدی یا الگوی آماده
            last = friendly_error(exc)
            logger.warning("shoot: %s plan call failed for product %s: %s", label, product.pk, exc)
    return None, last


def analyze(product) -> tuple[dict, str, list[str]]:
    """(برنامه، منبع: ai|template، یادداشت‌ها)."""
    raw, how = ask_model(product)
    if raw is None:
        return template_plan(product), "template", [f"تحلیلِ هوش مصنوعی انجام نشد ({how}) ⇐ الگوی آمادهٔ همین دسته."]
    plan, problems = validate_plan(raw, product)
    return plan, "ai", [f"تحلیل با هوش مصنوعی ({how})."] + problems

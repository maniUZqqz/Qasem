"""What can be searched for: business types (with the words every source needs) and ready-made missions (presets).

A *business type* is the owner's vocabulary («باشگاه بدنسازی»، «کافه»، «دندان‌پزشکی»). For each one this file knows
  * the OpenStreetMap tags that mean it (for the map source - only tags that are in common use),
  * the Persian / English words people write on the web for it (search engines, directories, website text),
  * the words that, seen in a business's name or site, say «yes, this really is one».
Nothing in the engine is specific to one type: a new type is one line here (or a mission with free keywords).

A *preset* is a mission that is already filled in. «چغر ← باشگاه‌ها و مربی‌ها در تهران» is one preset; «کافه‌های اصفهان» is another,
and they run through exactly the same engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SAFE_TAG = re.compile(r"^[a-z][a-z0-9_:]{0,40}$")


@dataclass(frozen=True)
class BusinessType:
    key: str
    fa: str
    group: str
    osm: tuple[tuple[str, str], ...] = ()
    terms_fa: tuple[str, ...] = ()  # what a person types into a search box
    terms_en: tuple[str, ...] = ()
    words: tuple[str, ...] = ()  # seen in a name / title / site text: "this is one"
    fit_words: tuple[str, ...] = ()  # optional: signals of a good customer for the usual products (used by scoring only)

    @property
    def osm_selectors(self) -> list[tuple[str, str]]:
        for k, v in self.osm:
            if not SAFE_TAG.match(k) or (v != "*" and not SAFE_TAG.match(v)):
                raise ValueError(f"unsafe tag in business type {self.key}: {k}={v}")
        return list(self.osm)


def _t(key, fa, group, osm=(), terms_fa=(), terms_en=(), words=(), fit_words=()) -> BusinessType:
    return BusinessType(key, fa, group, tuple(osm), tuple(terms_fa), tuple(terms_en), tuple(words), tuple(fit_words))


GROUPS = {
    "sport": "ورزش و سلامت", "food": "غذا و کافه", "retail": "فروشگاه", "beauty": "زیبایی", "health": "پزشکی و درمان",
    "services": "خدمات", "education": "آموزش", "travel": "گردشگری و اقامت", "auto": "خودرو",
}

_TYPES: list[BusinessType] = [
    # ---- ورزش و سلامت
    _t("gym", "باشگاه بدنسازی و فیتنس", "sport", [("leisure", "fitness_centre"), ("amenity", "gym")],
       ["باشگاه بدنسازی", "باشگاه فیتنس", "سالن بدنسازی", "باشگاه ورزشی"], ["gym", "fitness club", "fitness center"],
       ["باشگاه", "بدنسازی", "فیتنس", "تناسب اندام", "gym", "fitness", "bodybuilding", "crossfit", "کراس فیت"],
       ["مربی", "برنامه تمرینی", "برنامه غذایی", "رژیم", "شاگرد", "کوچینگ", "coach", "trainer"]),
    _t("sports_club", "مجموعه و باشگاه ورزشی", "sport", [("leisure", "sports_centre"), ("leisure", "sports_hall")],
       ["مجموعه ورزشی", "باشگاه ورزشی", "سالن ورزشی", "فرهنگسرای ورزشی"], ["sports club", "sports center"],
       ["مجموعه ورزشی", "باشگاه", "سالن", "ورزشی", "sports", "club"], ["مربی", "کلاس", "coach", "trainer"]),
    _t("personal_trainer", "مربی شخصی و مشاور تناسب اندام", "sport", [],
       ["مربی بدنسازی", "مربی شخصی", "مربی تناسب اندام", "مربی آنلاین", "برنامه تمرینی اختصاصی"], ["personal trainer", "fitness coach", "online coach"],
       ["مربی", "کوچ", "coach", "trainer", "pt", "تغذیه ورزشی", "برنامه تمرین"],
       ["برنامه تمرینی", "برنامه غذایی", "شاگرد", "آنلاین", "رژیم"]),
    _t("yoga_pilates", "یوگا و پیلاتس", "sport", [("sport", "yoga"), ("sport", "pilates")],
       ["استودیو یوگا", "باشگاه پیلاتس", "کلاس یوگا"], ["yoga studio", "pilates studio"], ["یوگا", "پیلاتس", "yoga", "pilates"], ["مربی", "کلاس"]),
    _t("martial_arts", "رزمی و دفاع شخصی", "sport",
       [("sport", "karate"), ("sport", "judo"), ("sport", "taekwondo"), ("sport", "boxing"), ("sport", "wrestling"), ("sport", "martial_arts")],
       ["باشگاه رزمی", "باشگاه بوکس", "باشگاه کاراته", "باشگاه تکواندو"], ["martial arts gym", "boxing gym"],
       ["رزمی", "بوکس", "کاراته", "تکواندو", "جودو", "کشتی", "mma", "boxing"], ["مربی", "کلاس"]),
    _t("swimming", "استخر و آموزشگاه شنا", "sport", [("sport", "swimming")],
       ["استخر", "آموزشگاه شنا", "مجموعه آبی"], ["swimming pool", "swim school"], ["استخر", "شنا", "pool", "swim"], ["مربی", "کلاس"]),
    _t("nutrition_store", "فروشگاه مکمل و تغذیه ورزشی", "sport", [("shop", "nutrition_supplements")],
       ["فروشگاه مکمل ورزشی", "مکمل بدنسازی", "فروشگاه مکمل"], ["supplement store", "sports nutrition shop"], ["مکمل", "پروتئین", "supplement", "whey"], ["مربی", "برنامه"]),
    _t("sportswear", "پوشاک و لوازم ورزشی", "sport", [("shop", "sports"), ("shop", "outdoor")],
       ["فروشگاه لوازم ورزشی", "پوشاک ورزشی", "فروشگاه ورزشی"], ["sports shop", "sportswear store"], ["ورزشی", "لوازم ورزشی", "sport", "sportswear"], []),
    _t("dietitian", "مشاور تغذیه و رژیم‌درمانی", "health", [("healthcare", "dietitian")],
       ["کلینیک تغذیه", "مشاور تغذیه", "رژیم درمانی", "متخصص تغذیه"], ["dietitian", "nutrition clinic"], ["تغذیه", "رژیم", "لاغری", "diet", "nutrition"], ["برنامه غذایی", "رژیم"]),
    _t("physio", "فیزیوتراپی و کایروپراکتیک", "health", [("healthcare", "physiotherapist")],
       ["کلینیک فیزیوتراپی", "فیزیوتراپی", "کایروپراکتیک"], ["physiotherapy clinic"], ["فیزیوتراپی", "کایروپراکتیک", "physio"], []),
    # ---- غذا و کافه
    _t("cafe", "کافه و قهوه‌خانه", "food", [("amenity", "cafe")],
       ["کافه", "کافی شاپ", "کافه رستوران", "قهوه"], ["cafe", "coffee shop"], ["کافه", "کافی شاپ", "قهوه", "cafe", "coffee", "کافیشاپ", "کافه‌رستوران"],
       ["منو", "منوی دیجیتال", "رزرو", "سفارش آنلاین", "اینستاگرام"]),
    _t("restaurant", "رستوران و سفره‌خانه", "food", [("amenity", "restaurant")],
       ["رستوران", "سفره خانه", "غذاخوری"], ["restaurant"], ["رستوران", "سفره‌خانه", "restaurant"], ["منو", "رزرو", "سفارش آنلاین"]),
    _t("fast_food", "فست‌فود و ساندویچی", "food", [("amenity", "fast_food")],
       ["فست فود", "ساندویچی", "پیتزا فروشی", "برگر"], ["fast food", "burger", "pizza"], ["فست فود", "ساندویچ", "پیتزا", "برگر", "pizza", "burger"], ["سفارش آنلاین", "منو"]),
    _t("bakery", "نانوایی و شیرینی‌پزی", "food", [("shop", "bakery"), ("shop", "pastry"), ("shop", "confectionery")],
       ["قنادی", "شیرینی سرا", "نانوایی", "کیک و شیرینی"], ["bakery", "pastry shop"], ["قنادی", "شیرینی", "نانوایی", "کیک", "bakery", "pastry"], ["سفارش", "سفارش آنلاین"]),
    # ---- فروشگاه
    _t("clothes", "پوشاک و بوتیک", "retail", [("shop", "clothes"), ("shop", "boutique"), ("shop", "fashion")],
       ["فروشگاه لباس", "بوتیک", "پوشاک زنانه", "پوشاک مردانه"], ["clothing store", "boutique"], ["پوشاک", "لباس", "بوتیک", "مزون", "clothing", "boutique", "fashion"], ["اینستاگرام", "فروشگاه آنلاین"]),
    _t("shoes", "کفش", "retail", [("shop", "shoes")], ["فروشگاه کفش", "کفش"], ["shoe store"], ["کفش", "shoes"], []),
    _t("bags", "کیف و چمدان", "retail", [("shop", "bag")], ["فروشگاه کیف", "کیف و کفش"], ["bag store"], ["کیف", "چمدان", "bag"], []),
    _t("jewelry", "طلا و جواهر", "retail", [("shop", "jewelry"), ("shop", "watches")], ["طلافروشی", "جواهری", "ساعت فروشی"], ["jewelry store"], ["طلا", "جواهر", "ساعت", "jewelry", "gold"], []),
    _t("cosmetics", "لوازم آرایشی و بهداشتی", "retail", [("shop", "cosmetics"), ("shop", "perfumery")], ["لوازم آرایشی", "عطر و ادکلن", "فروشگاه آرایشی"], ["cosmetics store", "perfume shop"], ["آرایشی", "بهداشتی", "عطر", "cosmetic", "perfume"], []),
    _t("gifts", "هدیه و سوغات", "retail", [("shop", "gift"), ("shop", "souvenir")], ["فروشگاه هدیه", "سوغات", "گیفت شاپ"], ["gift shop"], ["هدیه", "سوغات", "گیفت", "gift"], []),
    _t("handicrafts", "صنایع‌دستی و هنری", "retail", [("shop", "art"), ("craft", "*")], ["صنایع دستی", "فروشگاه صنایع دستی"], ["handicraft shop"], ["صنایع دستی", "صنایع‌دستی", "هنری", "handicraft"], []),
    _t("home_decor", "لوازم خانه و دکوراسیون", "retail", [("shop", "houseware"), ("shop", "interior_decoration"), ("shop", "furniture"), ("shop", "lighting")],
       ["فروشگاه دکوراسیون", "مبلمان", "لوازم خانگی", "لوستر"], ["home decor store", "furniture store"], ["دکوراسیون", "مبل", "مبلمان", "لوستر", "furniture"], []),
    _t("kids", "لوازم کودک و اسباب‌بازی", "retail", [("shop", "toys"), ("shop", "baby_goods")], ["فروشگاه اسباب بازی", "لوازم کودک", "بیبی شاپ"], ["toy store", "baby shop"], ["اسباب بازی", "کودک", "نوزاد", "toy", "baby"], []),
    _t("electronics", "موبایل و لوازم الکترونیکی", "retail", [("shop", "mobile_phone"), ("shop", "electronics"), ("shop", "computer")],
       ["موبایل فروشی", "فروشگاه لوازم الکترونیکی", "کامپیوتر"], ["mobile phone shop", "electronics store"], ["موبایل", "کامپیوتر", "الکترونیک", "mobile", "electronics"], []),
    _t("books", "کتاب و لوازم‌التحریر", "retail", [("shop", "books"), ("shop", "stationery")], ["کتاب فروشی", "لوازم التحریر"], ["bookstore"], ["کتاب", "کتابفروشی", "لوازم التحریر", "book"], []),
    _t("flowers", "گل و گیاه", "retail", [("shop", "florist"), ("shop", "garden_centre")], ["گل فروشی", "گلخانه", "گل و گیاه"], ["florist"], ["گل", "گیاه", "florist"], []),
    _t("carpet", "فرش و پارچه", "retail", [("shop", "carpet"), ("shop", "fabric"), ("shop", "curtain")], ["فرش فروشی", "پارچه فروشی", "پرده"], ["carpet shop", "fabric store"], ["فرش", "پارچه", "پرده", "carpet"], []),
    _t("optician", "عینک‌سازی و اپتومتری", "retail", [("shop", "optician")], ["عینک فروشی", "عینک سازی"], ["optician"], ["عینک", "optic"], []),
    _t("supermarket", "سوپرمارکت و هایپر", "retail", [("shop", "supermarket"), ("shop", "convenience")], ["سوپرمارکت", "فروشگاه زنجیره‌ای", "هایپرمارکت"], ["supermarket"], ["سوپرمارکت", "هایپر", "supermarket"], []),
    _t("pet", "پت‌شاپ", "retail", [("shop", "pet")], ["پت شاپ", "فروشگاه حیوانات خانگی"], ["pet shop"], ["پت", "حیوانات", "pet"], []),
    # ---- زیبایی
    _t("beauty_salon", "سالن زیبایی و آرایشگاه", "beauty", [("shop", "beauty"), ("shop", "hairdresser")], ["سالن زیبایی", "آرایشگاه زنانه", "سالن آرایش"], ["beauty salon", "hair salon"], ["سالن زیبایی", "آرایشگاه", "مو", "ناخن", "beauty", "salon"], ["رزرو", "نوبت دهی", "اینستاگرام"]),
    _t("barber", "آرایشگاه مردانه", "beauty", [("shop", "hairdresser")], ["آرایشگاه مردانه", "سلمانی", "باربر شاپ"], ["barber shop"], ["آرایشگاه مردانه", "سلمانی", "barber"], []),
    # ---- پزشکی و درمان
    _t("dentist", "دندان‌پزشکی", "health", [("amenity", "dentist"), ("healthcare", "dentist")], ["دندانپزشکی", "مطب دندانپزشک", "کلینیک دندانپزشکی"], ["dentist", "dental clinic"], ["دندان", "دندانپزشک", "dental", "dentist"], ["نوبت دهی", "رزرو"]),
    _t("clinic", "کلینیک و مطب", "health", [("amenity", "clinic"), ("amenity", "doctors")], ["کلینیک", "مطب پزشک", "درمانگاه"], ["clinic", "doctor office"], ["کلینیک", "مطب", "درمانگاه", "clinic"], ["نوبت دهی", "رزرو"]),
    _t("pharmacy", "داروخانه", "health", [("amenity", "pharmacy")], ["داروخانه"], ["pharmacy"], ["داروخانه", "pharmacy"], []),
    _t("lab", "آزمایشگاه و تصویربرداری", "health", [("healthcare", "laboratory")], ["آزمایشگاه", "مرکز تصویربرداری", "رادیولوژی"], ["medical laboratory"], ["آزمایشگاه", "رادیولوژی", "laboratory"], []),
    _t("vet", "دامپزشکی", "health", [("amenity", "veterinary")], ["کلینیک دامپزشکی", "دامپزشک"], ["vet clinic"], ["دامپزشک", "vet"], []),
    # ---- خدمات
    _t("photo_studio", "آتلیه و عکاسی", "services", [("shop", "photo"), ("craft", "photographer")], ["آتلیه عکاسی", "عکاسی", "آتلیه"], ["photo studio"], ["آتلیه", "عکاسی", "photo", "studio"], ["اینستاگرام", "نمونه کار"]),
    _t("printing", "چاپ و تبلیغات", "services", [("shop", "copyshop"), ("craft", "printer")], ["چاپخانه", "چاپ دیجیتال", "تبلیغات"], ["print shop"], ["چاپ", "چاپخانه", "تبلیغات", "print"], []),
    _t("real_estate", "مشاور املاک", "services", [("office", "estate_agent")], ["مشاور املاک", "آژانس املاک"], ["real estate agency"], ["املاک", "مشاور املاک", "estate"], []),
    _t("lawyer", "وکیل و دفتر حقوقی", "services", [("office", "lawyer")], ["وکیل", "دفتر حقوقی", "مشاوره حقوقی"], ["law office"], ["وکیل", "حقوقی", "lawyer"], []),
    _t("accountant", "حسابداری و مالی", "services", [("office", "accountant")], ["حسابدار", "دفتر حسابداری", "مشاور مالیاتی"], ["accounting firm"], ["حسابداری", "مالیاتی", "accountant"], []),
    _t("travel_agency", "آژانس مسافرتی", "travel", [("shop", "travel_agency"), ("office", "travel_agent")], ["آژانس مسافرتی", "دفتر خدمات مسافرتی"], ["travel agency"], ["آژانس", "مسافرتی", "تور", "travel", "tour"], []),
    _t("hotel", "هتل و اقامتگاه", "travel", [("tourism", "hotel"), ("tourism", "guest_house"), ("tourism", "hostel"), ("tourism", "motel")], ["هتل", "مهمانپذیر", "اقامتگاه بوم گردی", "هتل آپارتمان"], ["hotel", "guest house", "hostel"], ["هتل", "مهمانپذیر", "اقامتگاه", "hotel", "hostel"], ["رزرو"]),
    _t("event_hall", "تالار و سالن همایش", "services", [("amenity", "events_venue"), ("amenity", "community_centre")], ["تالار پذیرایی", "تالار عروسی", "سالن همایش"], ["event hall", "wedding venue"], ["تالار", "همایش", "event"], []),
    _t("tailor", "خیاطی و مزون", "services", [("craft", "tailor"), ("shop", "tailor")], ["خیاطی", "مزون لباس"], ["tailor"], ["خیاطی", "مزون", "tailor"], []),
    # ---- آموزش
    _t("language_school", "آموزشگاه زبان", "education", [("amenity", "language_school")], ["آموزشگاه زبان", "کلاس زبان"], ["language school"], ["زبان", "آموزشگاه", "language"], []),
    _t("driving_school", "آموزشگاه رانندگی", "education", [("amenity", "driving_school")], ["آموزشگاه رانندگی"], ["driving school"], ["رانندگی", "driving"], []),
    _t("kindergarten", "مهدکودک و پیش‌دبستانی", "education", [("amenity", "kindergarten")], ["مهد کودک", "پیش دبستانی"], ["kindergarten", "nursery"], ["مهدکودک", "پیش‌دبستانی", "kindergarten"], []),
    _t("school", "مدرسه و آموزشگاه", "education", [("amenity", "school"), ("amenity", "prep_school")], ["مدرسه غیرانتفاعی", "آموزشگاه"], ["private school"], ["مدرسه", "آموزشگاه", "school"], []),
    # ---- خودرو
    _t("car_repair", "تعمیرگاه خودرو", "auto", [("shop", "car_repair")], ["تعمیرگاه خودرو", "مکانیکی", "تعویض روغن"], ["car repair"], ["تعمیرگاه", "مکانیکی", "car repair"], []),
    _t("car_wash", "کارواش", "auto", [("amenity", "car_wash")], ["کارواش", "کارواش و روغن"], ["car wash"], ["کارواش", "car wash"], []),
]

TYPES: dict[str, BusinessType] = {t.key: t for t in _TYPES}


def get_type(key: str) -> BusinessType | None:
    return TYPES.get(key)


def listing() -> list[dict]:
    """For the panel's picker: grouped, with the Persian label and (read-only) what the sources will look for."""
    return [
        {"key": t.key, "label": t.fa, "group": t.group, "group_label": GROUPS.get(t.group, t.group), "has_map": bool(t.osm),
         "terms": list(t.terms_fa[:3]), "osm": [f"{k}={v}" for k, v in t.osm]}
        for t in _TYPES
    ]


def type_for_osm_tags(tags: dict, allowed: list[str] | None = None) -> list[str]:
    """Which of the (allowed) types an OpenStreetMap object's tags mean. ``craft=*`` only counts when nothing else matched."""
    out: list[str] = []
    for t in _TYPES:
        if allowed is not None and t.key not in allowed:
            continue
        for k, v in t.osm:
            if k not in tags:
                continue
            if v == "*" or str(tags.get(k)) == v:
                if t.key not in out:
                    out.append(t.key)
                break
    return out


# --------------------------------------------------------------------------- presets (missions that are already filled in)


@dataclass(frozen=True)
class Pitch:
    """What the sender says about itself, in its own voice. Used by the drafts (never invented: only what is written here or on the store)."""

    brand: str
    what: str  # one sentence: what it is
    benefit: str  # one sentence: why this kind of business would care
    cta: str  # the one thing we ask for
    voice: str = "صمیمی ولی حرفه‌ای، کوتاه و بدونِ اغراق"
    sms: str = ""  # one short line for an SMS (the whole message has to fit two SMS parts, sender block included)
    avoid: tuple[str, ...] = ("قیمت", "درصد", "تضمین")


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    description: str
    product: str
    store_id: int | None
    spec: dict = field(default_factory=dict)
    pitch: Pitch | None = None


_DEFAULT_BUDGET = {"max_requests": 600, "max_sites": 60, "max_pages_per_site": 5, "max_seconds": 1500, "max_bytes": 80_000_000, "domain_delay": 2.0, "max_search_queries": 8, "max_directory_pages": 12}

PRESETS: dict[str, Preset] = {
    "chagher_gyms_tehran": Preset(
        key="chagher_gyms_tehran",
        name="چغر ← باشگاه‌ها، مجموعه‌های ورزشی و مربی‌های شخصیِ تهران",
        description="باشگاه بدنسازی، مجموعهٔ ورزشی و مربی شخصی در تهران؛ مشتریِ طبیعیِ چغر (دستیار هوش مصنوعیِ مربی‌ها).",
        product="chagher",
        store_id=34,
        spec={
            "tag": "چغر · تهران",
            "business_types": ["gym", "sports_club", "personal_trainer"],
            "keywords": ["مربی", "برنامه تمرینی"],
            "cities": ["تهران"],
            "language": "fa",
            "sources": {"osm": True, "search": True, "directory": True, "website": True, "instagram": False, "neshan": False},
            "require_contact": True,
            "max_results": 400,
            "budget": {**_DEFAULT_BUDGET},
            "execution": "auto",
        },
        pitch=Pitch(
            brand="چغر",
            what="چغر دستیارِ هوش مصنوعیِ مربی‌هاست: برنامهٔ ورزشی و غذاییِ هر ورزشکار را در کمتر از یک دقیقه پیش‌نویس می‌کند و تصمیمِ نهایی همیشه با مربی است.",
            benefit="برای مربی‌ها و باشگاه‌هایی که شاگردِ زیاد دارند وقتِ نوشتنِ برنامه را کم می‌کند.",
            cta="اگر مایلید همین‌جا پاسخ بدهید تا بیشتر توضیح بدهم؛ شروعِ چغر رایگان است و کارتِ اعتباری نمی‌خواهد.",
            voice="صمیمی ولی حرفه‌ای، کوتاه و بدونِ اغراق؛ مثلِ همکارِ مربی. «پیش‌نویس» را همیشه بگو؛ جایگزینِ مربی نیست.",
            sms="دستیارِ هوش مصنوعیِ مربی‌ها برای پیش‌نویسِ برنامهٔ ورزشی و غذایی؛ شروع رایگان.",
            avoid=("قیمت", "درصد", "تضمین", "جایگزینِ مربی", "رضایتِ ۹۸", "۵۰۰ برنامه"),
        ),
    ),
    "chagher_coaches_instagram": Preset(
        key="chagher_coaches_instagram",
        name="چغر ← مربی‌های آنلاین و پیج‌های تناسب اندام (اینستاگرام)",
        description="پیج‌های عمومیِ مربیِ بدنسازی و تناسب اندام؛ خواندنِ پیج با آباگرام روی سرورِ پردازش لازم است (تا روشن‌شدنش در صف می‌ماند).",
        product="chagher",
        store_id=34,
        spec={
            "tag": "چغر · اینستاگرام",
            "business_types": ["personal_trainer", "gym"],
            "keywords": ["مربی بدنسازی", "برنامه تمرینی", "مربی آنلاین"],
            "cities": ["تهران", "اصفهان", "مشهد", "شیراز"],
            "language": "fa",
            "sources": {"osm": False, "search": True, "directory": True, "website": True, "instagram": True, "neshan": False},
            "require_contact": False,
            "max_results": 200,
            "budget": {**_DEFAULT_BUDGET, "max_ig_accounts": 40},
            "execution": "auto",
        },
        pitch=None,
    ),
    "cafes_isfahan": Preset(
        key="cafes_isfahan",
        name="کافه‌های اصفهان",
        description="کافه و کافی‌شاپ در اصفهان؛ نمونهٔ یک مأموریتِ غیرِ ورزشی که با همان موتور اجرا می‌شود.",
        product="nm",
        store_id=None,
        spec={
            "tag": "کافه · اصفهان",
            "business_types": ["cafe"],
            "keywords": ["کافه", "کافی شاپ"],
            "cities": ["اصفهان"],
            "language": "fa",
            "sources": {"osm": True, "search": True, "directory": True, "website": True, "instagram": False, "neshan": False},
            "require_contact": True,
            "max_results": 300,
            "budget": {**_DEFAULT_BUDGET},
            "execution": "auto",
        },
        pitch=Pitch(
            brand="آپ‌مارکت",
            what="آپ‌مارکت ابزارِ بازاریابیِ فارسی برای کسب‌وکارهاست: از محتوای شبکه‌های اجتماعی تا عکس و ویدیوی محصول.",
            benefit="برای کافه‌هایی که پیجِ اینستاگرامِ فعال دارند ساختنِ پست و استوریِ روزانه را سریع‌تر می‌کند.",
            cta="اگر دوست دارید، یک نمونهٔ رایگان برای کافهٔ شما آماده می‌کنم تا ببینید.",
            sms="ابزارِ فارسیِ ساختنِ پست و استوریِ اینستاگرام برای کافه‌ها.",
            avoid=("قیمت", "درصد", "تضمین"),
        ),
    ),
    "clothing_shops_hamedan": Preset(
        key="clothing_shops_hamedan",
        name="فروشگاه‌های پوشاک در همدان",
        description="فروشگاه و بوتیکِ پوشاک؛ مشتریِ طبیعیِ ابزارِ محتوا و عکسِ محصولِ آپ‌مارکت.",
        product="nm",
        store_id=None,
        spec={
            "tag": "پوشاک · همدان",
            "business_types": ["clothes", "shoes", "bags"],
            "keywords": ["پوشاک", "بوتیک"],
            "cities": ["همدان"],
            "language": "fa",
            "sources": {"osm": True, "search": True, "directory": False, "website": True, "instagram": False, "neshan": False},
            "require_contact": True,
            "max_results": 200,
            "budget": {**_DEFAULT_BUDGET},
            "execution": "auto",
        },
        pitch=Pitch(
            brand="آپ‌مارکت",
            what="آپ‌مارکت ابزارِ بازاریابیِ فارسی برای فروشگاه‌هاست: عکسِ حرفه‌ایِ محصول، کپشن و ویدیوی اینستاگرام.",
            benefit="برای فروشگاه‌هایی که محصولِ زیاد دارند عکس و کپشنِ هر محصول را سریع و یکدست می‌کند.",
            cta="اگر مایلید، با یکی از محصولاتِ فروشگاهتان یک نمونه می‌سازم و برایتان می‌فرستم.",
            sms="ابزارِ فارسیِ عکس، کپشن و ویدیوی محصول برای فروشگاه‌ها.",
        ),
    ),
    "dental_clinics_mashhad": Preset(
        key="dental_clinics_mashhad",
        name="دندان‌پزشکی‌ها و کلینیک‌های مشهد",
        description="دندان‌پزشکی و کلینیک؛ نمونه‌ای از مأموریتِ خدماتی.",
        product="nm",
        store_id=None,
        spec={
            "tag": "دندانپزشکی · مشهد",
            "business_types": ["dentist", "clinic"],
            "keywords": ["دندانپزشکی", "کلینیک"],
            "cities": ["مشهد"],
            "language": "fa",
            "sources": {"osm": True, "search": True, "directory": False, "website": True, "instagram": False, "neshan": False},
            "require_contact": True,
            "max_results": 200,
            "budget": {**_DEFAULT_BUDGET},
            "execution": "auto",
        },
        pitch=Pitch(
            brand="آپ‌مارکت",
            what="آپ‌مارکت ابزارِ بازاریابیِ فارسی برای کسب‌وکارهاست؛ از جمله محتوای آموزشیِ شبکه‌های اجتماعی برای کلینیک‌ها.",
            benefit="کلینیک‌ها را در ساختنِ محتوای آموزشیِ منظم برای اینستاگرام یاری می‌کند.",
            cta="اگر مایلید، یک نمونه محتوای آموزشی برای کلینیکتان آماده می‌کنم.",
            sms="ابزارِ فارسیِ ساختنِ محتوای آموزشیِ اینستاگرام برای کلینیک‌ها.",
            avoid=("قیمت", "درصد", "تضمین", "درمان", "نتیجه"),
        ),
    ),
}


def preset_listing() -> list[dict]:
    return [
        {"key": p.key, "name": p.name, "description": p.description, "product": p.product, "store_id": p.store_id,
         "spec": p.spec, "has_pitch": p.pitch is not None, "types": [TYPES[k].fa for k in p.spec.get("business_types", []) if k in TYPES],
         "cities": p.spec.get("cities", []), "needs_node": bool((p.spec.get("sources") or {}).get("instagram"))}
        for p in PRESETS.values()
    ]


def pitch_for(key: str) -> Pitch | None:
    p = PRESETS.get(key)
    return p.pitch if p else None

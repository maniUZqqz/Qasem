"""Scores for «پردازش»: who among a list's people matters most, and what each one is. Two moments:
- before any profile is read, from the list itself (pre_score): public or private, a real picture, the badge, and the words in
  the username and name (business words, the trade's words). The queue reads profiles in that order, best first.
- after the profile is read (final): the account type, Instagram's own category, a public phone or mail, the bio's words, size
  and activity. It also gives the label: farmer / seller / maker (manufacturer or company) / other.
Words are compared folded (ig_process.fold): «آبیاری» = «ابياري», «Tarım» = «tarim», separators ignored."""
import math
import re

_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "آ": "ا", "أ": "ا", "إ": "ا", "ة": "ه", "ı": "i", "İ": "i",
                       "ş": "s", "ç": "c", "ğ": "g", "ü": "u", "ö": "o", "ə": "e", "̇": "", "‌": "", "‍": ""})


def fold(text):
    """Lower case, Arabic/Persian letter forms made one, Turkish letters made plain, no joiners, no separators: so
    'Abyari_Co', 'آبیاری' and 'ابياري' compare as they read."""
    return re.sub(r"[\s._\-|•·'ʻʼ`’]+", "", (text or "").lower().translate(_FOLD))


# ---- the words (2026-10-29: «everyone tied in any way to farming, irrigation and spraying: organisations and companies, shops and
# sellers, and the customers who own farmland»). Persian, Turkish, English, Arabic, Russian, Uzbek, Azerbaijani, Tajik — compared
# folded (fold): letter forms made one, Turkish/Azeri letters made plain, separators and apostrophes dropped. Words of 1–2 letters
# must be a whole part of the name; longer ones may sit inside a longer username (anadolusera, cmragrotech).
# the heart of his trade: irrigation, spraying, wells, greenhouse watering
CORE = ["آبیاری", "قطره‌ای", "قطره‌چکان", "آبپاش", "آب‌پاش", "آبفشان", "سمپاش", "سم‌پاشی", "سنترپیوت", "پیوت", "تحت فشار", "نوار تیپ",
        "پلی‌اتیلن", "اتصالات", "شیرآلات", "الکتروپمپ", "پمپ", "چاه", "حفاری",
        "irrigation", "irrigat", "drip", "sprinkler", "sprinkl", "sprayer", "spraying", "cropspray", "centerpivot", "hydroponic",
        "sulama", "damla", "yagmurlama", "fiskiye", "pivot", "hortum", "pompa", "dalgicpompa", "sondaj", "ilaclama", "pulverizator", "atomizor",
        "تنقيط", "رشاش", "رشاشات", "مضخ",
        "полив", "орошен", "капельн", "спринклер", "опрыскив", "насос",
        "sugorish", "tomchilatib", "suvarma", "damci", "суару", "обёрӣ"]
# farming in general: the land, crops, seed, fertiliser, machinery, animals
AGRI = ["کشاورزی", "کشاورز", "زراعت", "زراعی", "زارع", "دهقان", "کشت", "گلخانه", "باغبانی", "باغدار", "مزرعه", "مزارع", "بذر", "نهال",
        "نشاء", "کود", "سموم", "ادوات", "ماشین‌آلات کشاورزی", "تراکتور", "کمباین", "دامداری", "دامپروری", "مرغداری", "پسته", "زعفران",
        "گندم", "برنج", "خرما", "انار", "مرکبات", "صیفی", "سبزیجات", "زیتون", "انگور", "پنبه", "چغندر",
        "agri", "agro", "agric", "farm", "farmer", "farming", "orchard", "vineyard", "crop", "harvest", "seed", "fertiliz", "fertilis",
        "pesticide", "agrochem", "tractor", "horticult", "greenhouse", "livestock", "dairy", "poultry", "olive", "citrus", "pistachio", "saffron",
        "tarim", "ziraat", "zirai", "ciftci", "ciftlik", "sera", "topraksiz", "tohum", "fide", "fidan", "gubre", "traktor", "hasat",
        "meyve", "sebze", "zeytin", "findik", "fistik", "pamuk", "bugday", "narenciye", "hayvancilik", "besicilik",
        "زراعة", "زراعي", "مزرعة", "بذور", "اسمدة", "سماد", "مبيدات", "جرار", "نخيل", "تمور", "حصاد", "فلاح",
        "агро", "сельхоз", "сельск", "ферм", "теплиц", "семен", "удобрен", "саженц", "трактор", "урожай", "садов", "агроном",
        "qishloq", "fermer", "dehqon", "issiqxona", "urug", "paxta", "kendteserrufat", "istixana", "toxum",
        "ауылшаруашылығы", "жылыжай", "кишоварз", "деҳқон"]
TRADE = CORE + AGRI
# a business of any trade (usernames and names)
BUSINESS = ["co", "company", "group", "corp", "inc", "ltd", "llc", "gmbh", "official", "shop", "store", "market", "mart",
            "trade", "trading", "export", "import", "industry", "industrial", "tech", "systems", "solutions", "agency",
            "ticaret", "sanayi", "insaat", "makina", "makine", "pazarlama", "magaza", "bayi", "ltdsti", "as", "sti",
            "شرکت", "گروه", "فروشگاه", "بازرگانی", "صنایع", "تولیدی", "پخش", "نمایندگی", "مهندسی", "تجارت", "بازار", "مجموعه",
            "شركة", "مؤسسة", "ооо", "компания", "группа"]
# what kind of business: from the bio or the name (Instagram's category comes first, see CATEGORY)
FARMER = ["کشاورز", "باغدار", "باغ", "مزرعه", "دامدار", "گلخانه‌دار", "زارع", "دهقان", "باغات", "ciftci", "ciftlik", "bahce", "farmer",
          "farm", "orchard", "ranch", "grower", "vineyard", "plantation", "فلاح", "مزارع", "фермер", "ферма", "садовод", "fermer", "dehqon", "деҳқон"]
SELLER = ["فروشگاه", "فروش", "نمایندگی", "عاملیت", "پخش", "بنکدار", "عمده", "مغازه", "فروشنده", "توزیع", "تامین", "لوازم", "shop", "store",
          "dealer", "distributor", "distribution", "seller", "retail", "wholesale", "supplier", "supplies", "supply", "bayi", "satis", "magaza",
          "toptan", "perakende", "nalbur", "dukkan", "متجر", "موزع", "بيع", "توزيع", "محل", "магазин", "продаж", "оптом", "дилер",
          "поставщик", "dokon", "savdo", "sotuv", "ulgurji"]
MAKER = ["تولید", "تولیدی", "کارخانه", "شرکت", "صنایع", "صنعتی", "مهندسی", "سازنده", "پلاستیک", "manufactur", "factory", "industr",
         "engineering", "producer", "production", "plastic", "uretim", "fabrika", "sanayi", "muhendislik", "imalat", "plastik", "ltd",
         "مصنع", "انتاج", "شركة", "صناعات", "هندسة", "завод", "производ", "инжиниринг"]
ORG = ["جهادکشاورزی", "سازمان", "اداره", "تعاونی", "اتحادیه", "انجمن", "نظامصنفی", "مرکزتحقیقات", "پژوهشکده", "دانشگاه", "دانشکده",
       "موسسه", "بنیاد", "شهرداری", "ابمنطقهای", "منابعطبیعی", "kooperatif", "birligi", "odasi", "bakanligi", "mudurlugu", "universite",
       "fakulte", "enstitu", "dernek", "vakfi", "belediye", "cooperative", "coop", "association", "union", "ministry", "university",
       "institute", "research", "academy", "foundation", "council", "chamber", "federation", "extension", "وزارة", "جامعة", "جمعية",
       "تعاونية", "اتحاد", "هيئة", "министерств", "университет", "институт", "ассоциац", "кооператив"]
# parts of ordinary words that would match the trade words by chance — removed before comparing
STOP = ["کودک", "کشتی", "کشتار", "کشته", "کشتن", "serap", "seray", "seraf", "serab", "farmasi", "farmacia", "farmacy", "pharma", "farmac",
        "fidel", "fidelity", "dripping", "agrippa", "sprayart", "hairspray", "bodyspray", "پمپاژ"]
# Instagram's own categories (English names, as the page shows them) → a label; fragments, folded
CATEGORY = {
    "farmer": ["farm", "agricultur", "ranch", "orchard", "plantnursery", "vineyard"],
    "seller": ["shopping", "retail", "store", "wholesale", "distributor", "dealer", "supplier", "hardware", "ecommerce",
               "commercial", "agriculturalsupply", "homeimprovement", "gardencenter"],
    "maker": ["industrial", "manufactur", "engineering", "company", "factory", "machinery", "construction", "business",
              "productservice", "consulting", "technology", "agriculturalcooperative"],
    "org": ["government", "nonprofit", "nongovernmental", "education", "university", "college", "school", "association",
            "organization", "community", "cooperative", "publicservice", "research", "library", "museum", "media"],
    "other": ["personalblog", "artist", "musician", "athlete", "actor", "creator", "publicfigure", "entertainment", "gamer",
              "photographer", "beauty", "fashion", "food", "restaurant", "cafe", "fitness", "digitalcreator", "videocreator"],
}
LABEL_FA = {"farmer": "کشاورز", "seller": "فروشنده یا نماینده", "maker": "تولیدکننده یا شرکت", "org": "سازمان یا نهاد",
            "other": "نامرتبط", "unknown": "هنوز خوانده نشده"}

FINAL_MAX = 128   # 20 + 30 business + 20 label + 15 phone + 5 mail + 5 link + 20 trade + 10 followers + 3 posts


def _folded(words):
    return [(w, fold(w)) for w in words if fold(w)]


_B, _C, _A, _F, _S, _M, _O = (_folded(x) for x in (BUSINESS, CORE, AGRI, FARMER, SELLER, MAKER, ORG))
_T = _C + _A
_STOP = sorted({fold(w) for w in STOP}, key=len, reverse=True)


def hits(text, words):
    """The words (as written) that appear in text, compared folded. Two-letter words must be a whole part of the name."""
    raw = (text or "").lower()
    f = fold(text)
    for stop in _STOP:   # «کودک» is no fertiliser, «Serap» no greenhouse, «farmasi» no farm
        f = f.replace(stop, " ")
    out = []
    for w, fw in words:
        if len(fw) <= 2:
            parts = {fold(p) for p in raw.replace(".", " ").replace("_", " ").replace("-", " ").split()}
            if fw in parts:
                out.append(w)
        elif fw in f:
            out.append(w)
    return out


def category_label(category):
    """Instagram's category → a label, by the most specific fragment that fits («Agricultural supply» is a seller, not a farm)."""
    c = fold(category)
    if not c:
        return None
    best, size = None, 0
    for label, parts in CATEGORY.items():
        for part in parts:
            if part in c and len(part) > size:
                best, size = label, len(part)
    return best


def pre_score(person, trade_words=()):
    """0..100 from the list alone (no request). Returns (score, reasons)."""
    text = f"{person.get('username') or ''} {person.get('full_name') or ''}"
    score, why = 50, []
    if person.get("private"):
        score -= 30
        why.append("خصوصی")
    if person.get("default_avatar"):
        score -= 15
        why.append("بدون عکس پروفایل")
    if person.get("verified"):
        score += 5
        why.append("تیک آبی")
    core, agri = hits(text, _C + _folded(trade_words)), hits(text, _A)
    if core:
        score += 30 + (5 if agri else 0)
        why.append("کلمهٔ آبیاری و آب‌پاشی: " + "، ".join(dict.fromkeys(core[:3])))
    elif agri:
        score += 20
    if agri:
        why.append("کلمهٔ کشاورزی: " + "، ".join(dict.fromkeys(agri[:3])))
    business, org = hits(text, _B), hits(text, _O)
    if business or org:
        score += 15
        why.append(("کلمهٔ کسب‌وکار: " if business else "کلمهٔ سازمان: ") + "، ".join(dict.fromkeys((business or org)[:3])))
    name = person.get("username") or ""
    if sum(ch.isdigit() for ch in name) >= 4:
        score -= 5
        why.append("یوزرنیم پر از عدد")
    return max(0, min(100, score)), why


def label_of(profile, person=None):
    """farmer / seller / maker / other for a read profile; 'unknown' when it was not read."""
    if not profile:
        return "unknown"
    by_cat = category_label(profile.get("category"))
    if by_cat:
        return by_cat
    text = f"{profile.get('biography') or ''} {profile.get('full_name') or ''} {profile.get('username') or ''}"
    # the label whose words cover the most of the text wins: «جهاد کشاورزی» (an organisation) over the «کشاورز» inside it
    weight = {k: sum(len(fold(x)) for x in hits(text, w)) for k, w in (("org", _O), ("maker", _M), ("seller", _S), ("farmer", _F))}
    best = max(weight, key=weight.get)
    if weight[best]:
        return best
    return "maker" if profile.get("is_business") else "other"


def final(profile, person=None, trade_words=()):
    """0..100 after the profile was read, with the label and the reasons (best first)."""
    more = profile.get("more") or {}
    contact = more.get("contact") or {}
    kind = more.get("account_type")
    bio = f"{profile.get('biography') or ''} {profile.get('full_name') or ''}"
    score, why = 20, []
    if profile.get("is_business") or kind == 2:
        score += 30
        why.append("حساب کسب‌وکار")
    elif kind == 3:
        score += 10
        why.append("حساب کریتور")
    label = label_of(profile, person)
    if profile.get("category"):
        why.append("دسته: " + profile["category"])
    if label in ("farmer", "seller", "maker", "org"):
        score += 20
    elif label == "other" and profile.get("category"):
        score -= 10
    if contact.get("phone"):
        score += 15
        why.append("شمارهٔ عمومی")
    if contact.get("email"):
        score += 5
        why.append("ایمیل عمومی")
    if profile.get("links"):
        score += 5
        why.append("لینک یا وب‌سایت")
    core, agri = hits(bio, _C + _folded(trade_words)), hits(bio, _A)
    if core or agri:
        score += 20 if core else 12
        why.append(("کلمهٔ آبیاری در بیو: " if core else "کلمهٔ کشاورزی در بیو: ") + "، ".join(dict.fromkeys((core or agri)[:3])))
    followers = profile.get("followers") or 0
    score += min(10, round(2.5 * math.log10(followers + 1)))
    if (profile.get("posts") or 0) >= 10:
        score += 3
    if profile.get("is_private"):
        score -= 30
        why.append("خصوصی")
    # the most a profile can collect is 128: scaled, so only a perfect one is 100 and strong ones stay apart
    return max(0, min(100, round(score * 100 / FINAL_MAX))), label, why

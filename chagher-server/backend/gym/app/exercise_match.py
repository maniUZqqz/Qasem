# -*- coding: utf-8 -*-
"""پیداکردنِ حرکتِ کتابخانه از روی متنِ برنامه.

متنِ برنامه را هوش مصنوعی (یا خودِ مربی) می‌نویسد، پس نام‌ها دقیقاً مثلِ دیتاست
نیستند: «پرس سینه با هالتر ۴×۱۰» یا «Barbell Bench Press». این ماژول نزدیک‌ترین
حرکت را پیدا می‌کند تا در PDF لینکِ آموزش بخورد.

─── چرا بازنویسی شد (۱۴۰۵/۰۷/۱۵) ───
مالک گزارش کرد «هوش مصنوعی می‌گوید جلو پا دستگاه، ما جلو پا ماشین داریم، یکی‌اند
ولی تشخیص نمی‌دهد». اندازه‌گیری روی ۱۵۳ خطِ واقعی نشان داد ۳۵٪ لینک نمی‌خورند و
ریشه‌اش کمبودِ دیتا نبود:

  · **نیم‌فاصله**: ۵۳۵ از ۱۳۲۵ نام نیم‌فاصله دارند؛ «سیمکش» و «سیم‌کش» دو واژهٔ
    جدا شمرده می‌شدند.
  · **املا**: «اسکات» صفر نتیجه می‌داد، «اسکوات» ۷۸ تا.
  · **مترادف**: ماشین/دستگاه، فلای/قفسه، کابل/سیم‌کش.

سه قاعده‌ای که از آزمونِ واقعی بیرون آمد و نباید شکسته شوند:

  ۱) **هر واژهٔ نام یک بار شمرده می‌شود، با هر شکلی که نوشته شده.** اگر «سیم‌کش»
     سه واژه (سیمکش/سیم/کش) حساب شود، نامِ دوواژه‌ایِ «ددلیفت با سیم‌کش» چهار‌واژه‌ای
     می‌شود و خطی که فقط «سیم‌کش» دارد ۷۵٪ می‌گیرد ⇒ «فیس‌پول سیم‌کش» به «ددلیفت»
     وصل می‌شد. برای همین «گروهِ واژه» داریم، نه مجموعهٔ تخت.
  ۲) **تشابهِ درصدی فقط برای واژه‌های بلند.** «پا» و «پر» ۵۰٪ شبیه‌اند ولی یکی نیستند.
  ۳) **لینکِ غلط از لینک‌نخوردن بدتر است** — ورزشکار حرکتِ اشتباه را تمرین می‌کند.
     پس آستانه‌ها محافظه‌کار مانده‌اند و نگهبانِ «وسیله» سرِ جایش است.
"""
import difflib
import re
import threading

_lock = threading.Lock()
_index = None            # [(گروه‌های واژه, external_id, نام, وزن, واژه‌های وسیله)]
_eq_vocab = set()        # همهٔ واژه‌هایی که نامِ وسیله‌اند (دمبل، هالتر، سیم‌کش…)
_vocab = set()           # واژه‌های کتابخانه — پایهٔ تشابهِ درصدی
_near_cache = {}         # واژهٔ ورودی ⇒ واژه‌های نزدیکِ کتابخانه

ZWNJ = '‌'

# واژه‌هایی که معنیِ تشخیصی ندارند و فقط نویز می‌سازند
STOP = {
    'با', 'و', 'در', 'از', 'روی', 'تا', 'ست', 'تکرار', 'ثانیه', 'دقیقه', 'هر', 'طرف',
    'the', 'a', 'with', 'on', 'to', 'of', 'and', 'for', 'sets', 'reps', 'rep', 'set',
}

# مترادف‌هایی که از روی خطاهای واقعیِ هوش مصنوعی جمع شده‌اند.
SYNONYMS = {
    'ماشین': 'دستگاه',
    'اسکات': 'اسکوات',
    'اسکوآت': 'اسکوات',
    'فلای': 'قفسه',
    'کابل': 'سیمکش',
    'کراس': 'سیمکش',
    'باربل': 'هالتر',
    'دامبل': 'دمبل',
    'بنچ': 'میز',
    'کرانچ': 'شکم',
    'پرسپا': 'پرس پا',
    'جلوبازو': 'جلو بازو',
    'پشتبازو': 'پشت بازو',
}

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
_CHARS = str.maketrans({
    '‏': '', '‎': '',                     # نشانه‌های جهت
    'ي': 'ی', 'ك': 'ک', 'ۀ': 'ه', 'ة': 'ه',
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ؤ': 'و',
    'ٔ': '', 'ّ': '', 'َ': '', 'ُ': '', 'ِ': '', 'ً': '', 'ٌ': '', 'ٍ': '', 'ْ': '',
})

NEAR_RATIO = 0.86        # «درصدِ تشابه» — زیرِ این، دو واژه یکی شمرده نمی‌شوند
MIN_NEAR_LEN = 5         # واژهٔ کوتاه فازی نمی‌شود


def _clean(s):
    """نویسه‌های بی‌ربط را برمی‌دارد ولی نیم‌فاصله را نگه می‌دارد."""
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'[0-9]+\s*[x×*]\s*[0-9]+', ' ', s)      # ۴×۱۰
    return re.sub('[^a-z؀-ۿ ' + ZWNJ + ']', ' ', s)


def _prep(text):
    return _clean((text or '').translate(_DIGITS).translate(_CHARS).lower())


def _token_groups(text):
    """هر واژه ⇒ (شکلِ پایه، همهٔ شکل‌هایش). یک واژه = یک گروه = یک شمارش."""
    groups = []
    for w in _prep(text).split():
        parts = [x for x in w.split(ZWNJ) if x]
        joined = ''.join(parts)
        if len(joined) < 2 or joined in STOP:
            continue
        canon = SYNONYMS.get(joined, joined)
        variants = set(canon.split()) | {joined}
        for x in parts:
            if len(x) > 1 and x not in STOP:
                variants.add(SYNONYMS.get(x, x))
        groups.append((canon, variants))
    return groups


def _tokens(text):
    """مجموعهٔ تختِ واژه‌ها — برای خطِ ورودی و برای واژه‌های وسیله."""
    out = set()
    for _canon, variants in _token_groups(text):
        out |= variants
    return out


def _build():
    global _index, _eq_vocab, _vocab, _near_cache
    from .models import ExerciseLibrary
    rows = list(ExerciseLibrary.objects.filter(is_active=True).values_list(
        'external_id', 'name', 'name_fa'))
    idx = []
    eq_vocab = set()
    vocab = set()
    for _, _, fa in rows:                      # واژه‌نامهٔ وسیله‌ها از خودِ نام‌ها
        if fa and ' با ' in fa:
            eq_vocab |= _tokens(fa.rsplit(' با ', 1)[1])
    for ext, en, fa in rows:
        base = _token_groups(fa) or _token_groups(en)
        idx.append((base, ext, fa or en, 1.0, None))
        vocab |= {c for c, _ in base}
        if fa and en:
            t = _token_groups(en)
            idx.append((t, ext, fa, 1.0, None))
            vocab |= {c for c, _ in t}
        # نامِ فارسی «<حرکت> با <وسیله>» است، ولی مربی و هوش مصنوعی گاهی وسیله را
        # نمی‌نویسند («دراز و نشست 3/4»). پس نامِ بی‌وسیله هم جداگانه ایندکس می‌شود،
        # با وزنِ کمی کمتر تا نامِ کاملِ هم‌خوان همیشه برنده باشد.
        if fa and ' با ' in fa:
            head, tail = fa.rsplit(' با ', 1)
            core = _token_groups(head)
            if core:
                idx.append((core, ext, fa, 0.9, _tokens(tail)))
    # نام‌های دومی که در جنگو ادمین ثبت شده‌اند — دقیقاً مثلِ نامِ اصلی عمل
    # می‌کنند. این‌جا جای تصمیمِ آدم است، وقتی الگوریتم کم می‌آورد.
    try:
        from .models import ExerciseAlias
        for alias, ext, fa, en in ExerciseAlias.objects.values_list(
                'name', 'exercise__external_id', 'exercise__name_fa', 'exercise__name'):
            g = _token_groups(alias)
            if g:
                idx.append((g, ext, fa or en, 1.0, None))
                vocab |= {c for c, _ in g}
    except Exception:
        pass            # جدول هنوز ساخته نشده یا دیتابیس در دسترس نیست

    _index = idx
    _eq_vocab = eq_vocab
    _vocab = vocab
    _near_cache = {}


def _expand(toks):
    """واژه‌های ورودی + واژه‌های کتابخانه که «به اندازهٔ کافی» شبیه‌اند.

    همان «درصدِ تشابه»: «اسکات» ⇒ «اسکوات»، «الپتیکال» ⇒ «eliptical».
    """
    out = set(toks)
    for w in toks:
        if w in _vocab or len(w) < MIN_NEAR_LEN:
            continue
        if w not in _near_cache:
            _near_cache[w] = set(
                difflib.get_close_matches(w, _vocab, n=3, cutoff=NEAR_RATIO))
        out |= _near_cache[w]
    return out


def find_exercise(line, min_score=0.6, with_score=False):
    """نزدیک‌ترین حرکت به این خط را برمی‌گرداند یا None.

    معیار: چند درصد از واژه‌های نامِ حرکت در این خط آمده است. آستانهٔ ۰٫۶ از روی
    نمونه‌های واقعی انتخاب شد: پایین‌تر از آن، «پرس پا» به «پرس سینه» وصل می‌شد.

    with_score=True ⇒ (external_id, نام, درصدِ تشابه).
    """
    with _lock:
        if _index is None:
            _build()
    raw = _tokens(line)
    if not raw:
        return None
    toks = _expand(raw)
    # ⚠ «وسیلهٔ خط» از واژه‌های خام خوانده می‌شود، نه گسترش‌یافته: گسترشِ فازی
    #   گاهی وسیله‌ای اضافه می‌کند که کاربر ننوشته و نگهبان بی‌دلیل سخت می‌گیرد.
    line_eq = raw & _eq_vocab
    best, best_score = None, 0.0
    for groups, ext, label, weight, eq_toks in _index:
        if not groups:
            continue
        hit = sum(1 for _c, variants in groups if variants & toks)
        if not hit:
            continue
        # ورودیِ «بی‌وسیله» وقتی پذیرفته است که خطِ برنامه هم وسیلهٔ دیگری نگفته باشد؛
        # وگرنه «اسکوات با هالتر» به «اسکوات با دمبل» وصل می‌شد.
        if eq_toks is not None and line_eq and not (line_eq & eq_toks):
            continue
        if eq_toks is not None:
            # نامِ بی‌وسیله شاهدِ ضعیف‌تری است: یک‌واژه‌ای‌ها («چرخش»، «پرس») کنار
            # گذاشته می‌شوند و بقیه باید تقریباً کامل در خط آمده باشند. با آستانهٔ
            # ۰٫۶، «چرخش آرام شانه» به «چرخش با سیم‌کش» وصل می‌شد.
            if len(groups) < 2 or hit / len(groups) < 0.8:
                continue
        score = (hit / len(groups)) * weight
        # نامِ بلندتر که کامل داخلِ خط آمده، بر نامِ کوتاه ترجیح دارد
        score += 0.01 * len(groups) if hit == len(groups) else 0
        if score > best_score:
            best, best_score = (ext, label), score
    if best_score < min_score:
        return None
    if with_score:
        return best[0], best[1], round(min(best_score, 1.0), 3)
    return best


def reset_cache():
    global _index, _near_cache
    with _lock:
        _index = None
        _near_cache = {}


def note_unmatched(name, line='', source='ai'):
    """نامی که تطبیق نخورد را در جدولِ «کارِ باقی‌مانده» ثبت می‌کند.

    عمداً بی‌صداست: اگر ثبت نشد، ساختِ PDF نباید بشکند. شمارنده بالا می‌رود تا
    معلوم شود کدام نام بیشتر تکرار می‌شود و اول باید سراغش رفت.
    """
    name = (name or '').strip()[:200]
    if not name:
        return
    try:
        from django.db.models import F
        from .models import UnmatchedExercise
        rows = UnmatchedExercise.objects.filter(name=name)
        if rows.update(seen_count=F('seen_count') + 1) == 0:
            UnmatchedExercise.objects.create(
                name=name, sample_line=(line or name)[:300], source=source)
        elif source == 'manual':
            # اگر هم از هوش مصنوعی آمده هم دستی، «هر دو» را نشان بده
            rows.exclude(source__in=['manual', 'both']).update(source='both')
    except Exception:
        pass

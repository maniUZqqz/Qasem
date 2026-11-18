"""A hand-checked set of Persian marketing sentences for the EZAFE check (round 3 of the review).

The lead's rule was: the automatic ezafe must be conservative, and its two kinds of mistake must be counted on at least 150 real
marketing sentences, before and after:

  * WRONG ezafe    the voice links two words that the writer did not link («چغرِ برنامه» in «با چغر برنامه بساز»)
  * MISSING ezafe  the voice does not link two words that a careful reader links («برنامهٔ شما را»)

Every sentence below is written in the style of the owner's own product copy (a fitness-coaching app, its store, coaching and food
tips, general shop copy; no price, statistic or claim about any real product) and read through by hand: a «^» after a word means
THIS WORD IS READ WITH AN EZAFE, every other word without one. A line is ``category|sentence``. The set is append-only.

``measure()`` runs the pronunciation layer over the set and counts both kinds of mistake. Words whose ezafe the SPELLING already
carries («برنامه‌های», «غذای», a written «هٔ» / kasra) are not counted on either side: the layer does not decide those.
``python manage.py shell -c "from services.audio.fa_pron import ezafe_gold as g; print(g.report())"`` prints the table.
"""
from __future__ import annotations

import re
from collections import Counter

from . import dictionary as D

ZWNJ = "‌"

GOLD_TEXT = """
chagher|چغر دستیار^ هوش^ مصنوعی^ مربی‌ها است.
chagher|چغر برنامه^ ورزشی و غذایی^ هر ورزشکار را پیش‌نویس می‌کند.
chagher|با چغر برنامه^ تمرینی بساز.
chagher|با چغر برنامه بساز.
chagher|با چغر غذا بساز و تمرین را شروع کن.
chagher|مربی برنامه می‌نویسد و چغر پیش‌نویس می‌سازد.
chagher|تصمیم^ نهایی همیشه با مربی است.
chagher|ثبت‌نام کمتر از یک دقیقه طول می‌کشد.
chagher|شروع رایگان است و به کارت^ اعتباری نیاز ندارد.
chagher|چغر جایگزین مربی نیست و فقط پیش‌نویس می‌دهد.
chagher|با چغر چغرتر شو.
chagher|کتابخانه^ حرکت‌ها بیش از هزار حرکت دارد.
chagher|هر حرکت گیف و عکس دارد.
chagher|محیط^ تمرین را انتخاب کن: خانه، خانه با دمبل یا باشگاه.
chagher|چغر نام^ ورزشکار را در برنامه می‌نویسد.
chagher|مربی خودش تصمیم^ نهایی را می‌گیرد.
chagher|برنامه^ هفتگی را در چند ثانیه ببین.
chagher|چغر پیام^ مربی را به برنامه تبدیل می‌کند.
chagher|هوش^ مصنوعی^ چغر پیش‌نویس را آماده می‌کند.
chagher|مربی برنامه را ویرایش می‌کند.
chagher|ورزشکار برنامه را در گوشی می‌بیند.
chagher|پنل^ مربی را با چغر شروع کن.
chagher|اشتراک^ ماهانه را در چغر بخرید.
chagher|چغر حرکت^ درست را نشان می‌دهد.
chagher|با چغر وقت^ مربی را آزاد کن.
train|برنامه^ تمرینی^ خود را هر هفته به‌روز کنید.
train|وزنه^ سنگین بلند نکن مگر با گرم کردن.
train|هر هفته سه جلسه^ تمرین کافی است.
train|عادت^ خوب عمر را عوض می‌کند.
train|یک مرد^ قوی وزنه را بلند کرد.
train|پلانک و اسکات و شنا حرکت‌های^ پایه هستند.
train|مربی حرکت را آهسته نشان می‌دهد.
train|عضله^ سینه را با پرس تمرین بده.
train|بدن^ شما به استراحت نیاز دارد.
train|قبل از تمرین بدن را گرم کن.
train|کیفیت^ خواب روی ریکاوری اثر دارد.
train|تمرین^ سنگین عضله می‌سازد.
train|ورزش^ منظم سلامت^ قلب را بهتر می‌کند.
train|دمبل^ سبک برای شروع مناسب است.
train|وزنه سنگین است و باید با دقت بلند شود.
train|شنا برای شانه و سینه خوب است.
train|تمرین^ امروز سبک است.
train|ساعت^ تمرین^ من عصر است.
train|سطح^ تمرین را از مبتدی شروع کنید.
train|مربی تمرین را شروع می‌کند.
train|اسکات^ سنگین را با کمربند انجام بده.
train|بعد از تمرین پروتئین بخور.
train|هدف^ اصلی^ ما سلامت است.
train|تعداد^ تکرارها را یادداشت کن.
train|مدت^ استراحت بین ست‌ها مهم است.
train|حرکت^ دوم را آهسته انجام بده.
train|دویدن^ آهسته برای شروع خوب است.
train|ورزشکار^ تازه‌کار با وزنه^ سبک شروع می‌کند.
train|علی وزنه را بلند کرد.
train|مربی تمرین^ جدید داد.
train|ورزش^ صبحگاهی انرژی می‌دهد.
train|هر روز ده دقیقه کشش انجام بده.
train|مربی علی را تشویق کرد.
train|سارا شنا را دوست دارد.
train|محمد و رضا با هم تمرین می‌کنند.
food|غذای^ سالم انرژی می‌دهد.
food|هوای^ تازه برای ورزش خوب است.
food|رژیم^ غذایی^ سالم با مربی شروع می‌شود.
food|وعده^ غذایی^ سبک بعد از تمرین بخور.
food|برنامه^ غذایی را با مربی تنظیم کن.
food|پروتئین^ کافی برای ساختن عضله لازم است.
food|دویست گرم پروتئین در روز کافی است.
food|روزی دو لیتر آب بنوش.
food|صبحانه را حذف نکن.
food|گوشت و ماهی منبع^ خوب^ پروتئین هستند.
food|میوه^ تازه بخور.
food|غذا خوشمزه بود.
food|برنامه عالی است.
food|چربی^ اضافه را با رژیم کم کن.
food|مصرف^ شکر را کم کن.
food|سبزی^ تازه را هر روز بخور.
food|مکمل^ ورزشی بدون نسخه مصرف نکن.
food|مکمل‌های^ ورزشی را با مشورت مصرف کن.
food|تغذیه^ سالم مهم است.
food|وعده‌های^ غذایی را منظم بخور.
food|آب^ کافی بنوش.
food|شام^ سبک بخور.
food|قهوه^ تلخ قبل از تمرین خوب است.
food|روغن^ زیتون را به سالاد اضافه کن.
food|مرغ^ پخته را با برنج بخور.
food|کاهش^ وزن با رژیم و ورزش ممکن است.
food|کنترل^ وزن به خواب هم وابسته است.
food|ماست^ کم‌چرب را به صبحانه اضافه کن.
food|نان^ سبوس‌دار انرژی^ پایدار می‌دهد.
food|برنج^ سفید را کم‌تر بخور.
food|شکلات^ تلخ را کم بخور.
food|مریم سالاد می‌خورد.
sale|قیمت^ محصول را ببینید.
sale|ارسال^ سریع داریم.
sale|خرید^ آنلاین راحت است.
sale|این بسته برای شما است.
sale|سفارش^ شما همین امروز ارسال می‌شود.
sale|پیشنهاد^ ویژه^ امروز را از دست نده.
sale|محصول^ ما ضمانت دارد.
sale|مشتری^ عزیز، سفارش^ شما ثبت شد.
sale|تخفیف^ ویژه تا آخر^ هفته ادامه دارد.
sale|کیفیت^ بالا و قیمت^ مناسب را با هم ببینید.
sale|با ثبت‌نام^ رایگان شروع کنید.
sale|پشتیبانی^ ما همیشه کنار^ شما است.
sale|ما برنامه^ شما را آماده می‌کنیم.
sale|مربی شما را راهنمایی می‌کند.
sale|فروشگاه^ ما از شنبه باز است.
sale|محصول^ جدید رسید.
sale|لیست^ قیمت را بفرستید.
sale|هزینه^ ارسال را حساب کنید.
sale|پرداخت^ امن از درگاه^ معتبر انجام می‌شود.
sale|پیام^ شما را دریافت کردیم.
sale|تجربه^ خرید^ خوبی داشته باشید.
sale|سفارش را همین حالا ثبت کنید.
sale|کد^ تخفیف را وارد کنید.
sale|اپلیکیشن را از سایت بگیرید.
sale|نسخه^ جدید^ برنامه آماده است.
sale|ما به سوال‌های^ شما جواب می‌دهیم.
sale|گارانتی^ معتبر^ محصول را بخوانید.
sale|بسته^ ما را بخرید و وقت^ خود را آزاد کنید.
brand|اپ^ چغر را نصب کنید.
brand|پنل^ چغر را باز کنید.
brand|تیم^ چغر به پیام‌ها جواب می‌دهد.
brand|حساب^ شما در چغر ساخته شد.
brand|نسخه^ جدید^ چغر آماده است.
brand|با اپ^ چغر برنامه می‌سازی.
brand|سایت^ چغر را ببینید.
brand|دستیار^ چغر شما را راهنمایی می‌کند.
gen|این دوره برای همه سطح‌ها مناسب است.
gen|دوره^ آموزشی^ ما از شنبه شروع می‌شود.
gen|مقاله^ جدید را بخوانید.
gen|وب‌سایت^ ما را ببینید.
gen|ما به کیفیت^ کار اهمیت می‌دهیم.
gen|زندگی^ سالم از امروز شروع می‌شود.
gen|یک زندگی^ سالم بسازید.
gen|سلامت^ بدن و روان مهم است.
gen|مراقبت از پوست^ صورت را فراموش نکن.
gen|انتخاب^ درست آسان نیست.
gen|تیم^ ما آماده کمک است.
gen|خدمات^ ما در همه شهرها است.
gen|شهر^ تهران پر از زندگی است.
gen|هوای^ تهران امروز آلوده است.
gen|امروز هوا سرد است.
gen|سفر^ خوب با برنامه شروع می‌شود.
gen|همراه^ ما باشید.
gen|کتاب^ من روی میز است.
gen|معلم^ من آمد.
gen|او خانه را فروخت.
gen|ما فردا شما را می‌بینیم.
gen|دوستان^ من به باشگاه می‌روند.
gen|سلام من علی هستم.
gen|ممنون از شما.
gen|ساعت^ کار^ ما از نه تا پنج است.
gen|نتیجه^ کار را ببینید.
gen|برای اطلاعات^ بیشتر تماس بگیرید.
gen|اطلاعات^ کامل^ محصول را بخوانید.
gen|پاسخ^ سوال^ شما را می‌دهیم.
gen|زمان^ تحویل^ سفارش دو روز است.
gen|طراحی^ مدرن و ساده را دوست دارید؟
gen|ما به حریم^ خصوصی^ شما احترام می‌گذاریم.
gen|مدیر^ فروشگاه پیام را دید.
gen|علی و سارا به باشگاه رفتند.
gen|رضا کتاب را خرید.
gen|پدرم مربی است.
gen|مربی برنامه^ تمرینی می‌نویسد.
gen|علی برنامه^ ورزشی نوشت.
gen|رضا کتاب^ خوب خرید.
gen|پسر بچه خوب است.
gen|دوستان^ عزیز سلام.
gen|همکاران^ گرامی، خوش آمدید.
gen|شهروندان^ محترم لطفا آرام باشید.
gen|بچه‌ها سالم رسیدند.
gen|بچه‌ها خوشحال شدند.
gen|مربی^ ما خسته شد.
gen|مادر^ من پیر است.
gen|دختر^ من ورزشکار است.
gen|نام^ شما چیست؟
gen|آدرس^ شما را بفرستید.
gen|رمز^ عبور^ خود را عوض کنید.
gen|شماره^ موبایل را وارد کنید.
gen|ایمیل^ خود را بنویسید.
gen|به نظر^ من ورزش مهم است.
gen|برای دیدن^ برنامه وارد شوید.
gen|بعد از تمرین^ سنگین استراحت کن.
gen|قبل از شروع^ تمرین بدن را گرم کن.
gen|زبان^ فارسی را دوست دارم.
gen|کار^ خوب را از امروز شروع کن.
gen|چای^ داغ را با شکر نخور.
gen|خانه^ بزرگ^ ما در شمال است.
gen|ماشین^ جدید را خریدیم.
gen|کفش^ ورزشی^ مناسب بخرید.
gen|لباس^ راحت بپوشید و کفش^ مناسب بردارید.
gen|رنگ^ آبی را دوست دارم.
gen|هدیه^ ویژه^ شما را بگیرید.
num|جلسه^ اول رایگان است.
num|تمرین^ روز^ سوم را انجام بده.
num|هفته^ اول^ برنامه آسان است.
num|نفر^ دوم هم ثبت‌نام کرد.
num|قیمت^ هر جلسه را ببینید.
num|دو جلسه^ رایگان داریم.
num|سه ماه اشتراک بخرید.
num|بیست درصد تخفیف بگیرید.
num|سه کیلو وزنه بردارید.
num|روز^ پنجم را استراحت کن.
"""

#: Written AFTER the rules were frozen and measured once, so the first set (which the rules were tuned against) does not flatter them.
HELDOUT_TEXT = """
held|محصولات^ ما با بهترین کیفیت تهیه می‌شوند.
held|تمرین در خانه هم ممکن است.
held|بهترین زمان^ تمرین صبح است.
held|اپلیکیشن^ ما رایگان نصب می‌شود.
held|هر روز نیم ساعت پیاده‌روی کنید.
held|با مشاور^ تغذیه صحبت کنید.
held|نتیجه^ تمرین به خواب^ شما بستگی دارد.
held|سارا هر روز ورزش می‌کند.
held|علی و رضا دوست^ خوبی هستند.
held|پدر^ من مربی^ بدنسازی است.
held|امسال سال^ خوبی برای شروع است.
held|این برنامه برای مبتدی‌ها مناسب است.
held|نتایج را در سه ماه ببینید.
held|مربی^ شخصی^ شما همیشه پاسخ می‌دهد.
held|سلامت^ شما برای ما مهم است.
held|ما به تیم^ خود افتخار می‌کنیم.
held|بسته^ رایگان را امتحان کنید.
held|رضا ماشین را فروخت.
held|فروشگاه^ اینترنتی^ ما شبانه‌روز باز است.
held|نسخه^ آزمایشی^ برنامه را دانلود کنید.
held|هر مربی روش^ خودش را دارد.
held|وزن^ بدن را هفته‌ای یک بار بسنجید.
held|قبل از خواب گوشی را کنار بگذارید.
held|شیر^ کم‌چرب بخورید.
held|تغذیه^ سالم و ورزش^ منظم عمر را طولانی می‌کند.
held|دوستان^ شما هم عضو شوند.
held|پیام^ مربی را بخوانید.
held|یادآوری^ تمرین را فعال کنید.
held|مشتریان^ ما راضی هستند.
held|وقت^ شما ارزشمند است.
held|هر هفته یک تمرین^ جدید دریافت کنید.
held|رمز^ شما محفوظ است.
held|بدن^ سالم، ذهن^ سالم می‌آورد.
held|سرعت^ پیشرفت^ شما به تمرین بستگی دارد.
held|مسیر^ دویدن را انتخاب کنید.
held|دوره^ رایگان^ ما شنبه شروع می‌شود.
held|شهر^ مشهد در شرق ایران است.
held|قیمت^ اشتراک^ ماهانه را ببینید.
held|گروه^ پشتیبانی^ ما پاسخ می‌دهد.
held|هدف^ شما چیست؟
held|وزنه^ سبک را با تکرار زیاد بزنید.
held|استراحت^ کافی را فراموش نکنید.
held|سلام دوست^ عزیز.
held|رضا و مریم برنامه را دیدند.
held|کاربران^ جدید هدیه می‌گیرند.
held|تمرین^ خانگی برای شروع عالی است.
held|دانلود^ برنامه از سایت^ ما انجام می‌شود.
held|اینستاگرام^ ما را دنبال کنید.
held|چغر در اینستاگرام فعال است.
held|با چغر وزنه را بلند کن.
held|بچه‌ها غذا خوردند.
held|معلم^ ورزش بچه‌ها را دوست دارد.
held|روز^ اول را سبک شروع کنید.
held|تمرین^ قدرتی و استقامتی را ترکیب کنید.
held|چغر پیش‌نویس^ برنامه می‌سازد.
held|مربی غذا می‌پزد.
held|با چغر تمرین بساز.
held|علی برنامه^ ورزشی را نوشت.
held|محمد کتاب را به مریم داد.
held|مریم کفش را پوشید و دوید.
held|هوا سرد و آسمان صاف است.
held|امروز پیاده‌روی ندارم.
held|نان و پنیر و سبزی بخور.
held|حرکت‌های^ سخت را آهسته انجام بده.
"""

_EDGE = "،.؟!:؛,!?()«»\"'"


def _norm(word: str) -> str:
    return D.canon(word).replace(ZWNJ, "")


def parse_gold(text: str | None = None) -> list[tuple[str, str, list[tuple[str, int]]]]:
    """-> [(category, sentence, [(word, n) ...])]: the words that take an ezafe, ``n`` = which occurrence of that word in the sentence."""
    rows = []
    for raw in (GOLD_TEXT if text is None else text).splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        cat, _, sentence = raw.partition("|")
        seen: Counter = Counter()
        marked: list[tuple[str, int]] = []
        for w in sentence.split():
            core = w.strip(_EDGE)
            is_marked = core.endswith("^")
            key = _norm(core.rstrip("^"))
            if not key:
                continue
            seen[key] += 1
            if is_marked:
                marked.append((key, seen[key]))
        rows.append((cat, sentence.replace("^", ""), marked))
    return rows


def _first_pass_tokens(text: str, depth: str = "lexicon"):
    from .pipeline import prepare
    return prepare(text, depth=depth, dictionary=D.Dictionary(), ezafe=False)


def measure(mark=None, *, depth: str = "lexicon", text: str | None = None) -> dict:
    """Count the wrong and missing automatic ezafes of ``mark`` (default: the product's ``ezafe.mark_ezafe``) on the gold set."""
    if mark is None:
        from .ezafe import mark_ezafe as mark
    dic = D.Dictionary()
    totals = Counter()
    by_cat: dict[str, Counter] = {}
    wrong_rows, missing_rows = [], []
    for cat, sentence, marked in parse_gold(text):
        prep = _first_pass_tokens(sentence, depth)
        mark(prep.tokens, dic)
        gold = set(marked)
        seen: Counter = Counter()
        c = by_cat.setdefault(cat, Counter())
        for t in (x for x in prep.tokens if x.kind == "word"):
            key = _norm(t.text)
            seen[key] += 1
            if t.written_ezafe or t.ezafe_inside:
                continue                      # the spelling decides these («برنامه‌های», «غذای», «هٔ»): not counted on either side
            is_gold = (key, seen[key]) in gold
            if t.ezafe and is_gold:
                totals["correct"] += 1
                c["correct"] += 1
            elif t.ezafe:
                totals["wrong"] += 1
                c["wrong"] += 1
                wrong_rows.append((sentence, t.text))
            elif is_gold:
                totals["missing"] += 1
                c["missing"] += 1
                missing_rows.append((sentence, t.text))
        totals["sentences"] += 1
        c["sentences"] += 1
    gold_total = totals["correct"] + totals["missing"]
    predicted_total = totals["correct"] + totals["wrong"]
    return {
        "sentences": totals["sentences"], "gold": gold_total, "predicted": predicted_total,
        "correct": totals["correct"], "wrong": totals["wrong"], "missing": totals["missing"],
        "precision": round(totals["correct"] / predicted_total, 4) if predicted_total else 1.0,
        "recall": round(totals["correct"] / gold_total, 4) if gold_total else 1.0,
        "by_category": {k: dict(v) for k, v in by_cat.items()},
        "wrong_rows": wrong_rows, "missing_rows": missing_rows,
    }


def report(mark=None) -> str:
    """The numbers of the conservative algorithm next to the round-3 one (``ezafe_v1``), on both sets."""
    from . import ezafe_v1
    lines = [f"{'':24}{'sentences':>10}{'gold':>7}{'said':>7}{'correct':>9}{'WRONG':>7}{'MISSING':>9}{'precision':>11}{'recall':>8}"]
    for set_name, text in (("main set", None), ("held-out set", HELDOUT_TEXT)):
        for name, fn in (("before (v1)", ezafe_v1.mark_ezafe), ("after", mark)):
            r = measure(fn, text=text)
            lines.append(f"{set_name + ' ' + name:24}{r['sentences']:>10}{r['gold']:>7}{r['predicted']:>7}{r['correct']:>9}{r['wrong']:>7}{r['missing']:>9}"
                         f"{r['precision']:>11.1%}{r['recall']:>8.1%}")
    return chr(10).join(lines)

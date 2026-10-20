# -*- coding: utf-8 -*-
"""کاتالوگِ دستگاه‌ها — فهرستی که اسکنِ دوربین از آن گزینه می‌گیرد.

قبلاً این فهرست داخلِ کد بود؛ حالا در دیتابیس است تا مدیر از جنگو ادمین
اضافه/کم/ویرایش کند. این ماژول سه کار می‌کند:

۱) `seed()` — ساختنِ ردیف‌های اولیه: هر وسیله‌ای که در کتابخانهٔ حرکت‌ها هست،
   به‌علاوهٔ دستگاه‌های پرتکرارِ باشگاه‌های ایران.
۲) `attach_exercise()` — برای هر ردیف یک حرکتِ نمونه از کتابخانه پیدا می‌کند تا
   عکس و آموزش داشته باشد (عکسِ مرجع، اگر مدیر عکسِ بهتری نگذاشته باشد).
۳) `candidates()` — فهرستِ نام‌ها + نام‌های دیگر برای مدلِ بینایی و یک نقشه از
   «نامِ ساده‌شده → ردیفِ کاتالوگ» تا تشخیصِ مدل به ردیفِ درست وصل شود.
"""
import logging

logger = logging.getLogger(__name__)

# دستگاه‌های پرتکرارِ باشگاه‌های ایران که در دیتاستِ حرکت‌ها نامِ جداگانه ندارند.
# این فقط **دانهٔ اولیه** است؛ بعد از اجرای seed، همه‌چیز از دیتابیس خوانده می‌شود.
SEED_EQUIPMENT = [
    ('تردمیل', 'دوی روی تردمیل، تردمیل برقی', 'هوازی'),
    ('دوچرخهٔ ثابت', 'دوچرخه ورزشی، اسپینینگ', 'هوازی'),
    ('الپتیکال', 'اسکی فضایی، کراس تریانر', 'هوازی'),
    ('دستگاه قایقی (روئینگ)', 'روئینگ، پاروزنی', 'هوازی'),
    ('دستگاه پرس سینه', 'پرس سینه دستگاه، چست پرس', 'سینه'),
    ('دستگاه قفسهٔ سینه (پک‌دک)', 'پک دک، باترفلای، قفسه سینه', 'سینه'),
    ('دستگاه زیربغل (لت)', 'لت پول داون، لت از جلو، زیربغل سیم‌کش', 'زیربغل'),
    ('دستگاه زیربغل قایقی', 'قایقی نشسته، سیتد رو', 'زیربغل'),
    ('دستگاه پرس سرشانه', 'شولدر پرس، سرشانه دستگاه', 'سرشانه'),
    ('دستگاه جلو پا', 'لگ اکستنشن، جلو پا نشسته', 'پا'),
    ('دستگاه پشت پا', 'لگ کرل، پشت پا خوابیده', 'پا'),
    ('دستگاه پرس پا', 'لگ پرس، پرس پا نشسته', 'پا'),
    ('دستگاه ساق پا', 'کاف رایز، ساق ایستاده', 'ساق'),
    ('دستگاه سرینی (باسن)', 'هیپ تراست دستگاه، گلوت', 'سرینی'),
    ('دستگاه شکم', 'کرانچ دستگاه، ab machine', 'شکم'),
    ('دستگاه فیله کمر (هایپراکستنشن)', 'هایپر اکستنشن، فیله کمر', 'کمر'),
    ('دستگاه اسمیت', 'اسمیت ماشین، هالتر ریلی', 'پا'),
    ('دستگاه هاگ اسکوات', 'هاگ پرس، اسکوات دستگاه', 'پا'),
    ('قفسِ اسکوات (رک)', 'پاور رک، اسکوات رک، قفس', 'پا'),
    ('میز پرس سینه', 'نیمکت پرس، بنچ پرس', 'سینه'),
    ('میز بالاسینه', 'نیمکت شیب‌دار، اینکلاین بنچ', 'سینه'),
    ('میز زیرسینه', 'دیکلاین بنچ', 'سینه'),
    ('میز جلو بازو (لاری)', 'لاری، پریچر کرل', 'جلو بازو'),
    ('میز شکم', 'نیمکت شکم، میز دراز و نشست', 'شکم'),
    ('سیم‌کش دوقرقره (کراس‌اور)', 'کراس اور، کابل دوطرفه', 'سینه'),
    ('سیم‌کش', 'کابل، قرقره', 'تمامِ بدن'),
    ('هالتر', 'بار، باربل', 'تمامِ بدن'),
    ('دمبل', 'دامبل', 'تمامِ بدن'),
    ('صفحهٔ وزنه', 'وزنه، پلیت', 'تمامِ بدن'),
    ('کتل‌بل', 'کتل بل، وزنهٔ دسته‌دار', 'تمامِ بدن'),
    ('بارفیکس', 'میله بارفیکس، پول آپ', 'زیربغل'),
    ('پارالل', 'دیپ، میله موازی', 'پشت بازو'),
    ('تی‌آر‌ایکس', 'TRX، کش معلق', 'تمامِ بدن'),
    ('کش ورزشی', 'کش مقاومتی، باند', 'تمامِ بدن'),
    ('توپ سوئدی', 'توپ تعادل، سوئیس بال', 'شکم'),
    ('توپ بوسو', 'بوسو', 'تمامِ بدن'),
    ('فوم رولر', 'غلتک فوم', 'تمامِ بدن'),
    ('طناب ورزشی', 'طناب زدن', 'هوازی'),
    ('طناب جنگی (بتل‌روپ)', 'بتل روپ، طناب سنگین', 'تمامِ بدن'),
    ('جعبهٔ پلایومتریک', 'باکس، جامپ باکس', 'پا'),
    ('تشک ورزشی', 'مت، زیرانداز', 'تمامِ بدن'),
    ('کیسهٔ بوکس', 'سندبگ، کیسه بوکس', 'تمامِ بدن'),
    ('وزنهٔ مچی', 'وزنه پا، وزنه دست', 'تمامِ بدن'),
]

MUSCLE_GROUPS = [
    'سینه', 'زیربغل', 'سرشانه', 'جلو بازو', 'پشت بازو', 'ساعد', 'شکم', 'کمر',
    'پا', 'سرینی', 'ساق', 'هوازی', 'تمامِ بدن',
]


def attach_exercise(row, save=True):
    """یک حرکتِ نمونه از کتابخانه به این ردیف می‌چسباند (برای عکس و آموزش).

    از همان تطبیق‌دهندهٔ لینکِ PDF استفاده می‌شود؛ اگر چیزی پیدا نشد، دست به
    ردیف نمی‌زنیم — بهتر است عکس نداشته باشد تا عکسِ دستگاهِ اشتباه داشته باشد.
    """
    from .exercise_match import find_exercise
    from .models import ExerciseLibrary

    if row.exercise_id:
        return False

    def pick(qs):
        """حرکتی که عکس دارد ترجیح دارد؛ بی‌عکس فایده‌ای ندارد."""
        return qs.exclude(thumb='').first() or qs.first()

    # ۱) خودِ همین نام در کتابخانه «وسیله» است؟ (مثلِ «ارگومتر بالاتنه»)
    #    این دقیق‌ترین راه است و باید قبل از حدس‌زدن از روی نامِ حرکت بیاید.
    names = [row.name] + row.alias_list()
    for probe in names:
        ex = pick(ExerciseLibrary.objects.filter(is_active=True, equipment_fa=probe.strip()))
        if ex is not None:
            row.exercise = ex
            if not row.muscle_group:
                row.muscle_group = ex.target_fa or ex.body_part_fa
            if save:
                row.save(update_fields=['exercise', 'muscle_group', 'updated_at'])
            return True

    # ۲) واژهٔ کلیدیِ نام («میز زیرسینه» ⇒ «زیرسینه») داخلِ نامِ حرکت
    import re as _re
    for probe in names:
        core = _re.sub(r'\(.*?\)', ' ', probe)
        core = _re.sub(r'(دستگاه|میز|قفسِ|قفس|ورزشی|ثابت)', ' ', core).strip()
        words = [w for w in core.split() if len(w) > 2]
        if not words:
            continue
        qs = ExerciseLibrary.objects.filter(is_active=True)
        for w in words:
            qs = qs.filter(name_fa__icontains=w)
        ex = pick(qs)
        if ex is not None:
            row.exercise = ex
            if not row.muscle_group:
                row.muscle_group = ex.target_fa or ex.body_part_fa
            if save:
                row.save(update_fields=['exercise', 'muscle_group', 'updated_at'])
            return True

    # ۳) آخرین تلاش: تطبیق‌دهندهٔ نامِ حرکت
    for probe in names:
        hit = find_exercise(probe, min_score=0.5)
        if hit:
            ex = ExerciseLibrary.objects.filter(external_id=hit[0]).first()
            if ex is not None:
                row.exercise = ex
                if not row.muscle_group:
                    row.muscle_group = ex.target_fa or ex.body_part_fa
                if save:
                    row.save(update_fields=['exercise', 'muscle_group', 'updated_at'])
                return True
    return False


def seed(verbose=False):
    """ردیف‌های اولیه را می‌سازد. دوباره اجرا کردنش بی‌خطر است (تکراری نمی‌سازد)."""
    from .models import EquipmentCatalog, ExerciseLibrary

    created = attached = 0

    # ۱) هر وسیله‌ای که در کتابخانهٔ حرکت‌ها هست
    lib_equipment = (ExerciseLibrary.objects.filter(is_active=True)
                     .exclude(equipment_fa__isnull=True).exclude(equipment_fa='')
                     .values_list('equipment_fa', flat=True).distinct())
    for name in lib_equipment:
        row, is_new = EquipmentCatalog.objects.get_or_create(
            name=name.strip(), defaults={'sort_order': 50}
        )
        created += int(is_new)
        if attach_exercise(row):
            attached += 1

    # ۲) دستگاه‌های پرتکرارِ باشگاه
    for order, (name, aliases, muscle) in enumerate(SEED_EQUIPMENT, start=1):
        row, is_new = EquipmentCatalog.objects.get_or_create(
            name=name,
            defaults={'aliases': aliases, 'muscle_group': muscle, 'sort_order': order},
        )
        created += int(is_new)
        if is_new is False and not row.aliases:
            row.aliases = aliases
            row.save(update_fields=['aliases', 'updated_at'])
        if attach_exercise(row):
            attached += 1

    if verbose:
        print('کاتالوگ: %d ردیفِ تازه، %d حرکتِ نمونه چسبیده' % (created, attached))
    return created, attached


def candidates(user=None):
    """(فهرستِ نام‌ها برای مدل، نقشهٔ «نامِ ساده‌شده → ردیف»)

    نام‌های دیگر هم در نقشه می‌آیند تا اگر مدل «باترفلای» گفت، به «قفسهٔ سینه»
    وصل شود. دستگاه‌های خودِ کاربر هم به فهرست اضافه می‌شوند تا نامِ تازه ساخته نشود.
    """
    from .equipment_scan import norm
    from .models import Equipment, EquipmentCatalog

    rows = list(EquipmentCatalog.objects.filter(is_active=True))
    names, by_key = [], {}
    for row in rows:
        key = norm(row.name)
        if key and key not in by_key:
            by_key[key] = row
            names.append(row.name)
        for alias in row.alias_list():
            akey = norm(alias)
            if akey and akey not in by_key:
                by_key[akey] = row

    if user is not None:
        for name in Equipment.objects.filter(user=user).values_list('name', flat=True):
            key = norm(name)
            if key and key not in by_key:
                by_key[key] = None          # نامِ خودِ باشگاه، بدونِ ردیفِ کاتالوگ
                names.append(name)

    return names, by_key

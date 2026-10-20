# -*- coding: utf-8 -*-
"""کاتالوگ پایه دستگاه‌ها و حرکات ورزشی.

این لیست برای «شروع سرد» است: تا وقتی داده واقعی کاربران کم است،
پیشنهادها از اینجا می‌آیند. با رشد سامانه، محبوبیت واقعی (تعداد ثبت
توسط کاربران) اولویت پیدا می‌کند و این لیست فقط مکمل می‌شود.

places: در چه محیط‌هایی قابل اجراست (هم‌نام با ClientProgram.TRAINING_PLACE_*)
"""

GYM = 'gym_equipment'
PUBLIC = 'public_gym'
HOME_BASIC = 'home_basic'
HOME_NONE = 'home_none'

ALL_GYM = [GYM, PUBLIC]
WITH_DUMBBELL = [GYM, PUBLIC, HOME_BASIC]
ANYWHERE = [GYM, PUBLIC, HOME_BASIC, HOME_NONE]


STARTER_CATALOG = [
    # ---------------- سینه ----------------
    {'name': 'پرس سینه هالتر', 'muscle_group': 'سینه', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'پرس سینه دمبل', 'muscle_group': 'سینه', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'پرس بالا سینه', 'muscle_group': 'سینه', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'قفسه سینه', 'muscle_group': 'سینه', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'شنا سوئدی', 'muscle_group': 'سینه', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'دیپ پارالل', 'muscle_group': 'سینه', 'category': 'وزن بدن', 'places': ALL_GYM},

    # ---------------- پشت ----------------
    {'name': 'زیربغل سیم‌کش (لت)', 'muscle_group': 'پشت', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'بارفیکس', 'muscle_group': 'پشت', 'category': 'وزن بدن', 'places': ALL_GYM},
    {'name': 'زیربغل دمبل تک‌خم', 'muscle_group': 'پشت', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'قایقی (روئینگ)', 'muscle_group': 'پشت', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'ددلیفت', 'muscle_group': 'پشت', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'کشش کش از بالا', 'muscle_group': 'پشت', 'category': 'کش ورزشی', 'places': [HOME_BASIC, PUBLIC, GYM]},

    # ---------------- پا ----------------
    {'name': 'اسکوات هالتر', 'muscle_group': 'پا', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'پرس پا', 'muscle_group': 'پا', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'جلو پا دستگاه', 'muscle_group': 'پا', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'پشت پا دستگاه', 'muscle_group': 'پا', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'لانج با دمبل', 'muscle_group': 'پا', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'اسکوات با وزن بدن', 'muscle_group': 'پا', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'ساق پا ایستاده', 'muscle_group': 'پا', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'پل باسن (گلوت بریج)', 'muscle_group': 'پا', 'category': 'وزن بدن', 'places': ANYWHERE},

    # ---------------- سرشانه ----------------
    {'name': 'پرس سرشانه هالتر', 'muscle_group': 'سرشانه', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'پرس سرشانه دمبل', 'muscle_group': 'سرشانه', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'نشر جانب دمبل', 'muscle_group': 'سرشانه', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'نشر خم', 'muscle_group': 'سرشانه', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'شنا شیب معکوس (پایک)', 'muscle_group': 'سرشانه', 'category': 'وزن بدن', 'places': ANYWHERE},

    # ---------------- بازو ----------------
    {'name': 'جلو بازو هالتر', 'muscle_group': 'بازو', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'جلو بازو دمبل', 'muscle_group': 'بازو', 'category': 'دمبل', 'places': WITH_DUMBBELL},
    {'name': 'پشت بازو سیم‌کش', 'muscle_group': 'بازو', 'category': 'دستگاه و هالتر', 'places': ALL_GYM},
    {'name': 'پشت بازو دیپ روی نیمکت', 'muscle_group': 'بازو', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'جلو بازو با کش', 'muscle_group': 'بازو', 'category': 'کش ورزشی', 'places': [HOME_BASIC, PUBLIC, GYM]},

    # ---------------- شکم و مرکز بدن ----------------
    {'name': 'کرانچ شکم', 'muscle_group': 'شکم', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'پلانک', 'muscle_group': 'شکم', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'زیرشکم آویزان', 'muscle_group': 'شکم', 'category': 'وزن بدن', 'places': ALL_GYM},
    {'name': 'کوهنوردی (مانتین کلایمر)', 'muscle_group': 'شکم', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'چرخش روسی', 'muscle_group': 'شکم', 'category': 'وزن بدن', 'places': ANYWHERE},

    # ---------------- هوازی ----------------
    {'name': 'تردمیل', 'muscle_group': 'هوازی', 'category': 'هوازی', 'places': ALL_GYM},
    {'name': 'دوچرخه ثابت', 'muscle_group': 'هوازی', 'category': 'هوازی', 'places': ALL_GYM},
    {'name': 'طناب زدن', 'muscle_group': 'هوازی', 'category': 'هوازی', 'places': ANYWHERE},
    {'name': 'برپی', 'muscle_group': 'هوازی', 'category': 'وزن بدن', 'places': ANYWHERE},
    {'name': 'الپتیکال', 'muscle_group': 'هوازی', 'category': 'هوازی', 'places': ALL_GYM},
]


def starter_items_for_place(training_place=None):
    """آیتم‌های کاتالوگ پایه، در صورت نیاز فیلترشده بر اساس محیط تمرین."""
    if not training_place:
        return list(STARTER_CATALOG)
    return [item for item in STARTER_CATALOG if training_place in item['places']]


def muscle_groups():
    """فهرست گروه‌های عضلانی موجود در کاتالوگ (برای فیلتر در فرانت)."""
    seen = []
    for item in STARTER_CATALOG:
        if item['muscle_group'] not in seen:
            seen.append(item['muscle_group'])
    return seen

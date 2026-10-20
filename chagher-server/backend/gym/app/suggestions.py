# -*- coding: utf-8 -*-
"""پیشنهاد دستگاه‌ها و حرکات ورزشی بر اساس محبوبیت در کل سامانه.

منطق: هرچه دستگاهی را کاربران بیشتری ثبت کرده باشند، بالاتر پیشنهاد می‌شود.
تا وقتی داده واقعی کم است، کاتالوگ پایه جای خالی را پر می‌کند تا پیشنهادها
از روز اول مفید باشند.

برای هر دو دنیا کار می‌کند:
- مربی (B2B): چه چیزی به تجهیزات باشگاهم اضافه کنم (و چه چیزی را قبلاً دارم)
- کاربر شخصی (B2C): چه حرکاتی در محیط تمرین من (خانه/باشگاه عمومی) رایج است
"""
from django.db.models import Count

from .exercise_catalog import starter_items_for_place
from .models import Equipment

SOURCE_COMMUNITY = 'community'  # از روی ثبت واقعی کاربران
SOURCE_STARTER = 'starter'      # از کاتالوگ پایه

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# حداقل تعداد کاربرِ ثبت‌کننده تا یک نام «پرکاربرد» شمرده شود.
# بدون این، یک ورودی اشتباه یا آزمایشی (مثل «node») به همه پیشنهاد می‌شد.
MIN_USAGE_FOR_SUGGESTION = 2


def _normalize(name):
    return (name or '').strip()


def _community_items(training_place=None):
    """دستگاه‌هایی که کاربران ثبت کرده‌اند، به ترتیب تعداد کاربران ثبت‌کننده."""
    rows = (
        Equipment.objects
        .exclude(name='')
        .exclude(name__isnull=True)
        .values('name')
        .annotate(usage_count=Count('user', distinct=True))
        .order_by('-usage_count', 'name')
    )

    # برای هر نام، یک نمونه برای گرفتن گروه عضلانی/دسته‌بندی
    samples = {}
    for eq in Equipment.objects.select_related('category').all():
        key = _normalize(eq.name)
        if key and key not in samples:
            samples[key] = eq

    # نام‌های موجود در کاتالوگ پایه معتبر شناخته می‌شوند حتی با یک‌بار ثبت
    catalog_names = {i['name'] for i in starter_items_for_place(None)}

    items = []
    for row in rows:
        name = _normalize(row['name'])
        if not name:
            continue
        # فیلتر کیفیت: یا باید چند کاربر ثبتش کرده باشند، یا در کاتالوگ پایه باشد
        if row['usage_count'] < MIN_USAGE_FOR_SUGGESTION and name not in catalog_names:
            continue
        sample = samples.get(name)
        items.append({
            'name': name,
            'muscle_group': (sample.muscle_group if sample else '') or '',
            'category': (sample.category.name if sample and sample.category else '') or '',
            'usage_count': row['usage_count'],
            'source': SOURCE_COMMUNITY,
        })

    # محیط تمرین روی داده کاربران قابل تشخیص نیست؛ فقط وقتی محیط خانگی
    # درخواست شده باشد، اقلام باشگاهی نباید پیشنهاد شوند.
    if training_place in ('home_none', 'home_basic'):
        starter_names = {i['name'] for i in starter_items_for_place(training_place)}
        items = [i for i in items if i['name'] in starter_names]

    return items


def _starter_items(training_place=None):
    return [{
        'name': item['name'],
        'muscle_group': item['muscle_group'],
        'category': item['category'],
        'usage_count': 0,
        'source': SOURCE_STARTER,
    } for item in starter_items_for_place(training_place)]


def get_suggestions(user=None, training_place=None, muscle_group=None,
                    search=None, limit=DEFAULT_LIMIT):
    """فهرست پیشنهادها.

    ترتیب: پرتکرارترین‌های واقعی، سپس کاتالوگ پایه.
    اگر کاربر مربی باشد، آیتم‌هایی که قبلاً ثبت کرده با already_added=True
    علامت می‌خورند تا فرانت بتواند آن‌ها را غیرفعال یا فیلتر کند.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    items = _community_items(training_place)
    seen = {i['name'] for i in items}

    for item in _starter_items(training_place):
        if item['name'] not in seen:
            items.append(item)
            seen.add(item['name'])

    if muscle_group:
        needle = muscle_group.strip()
        items = [i for i in items if needle in (i['muscle_group'] or '')]

    if search:
        needle = search.strip()
        items = [i for i in items if needle in i['name']]

    # آیتم‌های خود کاربر (فقط برای کسی که تجهیزات ثبت می‌کند)
    owned = set()
    if user is not None and getattr(user, 'is_authenticated', False):
        owned = {
            _normalize(n)
            for n in Equipment.objects.filter(user=user).values_list('name', flat=True)
        }

    for item in items:
        item['already_added'] = item['name'] in owned

    # پرتکرارها اول، بعد کاتالوگ پایه (به ترتیب اصلی خودش)
    items.sort(key=lambda i: (-i['usage_count'], i['source'] != SOURCE_COMMUNITY))

    return items[:limit]

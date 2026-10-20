# -*- coding: utf-8 -*-
"""برنامهٔ دستیِ مربی — بدونِ هوش مصنوعی.

مربی خودش جلسه‌ها و حرکت‌ها را می‌چیند. این ماژول دو کار می‌کند:

۱) ساختارِ چیده‌شده را به همان **متنی** تبدیل می‌کند که سازندهٔ PDF می‌فهمد
   («## جلسه 1» و بعد «1. نامِ حرکت — 4×10»). چون نامِ حرکت از خودِ کتابخانه
   برداشته می‌شود، لینکِ صفحهٔ آموزش در PDF هم بی‌کم‌وکاست می‌خورد.
۲) حسابِ «چند برنامهٔ رایگان برای این ورزشکار مانده» را نگه می‌دارد؛ سهمِ
   رایگان و هزینهٔ توکن، هر دو از تنظیماتِ جنگو ادمین خوانده می‌شوند، نه از کد.

عددها عمداً انگلیسی نوشته می‌شوند؛ خودِ سازندهٔ PDF آن‌ها را فارسی می‌کند و
«4×10» را در جاسازیِ چپ‌به‌راست می‌پیچد تا وارونه چاپ نشود.
"""
import re

# نویسه‌های عربیِ پرتکرار که باید فارسی شوند تا شمارشِ «همین ورزشکار» درست باشد
_ARABIC_FIX = {'ي': 'ی', 'ك': 'ک', 'ۀ': 'ه', 'إ': 'ا', 'أ': 'ا', 'ء': ''}
MAX_DAYS = 7
MAX_EXERCISES_PER_DAY = 30


def norm_name(name):
    """نامِ ورزشکار را یکدست می‌کند تا «رضا  احمدي» و «رضا احمدی» یکی شمرده شوند."""
    s = (name or '').strip()
    for a, b in _ARABIC_FIX.items():
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s).strip()


def _num(v):
    """عددِ ورودی را به رشتهٔ تمیز تبدیل می‌کند (ورودیِ کاربر ممکن است هر چیزی باشد)."""
    if v is None:
        return ''
    s = str(v).strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    s = re.sub(r'[^0-9\-–]', '', s)
    return s.strip('-–')


def exercise_line(ex):
    """یک حرکت → یک خطِ متنِ برنامه، بدونِ شمارهٔ ردیف."""
    name = norm_name(ex.get('name'))
    sets, reps = _num(ex.get('sets')), _num(ex.get('reps'))
    bits = []
    if sets and reps:
        bits.append('%s×%s' % (sets, reps))
    elif reps:
        bits.append('%s تکرار' % reps)
    elif sets:
        bits.append('%s ست' % sets)
    dur = norm_name(ex.get('duration'))
    if dur:
        bits.append(dur)
    rest = _num(ex.get('rest'))
    if rest:
        bits.append('استراحت %s ثانیه' % rest)
    line = name
    if bits:
        line += ' — ' + ' · '.join(bits)
    note = norm_name(ex.get('note'))
    if note:
        # داخلِ پرانتز می‌آید چون تطبیق‌دهندهٔ لینک، پرانتزها را نادیده می‌گیرد
        line += ' (%s)' % note
    return line


def render_workout_text(plan):
    """ساختار → متنِ برنامهٔ ورزشی.

    plan = {'days': [{'title': str, 'exercises': [{...}]}], 'notes': str}
    """
    out = []
    days = plan.get('days') or []
    for i, day in enumerate(days, 1):
        out.append('## جلسه %d' % i)
        title = norm_name(day.get('title'))
        if title:
            out.append(title)
        for j, ex in enumerate(day.get('exercises') or [], 1):
            out.append('%d. %s' % (j, exercise_line(ex)))
        note = norm_name(day.get('note'))
        if note:
            out.append(note)
        if i == len(days):
            # نکتهٔ کلیِ مربی هم داخلِ آخرین جلسه می‌آید؛ سرتیترِ تازه ساخته
            # نمی‌شود چون سازندهٔ PDF فقط سرتیترِ «جلسه» و «روز» را می‌شناسد.
            notes = norm_name(plan.get('notes'))
            if notes:
                out.append(notes)
        out.append('')
    return '\n'.join(out).strip() + '\n'


def render_meal_text(plan):
    """متنِ برنامهٔ غذاییِ دستی: تیترهای آزادِ مربی + جایگاهِ جدای مکمل.

    مربی هر تعداد تیتر می‌سازد («صبحانه»، «میان‌وعدهٔ قبل تمرین»، «روزِ استراحت»…)
    و زیرش هرچه می‌خواهد می‌نویسد. سازندهٔ PDF سرتیترهای `##` را می‌شناسد و
    سرتیترِ «مکمل» را در کادرِ جداگانه می‌کشد — همان کادری که در PDFِ هوش مصنوعی
    هست. پس خروجیِ دستی و هوشمند یک شکل دیده می‌شوند.

    `meal_text` قدیمی هم پذیرفته می‌شود تا نسخه‌های قبلیِ اپ نشکنند.
    """
    parts = []
    for section in plan.get('meal_sections') or []:
        title = norm_name(section.get('title'))
        body = (section.get('content') or '').strip()
        if not title and not body:
            continue
        if title:
            parts.append('## %s' % title)
        if body:
            parts.extend(line.rstrip() for line in body.splitlines())
        parts.append('')

    supplements = plan.get('supplements') or []
    if isinstance(supplements, str):
        supplements = [{'title': '', 'content': supplements}]
    supp_lines = []
    for item in supplements:
        title = norm_name(item.get('title'))
        body = (item.get('content') or '').strip()
        if title and body:
            supp_lines.append('%s: %s' % (title, body))
        elif title or body:
            supp_lines.append(title or body)
    if supp_lines:
        # سرتیترِ «مکمل» را سازندهٔ PDF می‌شناسد و کادرِ جدا می‌کشد
        parts.append('## مکمل‌ها و ویتامین‌ها')
        parts.extend(supp_lines)
        parts.append('')

    legacy = (plan.get('meal_text') or '').strip()
    if legacy:
        parts.append(legacy)

    text = '\n'.join(parts).strip()
    return text or None


def settings_snapshot():
    """(سهمِ رایگانِ هر ورزشکار، هزینهٔ توکن) از تنظیماتِ ادمین."""
    from .models import PlatformSettings
    st = PlatformSettings.get_solo()
    return st.manual_program_free_quota, st.manual_program_token_cost


def count_manual(coach, gym_client=None, name=None):
    """چند برنامهٔ دستی تا حالا برای این ورزشکار ساخته شده است."""
    from .models import ClientProgram
    qs = ClientProgram.objects.filter(source=ClientProgram.SOURCE_MANUAL)
    if gym_client is not None:
        # ورزشکارِ ثبت‌شده: شمارش روی خودِ رکورد، حتی اگر نامش عوض شود
        return qs.filter(gym_client=gym_client).count()
    return qs.filter(user=coach, gym_client__isnull=True, name=norm_name(name)).count()


def quota_state(coach, gym_client=None, name=None):
    """وضعیتِ سهمِ رایگانِ این ورزشکار و هزینهٔ برنامهٔ بعدی."""
    free_quota, cost = settings_snapshot()
    used = count_manual(coach, gym_client, name)
    remaining = max(0, free_quota - used)
    next_cost = 0 if remaining > 0 else cost
    return {
        'athlete_name': norm_name(name) if name else (gym_client.name if gym_client else ''),
        'gym_client': gym_client.id if gym_client else None,
        'free_quota': free_quota,
        'used': used,
        'free_remaining': remaining,
        'token_cost': cost,
        'next_is_free': next_cost == 0,
        'next_cost': next_cost,
        'balance': coach.get_effective_token_balance(),
    }


def clean_plan(data, library_names=None):
    """ساختارِ ورودیِ کاربر را وارسی و تمیز می‌کند. خطا → ValueError با پیامِ فارسی.

    library_names: {external_id: name_fa} — اگر مربی حرکت را از کتابخانه انتخاب
    کرده باشد، نامِ رسمیِ کتابخانه جای نامِ تایپ‌شده می‌نشیند تا لینکِ PDF بخورد.
    """
    days_in = data.get('days') or []
    meal_sections_in = data.get('meal_sections') or []
    supplements_in = data.get('supplements') or []
    has_meal = bool(meal_sections_in or supplements_in or (data.get('meal_text') or '').strip())
    # برنامه می‌تواند فقط ورزشی، فقط غذایی، یا هر دو باشد
    if not isinstance(days_in, list):
        raise ValueError('ساختارِ جلسه‌ها درست نیست.')
    if not days_in and not has_meal:
        raise ValueError('حداقل یک جلسهٔ تمرین یا یک بخشِ غذایی لازم است.')
    if len(days_in) > MAX_DAYS:
        raise ValueError('بیشتر از %d جلسه نمی‌شود.' % MAX_DAYS)

    days = []
    for i, d in enumerate(days_in, 1):
        if not isinstance(d, dict):
            raise ValueError('جلسهٔ %d درست نیست.' % i)
        ex_in = d.get('exercises')
        if not isinstance(ex_in, list) or not ex_in:
            raise ValueError('جلسهٔ %d هیچ حرکتی ندارد.' % i)
        if len(ex_in) > MAX_EXERCISES_PER_DAY:
            raise ValueError('جلسهٔ %d بیشتر از %d حرکت دارد.' % (i, MAX_EXERCISES_PER_DAY))
        exercises = []
        for j, ex in enumerate(ex_in, 1):
            if not isinstance(ex, dict):
                raise ValueError('حرکتِ %d از جلسهٔ %d درست نیست.' % (j, i))
            ext = (ex.get('exercise_id') or '').strip() or None
            name = norm_name(ex.get('name'))
            if ext and library_names is not None:
                if ext not in library_names:
                    raise ValueError('حرکتِ «%s» در کتابخانه نیست.' % ext)
                name = library_names[ext]
            if not name:
                raise ValueError('نامِ حرکتِ %d از جلسهٔ %d خالی است.' % (j, i))
            exercises.append({
                'exercise_id': ext,
                'name': name,
                'sets': _num(ex.get('sets')),
                'reps': _num(ex.get('reps')),
                'rest': _num(ex.get('rest')),
                'duration': norm_name(ex.get('duration')),
                'note': norm_name(ex.get('note')),
            })
        days.append({
            'title': norm_name(d.get('title')),
            'note': norm_name(d.get('note')),
            'exercises': exercises,
        })

    # بخش‌های غذایی: تیتر آزاد، محتوای آزاد، بی‌محدودیتِ تعداد (سقفِ ۴۰ فقط
    # برای جلوگیری از ورودیِ بی‌انتها)
    meal_sections = []
    for section in (meal_sections_in if isinstance(meal_sections_in, list) else [])[:40]:
        if not isinstance(section, dict):
            continue
        title = norm_name(section.get('title'))
        content = (section.get('content') or '').strip()
        if title or content:
            meal_sections.append({'title': title, 'content': content})

    supplements = []
    raw_supp = supplements_in if isinstance(supplements_in, list) else (
        [{'title': '', 'content': supplements_in}] if supplements_in else [])
    for item in raw_supp[:40]:
        if not isinstance(item, dict):
            continue
        title = norm_name(item.get('title'))
        content = (item.get('content') or '').strip()
        if title or content:
            supplements.append({'title': title, 'content': content})

    return {
        'days': days,
        'notes': norm_name(data.get('notes')),
        'meal_sections': meal_sections,
        'supplements': supplements,
        'meal_text': (data.get('meal_text') or '').strip() or None,
    }

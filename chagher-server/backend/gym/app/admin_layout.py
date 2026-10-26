# -*- coding: utf-8 -*-
"""چیدمانِ صفحهٔ اولِ جنگو ادمین — ۱۴۰۵/۰۷/۲۱

مالک: «اصلاً درست و یک‌جا نیست… مثلاً تأییدِ رسیدِ پرداخت جا نداشت. همه‌چیز
خیلی شلوغ توی پنجرهٔ app است و مرتب نیست.»

جنگو همهٔ مدل‌ها را زیرِ نامِ اپلیکیشن (app) می‌ریزد — ۳۹ ردیفِ پشتِ هم،
بی‌ترتیب و بی‌معنا. این فایل همان فهرست را به گروه‌های فارسیِ کاری تقسیم
می‌کند، به ترتیبی که مالک واقعاً سراغشان می‌رود.

⚠ هیچ مدلی حذف یا جابه‌جا نمی‌شود: فقط **نمایشِ** صفحهٔ اول عوض می‌شود. مسیرها،
مجوزها و خودِ صفحه‌ها دست‌نخورده‌اند. اگر مدلی اضافه شود و این‌جا نامش نیاید،
خودکار در گروهِ «سایر» می‌افتد تا هیچ‌وقت ناپدید نشود.
"""
from django.contrib import admin

# (عنوانِ گروه، توضیحِ کوتاه، [نامِ مدل‌ها به ترتیبِ دلخواه])
GROUPS = [
    ('💳 مالی، توکن و پرداخت',
     ['tokenpurchase', 'tokenrequest', 'tokenpackage', 'pricingrule',
      'discountcode', 'discountcodeusage', 'cardpaymentaccount',
      'paymentgatewayconfig', 'ledgerentry', 'accountstatement',
      'uniteconomicsreport', 'aiusagelog']),

    # اپِ جدای accounting (۱۴۰۵/۰۸/۰۳): دفترِ دوطرفه؛ «داشبورد» و «راهنما» را خودِ
    # accounting/admin.py بالای همین گروه اضافه می‌کند.
    ('📒 حسابداری (سود، زیان و شرکا)',
     ['journalentry', 'partner', 'account', 'fiscalyear', 'accountingsettings']),

    ('👥 کاربران و باشگاه‌ها',
     ['customuser', 'gymbrand', 'gymclient', 'athleteprofile',
      'programsharecode']),

    ('🏋 برنامه‌ها',
     ['clientprogram', 'aijob']),

    ('📚 کتابخانهٔ حرکت و دستگاه',
     ['exerciselibrary', 'unmatchedexercise', 'exercisealias',
      'equipmentcatalog', 'equipment', 'equipmentcategory',
      'equipmentscan', 'formchecksession', 'meal']),

    ('🌐 سایت و محتوا',
     ['homepage', 'blogpost', 'teammember', 'portfolioproject', 'portfoliocategory',
      'feature', 'contactmessage']),

    ('⚙️ تنظیمات سامانه',
     ['platformsettings', 'apiconfig', 'smsconfig', 'smsoutbox']),

    ('🔑 دسترسی و امنیت',
     ['group', 'tokenproxy']),
]

# مدل‌هایی که «کارِ منتظر» دارند: عددش کنارِ نامشان می‌آید تا توی چشم بزند
PENDING = {
    # ⚠ وضعیتِ «منتظرِ تأییدِ مدیر» در این مدل `under_review` است، نه `pending`
    #   (آن یکی یعنی «هنوز پرداخت نشده»).
    'tokenpurchase': ('رسیدِ منتظرِ تأیید',
                      lambda M: M.objects.filter(status='under_review').count()),
    'tokenrequest': ('درخواستِ باز',
                     lambda M: M.objects.filter(status='pending').count()),
    'unmatchedexercise': ('بررسی‌نشده',
                          lambda M: M.objects.filter(status='new').count()),
    'contactmessage': ('خوانده‌نشده',
                       lambda M: M.objects.filter(is_read=False).count()),
}


def _badge(model_name, model):
    """«(۳ رسیدِ منتظرِ تأیید)» — اگر چیزی منتظر باشد."""
    spec = PENDING.get(model_name)
    if not spec:
        return ''
    label, fn = spec
    try:
        n = fn(model)
    except Exception:
        return ''          # ستونی عوض شده؟ صفحهٔ ادمین نباید بشکند
    return '  ●  %d %s' % (n, label) if n else ''


def grouped_app_list(request, app_label=None):
    """فهرستِ صفحهٔ اول، دسته‌بندی‌شده."""
    original = admin.AdminSite.get_app_list(admin.site, request, app_label)

    # وقتی کاربر روی خودِ یک اپ کلیک کرده، همان صفحهٔ استانداردِ جنگو بماند
    if app_label:
        return original

    by_name, order = {}, []
    for app in original:
        for m in app['models']:
            key = m['object_name'].lower()
            m['_app_url'] = app['app_url']
            by_name[key] = m
            order.append(key)

    out, used = [], set()
    for title, names in GROUPS:
        models = []
        for nm in names:
            m = by_name.get(nm)
            if not m:
                continue        # مدلی که ثبت نشده یا کاربر مجوزش را ندارد
            used.add(nm)
            mdl = admin.site._registry and _model_of(nm)
            if mdl is not None:
                b = _badge(nm, mdl)
                if b:
                    m = dict(m, name=m['name'] + b)
            models.append(m)
        if models:
            out.append({
                'name': title,
                'app_label': 'grp_%d' % len(out),
                'app_url': models[0].get('_app_url', '/admin/'),
                'has_module_perms': True,
                'models': models,
            })

    rest = [by_name[n] for n in order if n not in used]
    if rest:
        out.append({
            'name': '📦 سایر',
            'app_label': 'grp_rest',
            'app_url': rest[0].get('_app_url', '/admin/'),
            'has_module_perms': True,
            'models': rest,
        })
    return out


def _model_of(model_name):
    for m in admin.site._registry:
        if m._meta.model_name == model_name:
            return m
    return None


def install():
    admin.site.get_app_list = grouped_app_list
    admin.site.site_header = 'مدیریتِ چغر'
    admin.site.site_title = 'چغر'
    admin.site.index_title = 'از کجا شروع کنم؟'

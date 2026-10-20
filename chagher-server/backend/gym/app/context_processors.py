# -*- coding: utf-8 -*-
"""متغیرهای مشترکِ همهٔ قالب‌ها.

`app_mode` یعنی «این صفحه از داخلِ اپِ فلاتر باز شده است». وقتی True باشد،
قالب‌ها سربرگ و پابرگِ سایت را نشان نمی‌دهند تا کاربر حس نکند از اپ بیرون
افتاده. مقدارش در نشست نوشته می‌شود (هنگامِ ورودِ یک‌باره از اپ).
"""


def app_mode(request):
    try:
        inside_app = bool(request.session.get('from_app'))
    except Exception:
        # درخواست‌های بی‌نشست (مثلِ sitemap یا robots) نباید بشکنند
        inside_app = False
    return {
        'app_mode': inside_app,
        'app_home_url': '/chagherpanel/',
    }


def site_contact(request):
    """نشانی/تلفن/ایمیل/نقشه برای همهٔ قالب‌ها — از تنظیماتِ سامانه.

    اگر دیتابیس در دسترس نبود (مثلاً هنگامِ مهاجرت) قالب نباید بشکند.
    """
    try:
        from .models import PlatformSettings
        st = PlatformSettings.get_solo()
        return {'site': {
            'address': st.contact_address,
            'phone': st.contact_phone,
            'email': st.contact_email,
            'map_url': st.map_embed_url,
        }}
    except Exception:
        return {'site': {'address': '', 'phone': '', 'email': '', 'map_url': ''}}

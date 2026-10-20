# -*- coding: utf-8 -*-
"""تفکیکِ دنیای B2C از B2B بر اساسِ نامِ میزبان.

چرا میان‌افزار و نه چکِ داخلِ هر ویو: صفحه‌ها زیاد می‌شوند و اگر قاعده در هر
ویو تکرار شود، یکی‌شان فراموش می‌شود و همان «قاطی‌شدن» برمی‌گردد.

تنظیمِ میزبان‌ها در settings است (`B2C_HOSTS`), پس با عوض‌شدنِ دامنه کد دست
نمی‌خورد.
"""
from django.conf import settings
from django.shortcuts import redirect


class B2CHostMiddleware:
    """`request.is_b2c` را می‌گذارد و نقش‌ها را به میزبانِ خودشان می‌فرستد."""

    # صفحه‌هایی که فقط مالِ مربی‌اند (روی میزبانِ B2C بسته‌اند)
    COACH_ONLY_PREFIXES = ('/panel/manual-program/',)
    # صفحه‌هایی که مالِ ورزشکارند
    ATHLETE_PATHS = ('/panel/me/',)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = (request.get_host() or '').split(':')[0].lower()
        b2c_hosts = [h.lower() for h in getattr(settings, 'B2C_HOSTS', [])]
        request.is_b2c = host in b2c_hosts
        request.b2c_host = b2c_hosts[0] if b2c_hosts else ''
        request.b2c_panel_host = (getattr(settings, 'B2C_PANEL_HOST', '')
                                  or request.b2c_host)
        request.is_b2c_panel = host == request.b2c_panel_host.lower()
        request.b2b_host = getattr(settings, 'B2B_HOST', 'chagher.ir')

        path = request.path

        # ابزارِ مربی روی میزبانِ ورزشکار باز نمی‌شود — این بی‌خطر است چون فقط
        # روی خودِ میزبانِ B2C رخ می‌دهد و مقصدش دامنهٔ اصلیِ همیشه‌بالاست.
        if request.is_b2c and path.startswith(self.COACH_ONLY_PREFIXES):
            return redirect('https://%s%s' % (request.b2b_host, path))

        # ⚠ مرزِ دو دنیا باید **دوطرفه** باشد (خواستِ مالک، ۱۴۰۵/۰۷/۱۵):
        # «سیستم B2B و B2C جدا هستند؛ ورزشکارِ باشگاه که از B2B می‌آید را نبر
        #  به B2C». تا پیش از این فقط یک طرف بسته بود: کاربرِ شخصی از B2B به
        # B2C می‌رفت، ولی مربی و ورزشکارِ باشگاه اگر آدرسِ B2C را باز می‌کردند
        # همان‌جا می‌ماندند — یعنی B2B داخلِ B2C. حالا هر کسی که «شخصی» نیست،
        # از میزبانِ B2C به دنیای خودش (B2B) برمی‌گردد.
        # ناشناس‌ها دست نمی‌خورند تا صفحهٔ ورود و لندینگِ B2C باز بماند.
        if (request.is_b2c
                and getattr(request.user, 'is_authenticated', False)
                and not getattr(request.user, 'is_personal', False)):
            return redirect('https://%s%s' % (request.b2b_host, path))

        # ⚠ مرز باید بر اساسِ **نقش** هم بسته باشد، نه فقط میزبان: ورزشکارِ شخصی
        # روی دامنهٔ اصلی هم نباید ابزارِ مربی را باز کند. (ایرادی که در بازبینیِ
        # کلمه‌به‌کلمهٔ پرامپت پیدا شد.)
        if (path.startswith(self.COACH_ONLY_PREFIXES)
                and getattr(request.user, 'is_authenticated', False)
                and getattr(request.user, 'is_personal', False)):
            return redirect('/panel/me/')

        # ⚠ هدایتِ ورزشکار به ساب‌دامین فقط وقتی انجام می‌شود که مدیر در جنگو
        # ادمین تأیید کرده باشد که آن ساب‌دامین **بالا آمده است**. وگرنه کاربر
        # را به آدرسی می‌فرستادیم که هنوز در DNS نیست.
        if (not request.is_b2c and b2c_hosts
                and path in self.ATHLETE_PATHS
                and getattr(request.user, 'is_authenticated', False)
                and getattr(request.user, 'is_personal', False)
                and self._split_active()):
            # ⚠ به میزبانِ **پنلِ** ورزشکار برود (my)، نه میزبانِ لندینگ (app).
            # این دو عمداً جدا شدند: app هوم‌پیج است و my پنل. پیش از این هر دو
            # به app می‌رفت و مرزِ «هوم‌پیج/پنل» بی‌معنی می‌شد.
            target = getattr(request, 'b2c_panel_host', '') or request.b2c_host
            return redirect('https://%s%s' % (target, path))

        return self.get_response(request)

    @staticmethod
    def _split_active():
        """کلیدِ «جداییِ کاملِ B2C» از تنظیماتِ سامانه. خطا = خاموش."""
        try:
            from .models import PlatformSettings
            return PlatformSettings.get_solo().b2c_split_active
        except Exception:
            # اگر دیتابیس در دسترس نبود، هدایت نکن — سایت نباید بشکند
            return False

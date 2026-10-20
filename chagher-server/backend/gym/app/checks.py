# -*- coding: utf-8 -*-
"""بررسی‌های زمان راه‌اندازی (Django system checks).

هدف: مشکلاتی که در توسعه بی‌صدا می‌مانند اما روی سرور خروجی خراب می‌دهند،
هنگام `manage.py check` یا `runserver` سر و صدا کنند — نه وقتی مشتری یک PDF
ناخوانا دستش گرفته است.
"""
import os

from django.conf import settings
from django.core.checks import Error, Warning as CheckWarning, register


@register('gym')
def check_pdf_font(app_configs, **kwargs):
    """اگر PDF قرار است با ReportLab ساخته شود، فونت فارسی باید موجود باشد.

    WeasyPrint فونت‌ها را از fontconfig سیستم می‌گیرد و مشکلی ندارد؛ اما اگر
    نصب نباشد، مسیر ReportLab فعال می‌شود و ReportLab بدون یک TTF فارسی،
    حروف را به شکل مربع یا به‌هم‌ریخته چاپ می‌کند.
    """
    from pdf_generator.pdf_gen import WEASYPRINT_AVAILABLE, find_persian_font

    if WEASYPRINT_AVAILABLE:
        return []

    if find_persian_font():
        return []

    return [
        CheckWarning(
            'PDF فارسی بدون فونت مناسب تولید می‌شود.',
            hint=(
                'WeasyPrint در دسترس نیست و هیچ فونت فارسی هم پیدا نشد، پس PDF '
                'با ReportLab و حروف ناخوانا ساخته می‌شود. یکی از این دو کار را '
                'انجام دهید:\n'
                '  ۱) WeasyPrint و وابستگی‌های سیستمی‌اش را نصب کنید، یا\n'
                '  ۲) یک فونت فارسی نصب کنید و مسیرش را در متغیر محیطی '
                'GYM_PDF_FONT_PATH بگذارید. مثال روی اوبونتو:\n'
                '     apt-get install fonts-vazirmatn\n'
                '     export GYM_PDF_FONT_PATH=/usr/share/fonts/truetype/'
                'vazirmatn/Vazirmatn-Regular.ttf'
            ),
            id='gym.W001',
        )
    ]


@register('gym', deploy=True)
def check_private_media_not_public(app_configs, **kwargs):
    """فضای فایل‌های خصوصی نباید زیر MEDIA_ROOT عمومی باشد.

    رسیدهای پرداخت اینجا ذخیره می‌شوند؛ اگر این پوشه داخل MEDIA_ROOT بیفتد،
    وب‌سرور مستقیم سروش می‌کند و رسید بانکی کاربران با حدس آدرس قابل دیدن
    می‌شود.
    """
    private_root = os.path.abspath(getattr(settings, 'PRIVATE_MEDIA_ROOT', ''))
    media_root = os.path.abspath(getattr(settings, 'MEDIA_ROOT', ''))

    if not private_root:
        return [
            Error(
                'PRIVATE_MEDIA_ROOT تنظیم نشده است.',
                hint='رسیدهای پرداخت جایی برای ذخیره امن ندارند.',
                id='gym.E001',
            )
        ]

    if media_root and (
        private_root == media_root
        or private_root.startswith(media_root + os.sep)
    ):
        return [
            Error(
                'PRIVATE_MEDIA_ROOT داخل MEDIA_ROOT عمومی قرار دارد.',
                hint=(
                    'رسیدهای پرداخت از طریق MEDIA_URL برای همه قابل دانلود '
                    'می‌شوند. PRIVATE_MEDIA_ROOT را به مسیری بیرون از '
                    'MEDIA_ROOT ببرید و مطمئن شوید وب‌سرور آن را سرو نمی‌کند.'
                ),
                id='gym.E002',
            )
        ]

    return []


@register('gym', deploy=True)
def check_mock_gateway_off(app_configs, **kwargs):
    """درگاه تستی روی production یعنی توکن رایگان."""
    if getattr(settings, 'ALLOW_MOCK_PAYMENT_GATEWAY', False) and not settings.DEBUG:
        return [
            CheckWarning(
                'درگاه پرداخت تستی روی محیط production فعال است.',
                hint=(
                    'با ALLOW_MOCK_PAYMENT_GATEWAY فعال، هر کاربری می‌تواند بدون '
                    'پرداخت واقعی توکن بگیرد. متغیر DJANGO_ALLOW_MOCK_GATEWAY '
                    'را حذف کنید.'
                ),
                id='gym.W002',
            )
        ]
    return []

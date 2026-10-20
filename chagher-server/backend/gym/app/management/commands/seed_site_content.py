# -*- coding: utf-8 -*-
"""پرکردن محتوای صفحات معرفی سایت با متن واقعی و حرفه‌ای.

استفاده:
    python manage.py seed_site_content            # فقط رکوردهای تستی/خالی را اصلاح می‌کند
    python manage.py seed_site_content --force    # همه محتوا را با نسخه پیش‌فرض بازنویسی می‌کند
"""
import re

from app.management.utf8_command import Utf8Command
from django.db import transaction

from app.models import Feature, HomePage, TeamMember

HOMEPAGE = {
    'title': 'چغر، ابزار هوش مصنوعی برای مربی‌ها',
    'subtitle': 'دستیار شما در نوشتن برنامه تمرینی و غذایی اختصاصی هر ورزشکار، تنها در چند ثانیه',
    'description': (
        'چغر جای مربی را نمی‌گیرد؛ کار او را سریع‌تر و دقیق‌تر می‌کند. '
        'اطلاعات ورزشکار را وارد کنید، تجهیزات مجموعه و غذاهای مورد نظرتان را یک بار تعریف کنید، '
        'و دستورالعمل شخصی خودتان را به سیستم بدهید تا هوش مصنوعی بر اساس شرایط جسمانی، '
        'آسیب‌ها و اهداف هر فرد، پیش‌نویسی دقیق و قابل اجرا بسازد. '
        'نتیجه را بازبینی کنید و به شکل فایل PDF تحویل ورزشکار بدهید.'
    ),
}

FEATURES = [
    {
        'title': 'تولید برنامه با هوش مصنوعی',
        'description': (
            'برنامه تمرینی و غذایی بر اساس سن، قد، وزن، سابقه ورزشی، آسیب‌ها و بیماری‌های '
            'هر ورزشکار ساخته می‌شود. می‌توانید فقط برنامه تمرینی، فقط برنامه غذایی یا هر دو را سفارش دهید.'
        ),
        'icon': 'robot',
        'order': 1,
    },
    {
        'title': 'تمرین بر اساس تجهیزات مجموعه شما',
        'description': (
            'دستگاه‌های موجود در مجموعه خود را یک بار ثبت کنید تا تمام حرکات پیشنهادی '
            'فقط با همان تجهیزات طراحی شوند؛ بدون حرکتی که امکان اجرایش را ندارید.'
        ),
        'icon': 'dumbbell',
        'order': 2,
    },
    {
        'title': 'تغذیه متناسب با ذائقه ایرانی',
        'description': (
            'برنامه غذایی با غذاهای آشنای ایرانی و خاورمیانه‌ای طراحی می‌شود؛ '
            'همراه با کالری و درشت‌مغذی هر وعده و گزینه‌های جایگزین برای حساسیت‌های غذایی.'
        ),
        'icon': 'utensils',
        'order': 3,
    },
    {
        'title': 'دستورالعمل شخصی مربی',
        'description': (
            'قواعد ثابت خودتان را یک بار بنویسید تا در تولید هر برنامه رعایت شود؛ '
            'مثل «روز اول هفته سبک باشد» یا «برای بانوان از پرس سرشانه بالای سر استفاده نشود». '
            'سبک مربیگری شما در خروجی حفظ می‌شود، نه سلیقه‌ی مدل.'
        ),
        'icon': 'clipboard-list',
        'order': 4,
    },
    {
        'title': 'ویرایش برنامه با بازخورد',
        'description': (
            'اگر ورزشکار بازخوردی داشت، کافی است آن را بنویسید؛ برنامه بدون ساخت دوباره از صفر '
            'و با حفظ ساختار قبلی اصلاح می‌شود.'
        ),
        'icon': 'wand-magic-sparkles',
        'order': 5,
    },
]

TEAM = [
    {
        'name': 'تیم فنی',
        'role': 'توسعه و نگهداری محصول',
        'bio': (
            'توسعه و نگهداری سامانه، یکپارچه‌سازی هوش مصنوعی و درگاه‌های پرداخت، '
            'و پایداری سرویس برای مربیان عضو.'
        ),
        'icon': 'code-slash',
        'order': 1,
    },
    {
        'name': 'تیم مربیگری',
        'role': 'طراحی تمرین و تغذیه',
        'bio': (
            'بیش از ۵ مربی خبره و متخصص، نظارت کامل بر مراحل طراحی این ابزار و '
            'خروجی آن داشته‌اند تا برنامه‌های تولیدشده اصولی، ایمن و قابل اجرا باشند.'
        ),
        'icon': 'clipboard-pulse',
        'order': 2,
    },
    {
        'name': 'تیم پشتیبانی',
        'role': 'همراهی مربیان',
        'bio': (
            'پاسخ به سوال‌های مربیان، راه‌اندازی اولیه حساب و پیگیری درخواست‌ها '
            'تا کار مربی هیچ‌جا زمین نماند.'
        ),
        'icon': 'headset',
        'order': 3,
    },
]


def looks_like_placeholder(text, min_length=15):
    """تشخیص متن‌های تستی: تکرار یک حرف، Lorem ipsum، یا متن خیلی کوتاه.

    min_length برای فیلدهای کوتاه (مثل نام) پایین‌تر گذاشته می‌شود.
    """
    if not text:
        return True

    value = text.strip()
    if len(value) < min_length:
        return True
    if 'lorem ipsum' in value.lower():
        return True

    # متنی که از تکرار چند کاراکتر ساخته شده (مثل «صصصصص» یا «قیقیقیقی»)
    letters = re.sub(r'[\s\W\d_]+', '', value)
    if letters and len(set(letters)) <= 3:
        return True

    return False


class Command(Utf8Command):
    help = 'پرکردن محتوای صفحات معرفی سایت (صفحه اصلی، امکانات، تیم) با متن واقعی'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='بازنویسی محتوا حتی اگر متن واقعی (غیرتستی) باشد',
        )
        parser.add_argument(
            '--clear-images',
            action='store_true',
            help='حذف ارجاع تصاویر آپلودشده تا آیکون‌های پیش‌فرض نمایش داده شوند (فایل‌ها روی دیسک باقی می‌مانند)',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        force = options['force']

        self._seed_homepage(force)
        self._seed_features(force)
        self._seed_team(force)

        if options['clear_images']:
            self._clear_images()

        self.stdout.write(self.style.SUCCESS('\n✓ محتوای سایت آماده است.'))

    # ------------------------------------------------------------------
    def _seed_homepage(self, force):
        homepage = HomePage.objects.filter(is_active=True).first() or HomePage.objects.first()

        if homepage is None:
            homepage = HomePage(**HOMEPAGE, is_active=True)
            homepage.save()
            self.stdout.write(self.style.SUCCESS('صفحه اصلی ساخته شد.'))
        else:
            changed = []
            for field, value in HOMEPAGE.items():
                if force or looks_like_placeholder(getattr(homepage, field)):
                    setattr(homepage, field, value)
                    changed.append(field)

            homepage.is_active = True
            homepage.save()

            if changed:
                self.stdout.write(self.style.SUCCESS(
                    f'صفحه اصلی به‌روزرسانی شد ({"، ".join(changed)}).'
                ))
            else:
                self.stdout.write('صفحه اصلی محتوای واقعی دارد — دست‌نخورده ماند.')

        # اطمینان از اینکه فقط یک صفحه اصلی فعال است
        deactivated = HomePage.objects.filter(is_active=True).exclude(pk=homepage.pk).update(is_active=False)
        if deactivated:
            self.stdout.write(self.style.WARNING(
                f'{deactivated} صفحه اصلی تکراری غیرفعال شد (فقط یکی می‌تواند فعال باشد).'
            ))

    # ------------------------------------------------------------------
    def _seed_features(self, force):
        existing = list(Feature.objects.order_by('order', 'id'))
        placeholders = [f for f in existing if force or looks_like_placeholder(f.description)]

        created = updated = 0
        for index, data in enumerate(FEATURES):
            if placeholders:
                feature = placeholders.pop(0)
                for field, value in data.items():
                    setattr(feature, field, value)
                feature.is_active = True
                feature.save()
                updated += 1
            elif not Feature.objects.filter(title=data['title']).exists():
                Feature.objects.create(is_active=True, **data)
                created += 1

        # ردیف‌های اضافی که چیزی برای نوشتن در آن‌ها نمانده، غیرفعال می‌شوند.
        #
        # بدون این، وقتی فهرست پیش‌فرض کوتاه‌تر از چیزی می‌شد که در دیتابیس
        # هست، امکاناتِ حذف‌شده روی سایت باقی می‌ماندند یا یک ردیف تکراری
        # از آخرین مورد به جا می‌ماند. حذف نمی‌کنیم چون ممکن است مدیر خودش
        # آن‌ها را ساخته باشد؛ فقط از نمایش خارج می‌شوند.
        deactivated = 0
        for leftover in placeholders:
            if leftover.is_active:
                leftover.is_active = False
                leftover.save(update_fields=['is_active'])
                deactivated += 1

        if updated:
            self.stdout.write(self.style.SUCCESS(f'{updated} امکانات با محتوای واقعی جایگزین شد.'))
        if created:
            self.stdout.write(self.style.SUCCESS(f'{created} امکانات جدید اضافه شد.'))
        if deactivated:
            self.stdout.write(self.style.WARNING(
                f'{deactivated} امکانات اضافی غیرفعال شد (در سایت نمایش داده نمی‌شوند).'
            ))
        if not updated and not created:
            self.stdout.write('امکانات محتوای واقعی دارند — دست‌نخورده ماندند.')

    # ------------------------------------------------------------------
    def _seed_team(self, force):
        existing = list(TeamMember.objects.order_by('order', 'id'))
        # نام‌ها کوتاه‌اند، پس آستانه طول برایشان پایین‌تر است
        placeholders = [
            m for m in existing
            if force or looks_like_placeholder(m.bio) or looks_like_placeholder(m.name, min_length=3)
        ]

        created = updated = 0
        for data in TEAM:
            if placeholders:
                member = placeholders.pop(0)
                for field, value in data.items():
                    setattr(member, field, value)
                member.save()
                updated += 1
            elif not TeamMember.objects.filter(name=data['name']).exists():
                TeamMember.objects.create(**data)
                created += 1

        if updated:
            self.stdout.write(self.style.SUCCESS(f'{updated} عضو تیم با اطلاعات واقعی جایگزین شد.'))
        if created:
            self.stdout.write(self.style.SUCCESS(f'{created} عضو تیم اضافه شد.'))
        if not updated and not created:
            self.stdout.write('اعضای تیم اطلاعات واقعی دارند — دست‌نخورده ماندند.')

    # ------------------------------------------------------------------
    def _clear_images(self):
        """حذف ارجاع تصاویر تستی (فایل روی دیسک پاک نمی‌شود)."""
        features = Feature.objects.exclude(image='').exclude(image__isnull=True)
        feature_count = features.count()
        for feature in features:
            feature.image = None
            feature.save(update_fields=['image'])

        members = TeamMember.objects.exclude(photo='').exclude(photo__isnull=True)
        member_count = members.count()
        for member in members:
            member.photo = None
            member.save(update_fields=['photo'])

        homepages = HomePage.objects.exclude(hero_image='').exclude(hero_image__isnull=True)
        home_count = homepages.count()
        for homepage in homepages:
            homepage.hero_image = None
            homepage.save(update_fields=['hero_image'])

        self.stdout.write(self.style.SUCCESS(
            f'تصاویر پاک شد — امکانات: {feature_count}، تیم: {member_count}، صفحه اصلی: {home_count}'
        ))

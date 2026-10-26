# -*- coding: utf-8 -*-
"""رزومه و نمونه‌کارِ اعضای تیم (۱۴۰۵/۰۸/۰۴).

خودِ عضو همان `app.TeamMember` است (نام، عکس، نقش، تماس، انتشار)؛ این‌جا فقط
ردیف‌های تکرارشونده می‌آیند: سابقه، تحصیل، مدرک، مهارت، زبان، افتخار، شبکهٔ
اجتماعی — و پروژه‌ها که می‌توانند چند عضو داشته باشند.

تاریخ‌ها شمسی و «سال/ماه» ذخیره می‌شوند (نه DateField): رزومه روزِ دقیق
نمی‌خواهد و مالک با تقویمِ شمسی فکر می‌کند.
"""
import re

from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from .jalali import format_range, format_ym

MONTHS = [(1, 'فروردین'), (2, 'اردیبهشت'), (3, 'خرداد'), (4, 'تیر'), (5, 'مرداد'),
          (6, 'شهریور'), (7, 'مهر'), (8, 'آبان'), (9, 'آذر'), (10, 'دی'),
          (11, 'بهمن'), (12, 'اسفند')]

YEAR_HELP = 'سالِ شمسی، مثل 1402'
_year = dict(null=True, blank=True,
             validators=[MinValueValidator(1300), MaxValueValidator(1500)])


def _unique_slug(model, text, pk, field='slug', fallback='item'):
    base = slugify(text or '', allow_unicode=True)[:70] or fallback
    slug, n = base, 2
    while model.objects.filter(**{field: slug}).exclude(pk=pk).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


class MemberItem(models.Model):
    """پایهٔ ردیف‌های رزومه: ترتیب + کلیدِ «منتشر شود»."""
    member = models.ForeignKey('app.TeamMember', on_delete=models.CASCADE,
                               related_name='%(class)s_set', verbose_name='عضو')
    order = models.PositiveSmallIntegerField('ترتیب', default=0)
    is_published = models.BooleanField('منتشر شود', default=True)

    class Meta:
        abstract = True


# ─────────────────────────── شبکه‌های اجتماعی ───────────────────────────
class SocialLink(MemberItem):
    KINDS = [
        ('linkedin', 'لینکدین'), ('instagram', 'اینستاگرام'), ('telegram', 'تلگرام'),
        ('github', 'گیت‌هاب'), ('gitlab', 'گیت‌لب'), ('website', 'وب‌سایت'),
        ('x', 'ایکس (توییتر)'), ('youtube', 'یوتیوب'), ('aparat', 'آپارات'),
        ('behance', 'بیهنس'), ('dribbble', 'دریبل'), ('whatsapp', 'واتس‌اپ'),
        ('other', 'سایر'),
    ]
    ICONS = {'linkedin': 'linkedin', 'instagram': 'instagram', 'telegram': 'telegram',
             'github': 'github', 'gitlab': 'gitlab', 'website': 'globe2', 'x': 'twitter-x',
             'youtube': 'youtube', 'aparat': 'play-btn', 'behance': 'behance',
             'dribbble': 'dribbble', 'whatsapp': 'whatsapp', 'other': 'link-45deg'}
    HANDLE_BASE = {'telegram': 'https://t.me/', 'instagram': 'https://instagram.com/',
                   'github': 'https://github.com/', 'x': 'https://x.com/'}

    kind = models.CharField('نوع', max_length=20, choices=KINDS, default='website')
    url = models.CharField('نشانی', max_length=300,
                           help_text='نشانیِ کامل (https://…) یا برای تلگرام/اینستاگرام/گیت‌هاب فقط @نامِ‌کاربری')
    label = models.CharField('برچسب (اختیاری)', max_length=60, blank=True)

    class Meta:
        verbose_name = 'شبکهٔ اجتماعی'
        verbose_name_plural = 'شبکه‌های اجتماعی'
        ordering = ['order', 'id']

    def save(self, *args, **kwargs):
        self.url = self.normalized_url(self.kind, self.url)
        super().save(*args, **kwargs)

    @classmethod
    def normalized_url(cls, kind, url):
        url = (url or '').strip()
        if url.startswith('@') and kind in cls.HANDLE_BASE:
            return cls.HANDLE_BASE[kind] + url[1:]
        if url and not re.match(r'^(https?://|mailto:|tel:)', url, re.I):
            return 'https://' + url.lstrip('/')
        return url

    @property
    def icon(self):
        return self.ICONS.get(self.kind, 'link-45deg')

    @property
    def title(self):
        return self.label or self.get_kind_display()

    def __str__(self):
        return f'{self.get_kind_display()}: {self.url}'


# ─────────────────────────── سوابقِ کاری ───────────────────────────
class Experience(MemberItem):
    TYPES = [('full', 'تمام‌وقت'), ('part', 'پاره‌وقت'), ('contract', 'قراردادی / پروژه‌ای'),
             ('freelance', 'آزادکار'), ('intern', 'کارآموزی'), ('volunteer', 'داوطلبانه')]

    role = models.CharField('سِمَت', max_length=150)
    organisation = models.CharField('شرکت / سازمان', max_length=150)
    city = models.CharField('شهر', max_length=80, blank=True)
    employment_type = models.CharField('نوعِ همکاری', max_length=12, choices=TYPES, blank=True)
    start_year = models.PositiveSmallIntegerField('سالِ شروع', help_text=YEAR_HELP, **_year)
    start_month = models.PositiveSmallIntegerField('ماهِ شروع', choices=MONTHS, null=True, blank=True)
    end_year = models.PositiveSmallIntegerField('سالِ پایان', help_text='خالی + «تا کنون» برای کارِ فعلی', **_year)
    end_month = models.PositiveSmallIntegerField('ماهِ پایان', choices=MONTHS, null=True, blank=True)
    is_current = models.BooleanField('تا کنون', default=False)
    description = models.TextField('شرحِ کار و دستاوردها', blank=True,
                                   help_text='هر خط یک بند (بولت) می‌شود.')

    class Meta:
        verbose_name = 'سابقهٔ کاری'
        verbose_name_plural = 'سوابقِ کاری'
        ordering = ['order', '-is_current', '-start_year', '-start_month', 'id']

    @property
    def period(self):
        return format_range(self.start_year, self.start_month, self.end_year, self.end_month,
                            self.is_current)

    @property
    def bullets(self):
        return _bullets(self.description)

    def __str__(self):
        return f'{self.role} — {self.organisation}'


def _bullets(text):
    out = []
    for line in (text or '').splitlines():
        line = re.sub(r'^\s*[-•*–▪●]\s*', '', line).strip()
        if line:
            out.append(line)
    return out


# ─────────────────────────── تحصیلات ───────────────────────────
class Education(MemberItem):
    degree = models.CharField('مقطع', max_length=80, help_text='مثل کارشناسی، کارشناسی ارشد، دیپلم')
    field = models.CharField('رشته', max_length=150, blank=True)
    institution = models.CharField('دانشگاه / مؤسسه', max_length=150)
    city = models.CharField('شهر', max_length=80, blank=True)
    start_year = models.PositiveSmallIntegerField('سالِ شروع', help_text=YEAR_HELP, **_year)
    end_year = models.PositiveSmallIntegerField('سالِ پایان', **_year)
    is_current = models.BooleanField('در حالِ تحصیل', default=False)
    description = models.TextField('توضیح (اختیاری)', blank=True, help_text='معدل، پایان‌نامه، … — هر خط یک بند')

    class Meta:
        verbose_name = 'تحصیلات'
        verbose_name_plural = 'تحصیلات'
        ordering = ['order', '-is_current', '-end_year', '-start_year', 'id']

    @property
    def period(self):
        return format_range(self.start_year, None, self.end_year, None, self.is_current,
                            current_label='در حالِ تحصیل')

    @property
    def bullets(self):
        return _bullets(self.description)

    def __str__(self):
        return f'{self.degree} {self.field} — {self.institution}'


# ─────────────────────────── مدرک و دوره ───────────────────────────
class Certification(MemberItem):
    title = models.CharField('عنوانِ مدرک / دوره', max_length=200)
    issuer = models.CharField('صادرکننده', max_length=150, blank=True)
    year = models.PositiveSmallIntegerField('سال', help_text=YEAR_HELP, **_year)
    month = models.PositiveSmallIntegerField('ماه', choices=MONTHS, null=True, blank=True)
    credential_id = models.CharField('شمارهٔ گواهی', max_length=100, blank=True)
    url = models.URLField('لینکِ تأیید / دوره', blank=True)
    file = models.FileField('فایلِ مدرک', upload_to='team/certificates/', blank=True,
                            validators=[FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png', 'webp'])])

    class Meta:
        verbose_name = 'مدرک یا دوره'
        verbose_name_plural = 'مدارک و دوره‌ها'
        ordering = ['order', '-year', '-month', 'id']

    @property
    def date_label(self):
        return format_ym(self.year, self.month)

    @property
    def link(self):
        return self.url or (self.file.url if self.file else '')

    def __str__(self):
        return self.title


# ─────────────────────────── مهارت ───────────────────────────
class Skill(MemberItem):
    LEVELS = [(1, 'مقدماتی'), (2, 'متوسط'), (3, 'خوب'), (4, 'پیشرفته'), (5, 'متخصص')]

    name = models.CharField('مهارت', max_length=80)
    group = models.CharField('دسته', max_length=60, blank=True,
                             help_text='مهارت‌های هم‌دسته کنارِ هم می‌آیند، مثل «برنامه‌نویسی»، «طراحی»، «مربیگری»')
    level = models.PositiveSmallIntegerField('سطح', choices=LEVELS, default=3)

    class Meta:
        verbose_name = 'مهارت'
        verbose_name_plural = 'مهارت‌ها'
        ordering = ['order', 'id']

    @property
    def percent(self):
        return self.level * 20

    def __str__(self):
        return self.name


# ─────────────────────────── زبان ───────────────────────────
class LanguageSkill(MemberItem):
    LEVELS = [('native', 'زبانِ مادری'), ('c2', 'تسلطِ کامل (C2)'), ('c1', 'پیشرفته (C1)'),
              ('b2', 'بالاتر از متوسط (B2)'), ('b1', 'متوسط (B1)'), ('a2', 'مقدماتی (A2)'),
              ('a1', 'آشنایی (A1)')]
    PERCENT = {'native': 100, 'c2': 95, 'c1': 80, 'b2': 65, 'b1': 50, 'a2': 35, 'a1': 20}

    language = models.CharField('زبان', max_length=60)
    level = models.CharField('سطح', max_length=8, choices=LEVELS, default='b1')

    class Meta:
        verbose_name = 'زبان'
        verbose_name_plural = 'زبان‌ها'
        ordering = ['order', 'id']

    @property
    def percent(self):
        return self.PERCENT.get(self.level, 50)

    def __str__(self):
        return self.language


# ─────────────────────────── افتخار ───────────────────────────
class Award(MemberItem):
    title = models.CharField('عنوان', max_length=200)
    issuer = models.CharField('اهداکننده', max_length=150, blank=True)
    year = models.PositiveSmallIntegerField('سال', help_text=YEAR_HELP, **_year)
    description = models.TextField('توضیح', blank=True)
    url = models.URLField('لینک', blank=True)

    class Meta:
        verbose_name = 'افتخار / جایزه'
        verbose_name_plural = 'افتخارات و جوایز'
        ordering = ['order', '-year', 'id']

    def __str__(self):
        return self.title


# ─────────────────────────── نمونه‌کار ───────────────────────────
class PortfolioCategory(models.Model):
    name = models.CharField('نامِ دسته', max_length=80)
    slug = models.SlugField('نامک', max_length=80, unique=True, allow_unicode=True, blank=True)
    order = models.PositiveSmallIntegerField('ترتیب', default=0)

    class Meta:
        verbose_name = 'دستهٔ نمونه‌کار'
        verbose_name_plural = 'دسته‌های نمونه‌کار'
        ordering = ['order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(PortfolioCategory, self.name, self.pk, fallback='category')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PortfolioProject(models.Model):
    title = models.CharField('عنوانِ پروژه', max_length=200)
    slug = models.SlugField('نامک (آدرس)', max_length=90, unique=True, allow_unicode=True, blank=True,
                            help_text='آخرِ آدرس: chagher.ir/portfolio/<b>نامک</b>/ — خالی بماند از عنوان ساخته می‌شود.')
    category = models.ForeignKey(PortfolioCategory, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='projects', verbose_name='دسته')
    cover = models.ImageField('تصویرِ کاور', upload_to='portfolio/covers/', blank=True,
                              help_text='افقی بهتر است (مثلاً ۱۶۰۰×۱۰۰۰). نسخهٔ کوچک خودکار ساخته می‌شود.')
    short_description = models.CharField('خلاصهٔ کوتاه', max_length=300, blank=True,
                                         help_text='یک دو جمله؛ روی کارت و در نتیجهٔ گوگل می‌آید.')
    description = models.TextField('شرحِ کامل', blank=True,
                                   help_text='پاراگراف‌ها را با یک خطِ خالی جدا کنید.')
    client = models.CharField('کارفرما', max_length=150, blank=True)
    year = models.PositiveSmallIntegerField('سال', help_text=YEAR_HELP, **_year)
    month = models.PositiveSmallIntegerField('ماه', choices=MONTHS, null=True, blank=True)
    tags = models.CharField('برچسب‌ها', max_length=300, blank=True,
                            help_text='با ویرگول جدا کنید: پایتون، جنگو، هوش مصنوعی')
    external_url = models.URLField('لینکِ پروژه / دمو', blank=True)
    video_url = models.URLField('لینکِ ویدئو', blank=True,
                                help_text='آپارات یا یوتیوب — داخلِ صفحه پخش می‌شود. برای ویدئوی بزرگ‌تر از ۲۵ مگ همین را بگذارید.')
    video_file = models.FileField('فایلِ ویدئو', upload_to='portfolio/videos/', blank=True,
                                  validators=[FileExtensionValidator(['mp4', 'webm'])],
                                  help_text='mp4 یا webm، حداکثر ۲۵ مگابایت.')
    members = models.ManyToManyField('app.TeamMember', through='ProjectMember', blank=True,
                                     related_name='portfolio_projects', verbose_name='اعضا')
    is_featured = models.BooleanField('ویژه', default=False,
                                      help_text='پروژه‌های ویژه اول می‌آیند و در رزومهٔ اعضا نشان داده می‌شوند.')
    order = models.PositiveSmallIntegerField('ترتیب', default=0)
    is_published = models.BooleanField('منتشر شود', default=True)
    created_at = models.DateTimeField('ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین تغییر', auto_now=True)

    class Meta:
        verbose_name = 'نمونه‌کار (پروژه)'
        verbose_name_plural = 'نمونه‌کارها (پروژه‌ها)'
        ordering = ['-is_featured', 'order', '-year', '-month', '-id']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(PortfolioProject, self.title, self.pk, fallback='project')
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('portfolio-detail', kwargs={'slug': self.slug})

    @property
    def tag_list(self):
        return [t.strip() for t in re.split(r'[,،;\n]', self.tags or '') if t.strip()]

    @property
    def date_label(self):
        return format_ym(self.year, self.month)

    @property
    def paragraphs(self):
        return [p.strip() for p in re.split(r'\n\s*\n', self.description or '') if p.strip()]

    @property
    def video_embed(self):
        """نشانیِ iframe برای یوتیوب/آپارات؛ برای بقیه خالی (فقط لینک)."""
        url = self.video_url or ''
        m = re.search(r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{6,})', url)
        if m:
            return 'https://www.youtube-nocookie.com/embed/' + m.group(1)
        m = re.search(r'aparat\.com/(?:v/|video/video/embed/videohash/)([\w-]+)', url)
        if m:
            return 'https://www.aparat.com/video/video/embed/videohash/%s/vt/frame' % m.group(1)
        return ''

    def __str__(self):
        return self.title


class ProjectMember(models.Model):
    project = models.ForeignKey(PortfolioProject, on_delete=models.CASCADE, related_name='credits',
                                verbose_name='پروژه')
    member = models.ForeignKey('app.TeamMember', on_delete=models.CASCADE, related_name='project_credits',
                               verbose_name='عضو')
    role = models.CharField('نقشِ این عضو در پروژه', max_length=150, blank=True)
    order = models.PositiveSmallIntegerField('ترتیب', default=0)

    class Meta:
        verbose_name = 'عضوِ پروژه'
        verbose_name_plural = 'اعضای پروژه'
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['project', 'member'], name='portfolio_unique_credit')]

    def __str__(self):
        return f'{self.member.name} در {self.project.title}'


class ProjectImage(models.Model):
    project = models.ForeignKey(PortfolioProject, on_delete=models.CASCADE, related_name='images',
                                verbose_name='پروژه')
    image = models.ImageField('تصویر', upload_to='portfolio/gallery/')
    caption = models.CharField('توضیحِ تصویر', max_length=200, blank=True)
    order = models.PositiveSmallIntegerField('ترتیب', default=0)

    class Meta:
        verbose_name = 'تصویرِ گالری'
        verbose_name_plural = 'گالریِ تصاویر'
        ordering = ['order', 'id']

    def __str__(self):
        return self.caption or f'تصویر {self.pk}'

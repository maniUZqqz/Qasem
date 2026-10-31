# -*- coding: utf-8 -*-
"""مدل‌های استودیو — «تعریفِ ساختاریافته»ای که موتورِ تولید از رویش کد می‌سازد.

⚠ اصلِ معماری (از idea.md §۵.۳): متادیتا و سورس باید با هم هماهنگ بمانند.
   این جدول‌ها «حقیقت» را نگه می‌دارند و `code_generation` از رویشان فایلِ
   واقعیِ جنگو می‌نویسد. هیچ‌وقت عکسش نه — جز در پروژهٔ **واردشده** که
   تحلیل‌گر یک بار از روی سورس، این جدول‌ها را پر می‌کند (idea.md §۸).

دو نوع پروژه:
  · `studio`   — استودیو ساخته؛ همهٔ فایل‌ها را خودش می‌نویسد.
  · `imported` — کاربر آپلود کرده؛ فقط چیزهایی که «managed» هستند
                 (اپ‌های تازه، قالب‌های ویرایش‌شده) نوشته می‌شوند. بقیه فقط
                 نمایش داده می‌شوند (سطحِ ۲ از idea.md §۸).
"""
import re

from django.conf import settings
from django.db import models
from django.utils.text import slugify


def _snake(name):
    s = re.sub(r'[^0-9a-zA-Z]+', '_', (name or '').strip())
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
    return re.sub(r'_+', '_', s).strip('_') or 'item'


def _camel(name):
    return ''.join(w.capitalize() for w in _snake(name).split('_')) or 'Item'


def _lines(text):
    """متنِ چندخطی ⇒ فهرستِ خط‌های غیرخالی (برای فیلدهای «هر خط یکی»)."""
    return [x.strip() for x in (text or '').splitlines() if x.strip()]


def _csv(text):
    return [x.strip() for x in (text or '').replace('،', ',').split(',') if x.strip()]


class Project(models.Model):
    """یک پروژهٔ جنگو — ساختهٔ استودیو یا واردشده."""

    STATUS_DRAFT = 'draft'
    STATUS_GENERATED = 'generated'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'پیش‌نویس — هنوز کدی تولید نشده'),
        (STATUS_GENERATED, 'کد تولید شده'),
        (STATUS_ERROR, 'خطا در تولید'),
    ]
    SOURCE_STUDIO = 'studio'
    SOURCE_IMPORTED = 'imported'
    SOURCE_CHOICES = [(SOURCE_STUDIO, 'ساختهٔ استودیو'), (SOURCE_IMPORTED, 'واردشده')]

    name = models.CharField(max_length=120, verbose_name='نامِ پروژه')
    slug = models.SlugField(max_length=120, unique=True, blank=True,
                            verbose_name='شناسه (نامِ پوشه)')
    description = models.TextField(blank=True, verbose_name='توضیحِ فروشگاه',
                                   help_text='چه می‌فروشد، لحنِ سایت، رنگِ غالب…')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT, verbose_name='وضعیت')
    last_error = models.TextField(blank=True, verbose_name='آخرین خطا')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES,
                              default=SOURCE_STUDIO, verbose_name='منشأ')

    # ظاهرِ پایه که در قالبِ تولیدی می‌نشیند
    brand_color = models.CharField(max_length=9, default='#126F85',
                                   verbose_name='رنگِ برند')
    site_title = models.CharField(max_length=120, blank=True,
                                  verbose_name='عنوانِ سایت')

    # ── تنظیماتِ گرافیکیِ config/settings.py (idea.md: «ستینگ را گرافیکی تنظیم کنی») ──
    language_code = models.CharField(max_length=10, default='fa', verbose_name='زبان')
    time_zone = models.CharField(max_length=40, default='Asia/Tehran', verbose_name='منطقهٔ زمانی')
    allowed_hosts = models.CharField(max_length=300, default='*', verbose_name='ALLOWED_HOSTS',
                                     help_text='با کاما جدا کن؛ * یعنی همه')
    extra_apps = models.TextField(blank=True, verbose_name='اپ‌های بیرونی (INSTALLED_APPS)',
                                  help_text='هر خط یکی، مثلاً rest_framework')
    extra_requirements = models.TextField(blank=True, verbose_name='بسته‌های بیرونی (requirements)',
                                          help_text='هر خط یکی، مثلاً djangorestframework>=3.15')
    custom_settings = models.TextField(blank=True, verbose_name='تنظیماتِ دستی',
                                       help_text='عیناً به انتهای settings.py اضافه می‌شود')

    # ── پروژهٔ واردشده ──
    settings_module = models.CharField(max_length=120, blank=True, verbose_name='ماژولِ تنظیمات',
                                       help_text='مثلاً project.settings — خالی = config.settings')
    urls_module = models.CharField(max_length=120, blank=True, verbose_name='ماژولِ نشانی‌ها')
    apps_dir = models.CharField(max_length=60, blank=True, verbose_name='پوشهٔ اپ‌ها',
                                help_text='خالی = ریشهٔ پروژه؛ در پروژهٔ استودیو همیشه apps')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generated_at = models.DateTimeField(null=True, blank=True,
                                        verbose_name='آخرین تولید')

    class Meta:
        verbose_name = 'پروژه'
        verbose_name_plural = 'پروژه‌ها'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=False) or 'project'
            s, i = base, 2
            while Project.objects.filter(slug=s).exclude(pk=self.pk).exists():
                s = '%s-%d' % (base, i)
                i += 1
            self.slug = s
        if not self.site_title:
            self.site_title = self.name
        super().save(*args, **kwargs)

    @property
    def path(self):
        """پوشهٔ این پروژه روی دیسک."""
        return settings.WORKSPACES_ROOT / self.slug

    @property
    def exists_on_disk(self):
        return (self.path / 'manage.py').exists()

    @property
    def is_imported(self):
        return self.source == self.SOURCE_IMPORTED

    @property
    def settings_module_name(self):
        return self.settings_module or 'config.settings'

    @property
    def apps_dir_name(self):
        return 'apps' if not self.is_imported else self.apps_dir

    @property
    def extra_app_list(self):
        return _lines(self.extra_apps)

    @property
    def extra_requirement_list(self):
        return _lines(self.extra_requirements)

    @property
    def allowed_host_list(self):
        return _csv(self.allowed_hosts) or ['*']


class App(models.Model):
    """یک اپِ جنگو داخلِ پروژه."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='apps', verbose_name='پروژه')
    name = models.CharField(max_length=60, verbose_name='نامِ اپ',
                            help_text='انگلیسی، مثلاً catalog یا orders')
    verbose_name_fa = models.CharField(max_length=80, blank=True,
                                       verbose_name='نامِ فارسی')
    description = models.TextField(blank=True, verbose_name='مسئولیتِ اپ')
    is_core = models.BooleanField(default=False, verbose_name='اپِ پایهٔ فروشگاه',
                                  help_text='اپ‌هایی که قالبِ استاندارد ساخته است.')
    managed = models.BooleanField(default=True, verbose_name='استودیو فایل‌هایش را می‌نویسد',
                                  help_text='اپ‌های واردشده خاموش‌اند: فقط نمایش داده می‌شوند.')
    path = models.CharField(max_length=120, blank=True, verbose_name='پوشه (نسبی)',
                            help_text='خالی = apps/<name>؛ در پروژهٔ واردشده همان جایی که بود')
    url_prefix = models.CharField(max_length=80, blank=True, verbose_name='پیشوندِ نشانی',
                                  help_text='مثلاً blog/ — نشانی‌های این اپ زیرِ آن می‌نشینند')
    order = models.PositiveIntegerField(default=100, verbose_name='ترتیب')

    class Meta:
        verbose_name = 'اپ'
        verbose_name_plural = 'اپ‌ها'
        ordering = ['order', 'id']
        unique_together = [('project', 'name')]

    def __str__(self):
        return '%s / %s' % (self.project.slug, self.name)

    def save(self, *args, **kwargs):
        if self.managed:
            self.name = _snake(self.name)
        if self.url_prefix:
            self.url_prefix = self.url_prefix.strip().strip('/')
            self.url_prefix = self.url_prefix + '/' if self.url_prefix else ''
        super().save(*args, **kwargs)

    @property
    def dir(self):
        """پوشهٔ اپ نسبت به ریشهٔ پروژه."""
        if self.path:
            return self.path.strip('/')
        d = self.project.apps_dir_name
        return '%s/%s' % (d, self.name) if d else self.name

    @property
    def package(self):
        """نامِ نقطه‌دارِ پایتونی، برای INSTALLED_APPS و include."""
        return self.dir.replace('/', '.')

    @property
    def class_prefix(self):
        return ''.join(w.capitalize() for w in re.split(r'[_\W]+', self.name) if w) or 'App'

    @property
    def effective_prefix(self):
        """پیشوندی که واقعاً در config/urls.py می‌نشیند — خالی هیچ‌وقت ریشه را نمی‌پوشاند."""
        if self.url_prefix:
            return self.url_prefix
        return (self.name + '/') if self.managed else ''

    @property
    def has_urls(self):
        return self.routes.exists() or self.views.exists()


class Model(models.Model):
    """یک مدلِ جنگو داخلِ یک اپ."""
    app = models.ForeignKey(App, on_delete=models.CASCADE,
                            related_name='models', verbose_name='اپ')
    name = models.CharField(max_length=60, verbose_name='نامِ مدل',
                            help_text='مثلاً Product — خودش CamelCase می‌شود')
    verbose_name_fa = models.CharField(max_length=80, blank=True,
                                       verbose_name='نامِ فارسی')
    verbose_plural_fa = models.CharField(max_length=80, blank=True,
                                         verbose_name='نامِ فارسیِ جمع')
    has_str = models.BooleanField(default=True, verbose_name='__str__ بسازد')
    str_field = models.CharField(max_length=60, blank=True, verbose_name='فیلدِ __str__',
                                 help_text='خالی = اولین فیلدِ متنی')
    ordering = models.CharField(max_length=120, blank=True, verbose_name='ترتیبِ پیش‌فرض',
                                help_text='مثلاً -created_at یا name')
    in_admin = models.BooleanField(default=True, verbose_name='در ادمین ثبت شود')
    admin_list_display = models.CharField(max_length=200, blank=True, verbose_name='ستون‌های فهرستِ ادمین',
                                          help_text='با کاما؛ خالی = خودکار')
    admin_search_fields = models.CharField(max_length=200, blank=True, verbose_name='فیلدهای جست‌وجو')
    admin_list_filter = models.CharField(max_length=200, blank=True, verbose_name='فیلترهای ادمین')
    managed = models.BooleanField(default=True, verbose_name='استودیو کدش را می‌نویسد')
    raw_code = models.TextField(blank=True, verbose_name='کدِ اصلی (واردشده)',
                                help_text='برای مدل‌های واردشده: متنِ کلاس همان‌طور که در فایل بود')
    order = models.PositiveIntegerField(default=100, verbose_name='ترتیب')

    class Meta:
        verbose_name = 'مدل'
        verbose_name_plural = 'مدل‌ها'
        ordering = ['order', 'id']
        unique_together = [('app', 'name')]

    def __str__(self):
        return '%s.%s' % (self.app.name, self.name)

    def save(self, *args, **kwargs):
        self.name = _camel(self.name) if self.managed else self.name
        super().save(*args, **kwargs)

    @property
    def table_label(self):
        return self.verbose_name_fa or self.name

    @property
    def snake(self):
        return _snake(self.name)

    @property
    def ordering_list(self):
        return _csv(self.ordering)

    @property
    def editable_field_names(self):
        """فیلدهایی که در فرم‌های ساخت/ویرایش می‌آیند."""
        return [f.name for f in self.fields.all()
                if not f.auto_now and not f.auto_now_add and f.field_type != 'custom']


class Field(models.Model):
    """یک فیلدِ مدل — همان چیزی که کاربر گرافیکی می‌سازد."""

    TYPES = [
        ('CharField', 'متنِ کوتاه'),
        ('TextField', 'متنِ بلند'),
        ('IntegerField', 'عدد صحیح'),
        ('PositiveIntegerField', 'عدد صحیحِ مثبت'),
        ('BigIntegerField', 'عدد صحیحِ بزرگ'),
        ('FloatField', 'عدد اعشاری (float)'),
        ('DecimalField', 'عدد اعشاری (قیمت)'),
        ('BooleanField', 'بله/خیر'),
        ('DateField', 'تاریخ'),
        ('DateTimeField', 'تاریخ و ساعت'),
        ('TimeField', 'ساعت'),
        ('EmailField', 'ایمیل'),
        ('URLField', 'نشانیِ اینترنتی'),
        ('SlugField', 'اسلاگ'),
        ('UUIDField', 'شناسهٔ یکتا (UUID)'),
        ('JSONField', 'JSON'),
        ('ImageField', 'تصویر'),
        ('FileField', 'فایل'),
        ('ForeignKey', 'رابطه: چند-به-یک'),
        ('ManyToManyField', 'رابطه: چند-به-چند'),
        ('OneToOneField', 'رابطه: یک-به-یک'),
        ('custom', 'دستی / ناشناخته (کدِ خام)'),
    ]
    RELATIONAL = {'ForeignKey', 'ManyToManyField', 'OneToOneField'}
    TEXTUAL = {'CharField', 'TextField', 'SlugField', 'EmailField', 'URLField'}

    ON_DELETE = [
        ('CASCADE', 'با حذفِ والد، این هم حذف شود'),
        ('PROTECT', 'نگذارد والد حذف شود'),
        ('SET_NULL', 'خالی شود (باید «می‌تواند خالی باشد» باشد)'),
    ]

    model = models.ForeignKey(Model, on_delete=models.CASCADE,
                              related_name='fields', verbose_name='مدل')
    name = models.CharField(max_length=60, verbose_name='نامِ فیلد')
    verbose_name_fa = models.CharField(max_length=80, blank=True,
                                       verbose_name='برچسبِ فارسی')
    field_type = models.CharField(max_length=24, choices=TYPES,
                                  default='CharField', verbose_name='نوع')

    max_length = models.PositiveIntegerField(null=True, blank=True,
                                             verbose_name='حداکثر طول')
    max_digits = models.PositiveIntegerField(null=True, blank=True, verbose_name='تعدادِ رقم')
    decimal_places = models.PositiveIntegerField(null=True, blank=True, verbose_name='رقمِ اعشار')
    null = models.BooleanField(default=False, verbose_name='در دیتابیس NULL باشد')
    blank = models.BooleanField(default=False, verbose_name='در فرم می‌تواند خالی باشد')
    unique = models.BooleanField(default=False, verbose_name='یکتا')
    db_index = models.BooleanField(default=False, verbose_name='ایندکس')
    auto_now = models.BooleanField(default=False, verbose_name='هر ذخیره = الان (auto_now)')
    auto_now_add = models.BooleanField(default=False, verbose_name='زمانِ ساخت (auto_now_add)')
    default = models.CharField(max_length=120, blank=True, verbose_name='پیش‌فرض',
                               help_text='عیناً در کد می‌نشیند؛ متن را داخلِ کوتیشن بگذار')
    choices = models.TextField(blank=True, verbose_name='گزینه‌ها',
                               help_text='هر خط «مقدار=برچسب»، مثلاً new=تازه')
    help_text_fa = models.CharField(max_length=160, blank=True, verbose_name='راهنما')

    related_model = models.ForeignKey(
        Model, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='incoming_relations', verbose_name='به کدام مدل',
        help_text='فقط برای فیلدهای رابطه‌ای')
    related_ref = models.CharField(max_length=120, blank=True, verbose_name='مقصدِ متنی',
                                   help_text='وقتی مقصد مدلِ خودِ پروژه نیست، مثلاً auth.User یا settings.AUTH_USER_MODEL')
    on_delete = models.CharField(max_length=12, choices=ON_DELETE, default='CASCADE',
                                 verbose_name='رفتارِ حذف')
    related_name = models.CharField(max_length=60, blank=True,
                                    verbose_name='نامِ برگشتی')
    raw_code = models.CharField(max_length=400, blank=True, verbose_name='کدِ خام',
                                help_text='برای نوعِ «دستی»: دقیقاً همان چیزی که بعد از = می‌آید')

    order = models.PositiveIntegerField(default=100, verbose_name='ترتیب')

    class Meta:
        verbose_name = 'فیلد'
        verbose_name_plural = 'فیلدها'
        ordering = ['order', 'id']
        unique_together = [('model', 'name')]

    def __str__(self):
        return '%s.%s' % (self.model.name, self.name)

    def save(self, *args, **kwargs):
        if self.model.managed:
            self.name = _snake(self.name)
        if self.field_type == 'CharField' and not self.max_length:
            self.max_length = 200
        if self.field_type == 'DecimalField':
            self.max_digits = self.max_digits or 12
            if self.decimal_places is None:
                self.decimal_places = 0
        super().save(*args, **kwargs)

    @property
    def is_relational(self):
        return self.field_type in self.RELATIONAL

    @property
    def is_textual(self):
        return self.field_type in self.TEXTUAL

    @property
    def choice_pairs(self):
        out = []
        for line in _lines(self.choices):
            k, _, v = line.partition('=')
            out.append((k.strip(), (v or k).strip()))
        return out

    @property
    def target_label(self):
        if self.related_model_id:
            return '%s.%s' % (self.related_model.app.name, self.related_model.name)
        return self.related_ref


class View(models.Model):
    """یک ویو — استاندارد (فهرست/جزئیات/ساخت/ویرایش/حذف/قالب) یا دستی.

    idea.md §۵.۴: «حالتِ استاندارد» کدِ قابلِ پیش‌بینی می‌سازد، «حالتِ
    پیشرفته» کدِ خامِ خودِ کاربر را عیناً می‌نشاند.
    """
    KIND = [
        ('list', 'فهرست (ListView)'),
        ('detail', 'جزئیات (DetailView)'),
        ('create', 'ساخت (CreateView)'),
        ('update', 'ویرایش (UpdateView)'),
        ('delete', 'حذف (DeleteView)'),
        ('template', 'صفحهٔ قالبی (TemplateView)'),
        ('custom', 'دستی — کدِ خام'),
    ]
    NEEDS_MODEL = {'list', 'detail', 'create', 'update', 'delete'}

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='views', verbose_name='اپ')
    name = models.CharField(max_length=60, verbose_name='نام (snake_case)',
                            help_text='مثلاً post_list — نامِ کلاس خودش ساخته می‌شود')
    kind = models.CharField(max_length=10, choices=KIND, default='list', verbose_name='نوع')
    model = models.ForeignKey(Model, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='views', verbose_name='مدل')
    description = models.CharField(max_length=200, blank=True, verbose_name='توضیح')
    template_body = models.TextField(blank=True, verbose_name='بدنهٔ قالب',
                                     help_text='داخلِ block content می‌نشیند')
    css = models.TextField(blank=True, verbose_name='CSSِ همین صفحه')
    paginate_by = models.PositiveIntegerField(null=True, blank=True, verbose_name='صفحه‌بندی')
    ordering = models.CharField(max_length=120, blank=True, verbose_name='ترتیب')
    form_fields = models.CharField(max_length=300, blank=True, verbose_name='فیلدهای فرم',
                                   help_text='با کاما؛ خالی = همهٔ فیلدهای ویرایش‌پذیر')
    login_required = models.BooleanField(default=False, verbose_name='ورود لازم است')
    success_url_name = models.CharField(max_length=80, blank=True, verbose_name='بعد از موفقیت برو به (نامِ نشانی)')
    context_object_name = models.CharField(max_length=60, blank=True, verbose_name='نامِ متغیر در قالب')
    custom_code = models.TextField(blank=True, verbose_name='کدِ خام',
                                   help_text='یک تابع یا کلاسِ کاملِ پایتون؛ عیناً در views.py می‌نشیند')
    managed = models.BooleanField(default=True, verbose_name='استودیو کدش را می‌نویسد')
    order = models.PositiveIntegerField(default=100, verbose_name='ترتیب')

    class Meta:
        verbose_name = 'ویو'
        verbose_name_plural = 'ویوها'
        ordering = ['order', 'id']
        unique_together = [('app', 'name')]

    def __str__(self):
        return '%s.%s' % (self.app.name, self.name)

    def save(self, *args, **kwargs):
        if self.managed:
            self.name = _snake(self.name)
        super().save(*args, **kwargs)

    @property
    def class_name(self):
        if self.kind == 'custom':
            m = re.search(r'^\s*(?:class|def)\s+([A-Za-z_]\w*)', self.custom_code or '', re.M)
            return m.group(1) if m else self.name
        c = _camel(self.name)
        return c if c.endswith('View') else c + 'View'

    @property
    def is_class_based(self):
        if self.kind != 'custom':
            return True
        return bool(re.search(r'^\s*class\s+', self.custom_code or '', re.M))

    @property
    def view_ref(self):
        """عبارتی که در urls.py می‌نشیند."""
        return 'views.%s.as_view()' % self.class_name if self.is_class_based else 'views.%s' % self.class_name

    @property
    def template_name(self):
        return '%s/%s.html' % (self.app.name, self.name)

    @property
    def css_name(self):
        return '%s_%s' % (self.app.name, self.name)

    @property
    def field_list(self):
        return _csv(self.form_fields)

    @property
    def needs_template(self):
        return self.kind != 'custom'


class Route(models.Model):
    """یک خطِ urlpatterns — در اپ (urls.py همان اپ) یا در ریشه (config/urls.py)."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='routes', verbose_name='پروژه')
    app = models.ForeignKey(App, on_delete=models.CASCADE, null=True, blank=True,
                            related_name='routes', verbose_name='اپ',
                            help_text='خالی = نشانیِ ریشه (config/urls.py)')
    pattern = models.CharField(max_length=200, blank=True, verbose_name='الگو',
                               help_text='مثلاً posts/<int:pk>/ — خالی = ریشهٔ همان اپ')
    name = models.CharField(max_length=80, blank=True, verbose_name='نامِ نشانی')
    view = models.ForeignKey(View, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='routes', verbose_name='ویو')
    view_text = models.CharField(max_length=200, blank=True, verbose_name='ویو (متنی)',
                                 help_text='اگر ویو را از فهرست انتخاب نکردی: مثلاً views.about یا include(…)')
    managed = models.BooleanField(default=True, verbose_name='استودیو کدش را می‌نویسد')
    order = models.PositiveIntegerField(default=100, verbose_name='ترتیب')

    class Meta:
        verbose_name = 'نشانی (URL)'
        verbose_name_plural = 'نشانی‌ها (URL)'
        ordering = ['app__order', 'order', 'id']

    def __str__(self):
        return '/%s' % self.full_pattern

    @property
    def target(self):
        return self.view.view_ref if self.view_id else (self.view_text or 'views.TODO')

    @property
    def full_pattern(self):
        return ((self.app.effective_prefix if self.app_id else '') + (self.pattern or '')).lstrip('/')

    @property
    def code(self):
        name = ", name='%s'" % self.name if self.name else ''
        return "path('%s', %s%s)," % (self.pattern or '', self.target, name)

    @property
    def root_alias(self):
        """در config/urls.py ویوی یک اپ با نامِ مستعار صدا زده می‌شود (views خودش مالِ config است)."""
        return '%s_views' % self.view.app.name if self.view_id else ''

    @property
    def root_code(self):
        name = ", name='%s'" % self.name if self.name else ''
        if self.view_id:
            ref = self.view.view_ref.replace('views.', self.root_alias + '.', 1)
        else:
            ref = self.view_text or 'views.TODO'
        return "path('%s', %s%s)," % (self.pattern or '', ref, name)


class Page(models.Model):
    """یک صفحهٔ فرانت — معماریِ سه‌بخشی (هدر/بدنه/فوتر) از idea.md §۶.

    فقط `body_html` و `css` مالِ این صفحه‌اند؛ هدر و فوتر مشترک‌اند و در
    خودِ پروژه نگه داشته می‌شوند. همین مرز است که اجازه می‌دهد ویرایش
    (دستی یا با AI) فقط همین صفحه را عوض کند.

    صفحهٔ `imported`: یک فایلِ قالبِ پروژهٔ واردشده (کلِ فایل در body_html).
    """
    KIND = [
        ('home', 'صفحهٔ اصلی'),
        ('product_list', 'فهرستِ محصولات'),
        ('product_detail', 'جزئیاتِ محصول'),
        ('cart', 'سبدِ خرید'),
        ('checkout', 'تسویه‌حساب'),
        ('static', 'صفحهٔ ساده'),
        ('imported', 'قالبِ واردشده'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='pages', verbose_name='پروژه')
    title = models.CharField(max_length=120, verbose_name='عنوانِ صفحه')
    slug = models.SlugField(max_length=80, verbose_name='نشانی (بعد از /)',
                            blank=True, allow_unicode=False,
                            help_text='خالی = صفحهٔ اصلی')
    kind = models.CharField(max_length=20, choices=KIND, default='static',
                            verbose_name='نوعِ صفحه')
    body_html = models.TextField(blank=True, verbose_name='بدنهٔ صفحه (HTML)')
    css = models.TextField(blank=True, verbose_name='CSSِ همین صفحه')
    in_menu = models.BooleanField(default=True, verbose_name='در منو بیاید')
    file_path = models.CharField(max_length=300, blank=True, verbose_name='فایل (واردشده)',
                                 help_text='نسبت به ریشهٔ پروژه؛ فقط صفحه‌های واردشده')
    synced_hash = models.CharField(max_length=40, blank=True, verbose_name='اثرِ انگشتِ آخرین نوشتن')
    order = models.PositiveIntegerField(default=100, verbose_name='ترتیب')

    class Meta:
        verbose_name = 'صفحه'
        verbose_name_plural = 'صفحه‌ها'
        ordering = ['order', 'id']
        unique_together = [('project', 'slug')]

    def __str__(self):
        return '%s (%s)' % (self.title, self.slug or '/')

    @property
    def is_imported(self):
        return self.kind == 'imported'

    @property
    def view_name(self):
        return 'page_%s' % (_snake(self.slug) if self.slug else 'home')

    @property
    def template_path(self):
        if self.file_path:
            return self.file_path
        return 'pages/%s.html' % (_snake(self.slug) if self.slug else 'home')

    @property
    def css_name(self):
        return _snake(self.slug) if self.slug else 'home'

    @property
    def url_pattern(self):
        return '' if not self.slug else '%s/' % self.slug


class SharedPart(models.Model):
    """هدر و فوترِ مشترکِ پروژه — عمداً جدا از صفحه‌ها."""
    KIND = [('header', 'هدر'), ('footer', 'فوتر'), ('base_css', 'CSSِ مشترک')]

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='shared_parts', verbose_name='پروژه')
    kind = models.CharField(max_length=12, choices=KIND, verbose_name='بخش')
    content = models.TextField(blank=True, verbose_name='محتوا')

    class Meta:
        verbose_name = 'بخشِ مشترک'
        verbose_name_plural = 'بخش‌های مشترک'
        unique_together = [('project', 'kind')]

    def __str__(self):
        return '%s — %s' % (self.project.slug, self.get_kind_display())


class Design(models.Model):
    """سندِ بلوک‌های ویرایشگرِ دیداری برای یک صفحه یا سربرگ/پابرگ.

    موتورِ تولید این جدول را نمی‌بیند؛ انتشار نتیجهٔ رندر را در Page.body_html/css یا SharedPart می‌نویسد.
    """
    TARGETS = [('page', 'صفحه'), ('header', 'سربرگ'), ('footer', 'پابرگ')]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='designs', verbose_name='پروژه')
    target = models.CharField(max_length=8, choices=TARGETS, default='page', verbose_name='بخش')
    page = models.OneToOneField(Page, on_delete=models.CASCADE, null=True, blank=True, related_name='design', verbose_name='صفحه')
    draft = models.JSONField(default=dict, blank=True, verbose_name='پیش‌نویس')
    published = models.JSONField(null=True, blank=True, verbose_name='منتشرشده')
    published_css = models.TextField(blank=True, verbose_name='CSSِ سربرگ/پابرگ')
    synced_hash = models.CharField(max_length=40, blank=True, verbose_name='اثرِ انگشتِ محتوای همخوان')
    rev = models.PositiveIntegerField(default=1, verbose_name='شمارهٔ بازنگری')
    keep_out_of_menu = models.BooleanField(default=False, verbose_name='خودکار به منو نرود')
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='آخرین انتشار')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'طراحیِ دیداری'
        verbose_name_plural = 'طراحی‌های دیداری'
        constraints = [models.UniqueConstraint(fields=['project', 'target'], condition=models.Q(page__isnull=True),
                                               name='projects_design_one_shared_per_target')]

    def __str__(self):
        return '%s — %s' % (self.project.slug, self.page.title if self.page_id else self.get_target_display())


class DesignVersion(models.Model):
    """نسخه‌های قبلیِ یک طراحی: هر انتشار و هر پیش‌نویسی که قرار بود روی آن نوشته شود."""
    KINDS = [('publish', 'انتشار'), ('draft', 'پیش‌نویس'), ('external', 'تغییرِ بیرونی')]
    design = models.ForeignKey(Design, on_delete=models.CASCADE, related_name='versions')
    doc = models.JSONField(default=dict)
    rendered_hash = models.CharField(max_length=40, blank=True, db_index=True)
    label = models.CharField(max_length=160, blank=True)
    kind = models.CharField(max_length=10, choices=KINDS, default='publish')
    user = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'نسخهٔ طراحی'
        verbose_name_plural = 'نسخه‌های طراحی'
        ordering = ['-created_at', '-id']


class SiteTheme(models.Model):
    """پوسته و منوی سایت. `active` یعنی این پروژه از ویرایشگرِ دیداری منتشر کرده؛ تا پیش از آن خروجی دست نمی‌خورد."""
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='site_theme')
    active = models.BooleanField(default=False, verbose_name='ویرایشگرِ دیداری فعال است')
    draft = models.JSONField(default=dict, blank=True)
    published = models.JSONField(default=dict, blank=True)
    menu = models.JSONField(default=list, blank=True)
    menu_published = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پوستهٔ سایت'
        verbose_name_plural = 'پوسته‌های سایت'

    def __str__(self):
        return self.project.slug


class MediaAsset(models.Model):
    """یک فایل در کتابخانهٔ رسانهٔ پروژه؛ خودِ فایل در static/site-media ِ همان پروژه است."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='media_assets')
    kind = models.CharField(max_length=8, default='image')
    name = models.CharField(max_length=120, blank=True, verbose_name='نام')
    alt = models.CharField(max_length=200, blank=True, verbose_name='توضیحِ تصویر')
    rel_path = models.CharField(max_length=200)
    variants = models.JSONField(default=dict, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    size = models.PositiveIntegerField(default=0)
    sha = models.CharField(max_length=32, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'فایلِ رسانه'
        verbose_name_plural = 'فایل‌های رسانه'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.name


class SavedSection(models.Model):
    """بخشی که کاربر برای استفادهٔ دوباره ذخیره کرده."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='saved_sections')
    title = models.CharField(max_length=120)
    doc = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'بخشِ ذخیره‌شده'
        verbose_name_plural = 'بخش‌های ذخیره‌شده'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title


class BuildLog(models.Model):
    """هر بار تولیدِ کد یک ردیف — تا معلوم باشد چه وقت چه چیزی نوشته شد."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='builds', verbose_name='پروژه')
    ok = models.BooleanField(default=True, verbose_name='موفق')
    summary = models.CharField(max_length=200, blank=True, verbose_name='خلاصه')
    detail = models.TextField(blank=True, verbose_name='جزئیات')
    files_written = models.PositiveIntegerField(default=0, verbose_name='فایلِ نوشته‌شده')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'گزارشِ تولید'
        verbose_name_plural = 'گزارش‌های تولید'
        ordering = ['-created_at']

    def __str__(self):
        return '%s — %s' % (self.project.slug, self.summary)


class PublishedSite(models.Model):
    """سایتی که واقعاً روی اینترنت است (یا بوده). کد در releases/، داده در shared/؛ hosting/publisher.py"""
    NONE, PUBLISHING, LIVE, STOPPED, FAILED, UNPUBLISHED = 'none', 'publishing', 'live', 'stopped', 'failed', 'unpublished'
    STATES = [(NONE, 'منتشر نشده'), (PUBLISHING, 'در حالِ انتشار'), (LIVE, 'روی اینترنت'), (STOPPED, 'خاموش'),
              (FAILED, 'خراب'), (UNPUBLISHED, 'برداشته شده')]
    DOMAIN_NONE, DOMAIN_WAITING, DOMAIN_HTTP, DOMAIN_ISSUING, DOMAIN_ACTIVE, DOMAIN_FAILED = '', 'waiting', 'http', 'issuing', 'active', 'failed'
    DOMAIN_STATES = [(DOMAIN_NONE, 'بدون دامنه'), (DOMAIN_WAITING, 'منتظرِ DNS'), (DOMAIN_HTTP, 'وصل بدونِ قفل'),
                     (DOMAIN_ISSUING, 'گرفتنِ گواهی'), (DOMAIN_ACTIVE, 'وصل با قفل'), (DOMAIN_FAILED, 'خطا')]

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='published_site', verbose_name='پروژه')
    key = models.CharField('کلیدِ سیستم', max_length=28, unique=True, editable=False)
    state = models.CharField('وضعیت', max_length=12, choices=STATES, default=NONE)
    port = models.PositiveIntegerField('پورتِ عمومی', null=True, blank=True, unique=True)
    local_port = models.PositiveIntegerField('پورتِ داخلی', null=True, blank=True)
    current_release = models.CharField('نسخهٔ فعلی', max_length=32, blank=True)
    previous_release = models.CharField('نسخهٔ قبلی', max_length=32, blank=True)
    last_publish_at = models.DateTimeField('آخرین انتشار', null=True, blank=True)
    last_error = models.TextField('آخرین خطا', blank=True)
    last_technical = models.TextField('جزئیاتِ فنی', blank=True)
    admin_user = models.CharField('کاربرِ مدیریت', max_length=120, blank=True)
    admin_password = models.CharField('رمزِ مدیریت', max_length=120, blank=True)
    domain = models.CharField('دامنه', max_length=253, blank=True, db_index=True)
    domain_www = models.BooleanField('www هم', default=False)
    domain_state = models.CharField('وضعیتِ دامنه', max_length=10, choices=DOMAIN_STATES, blank=True, default=DOMAIN_NONE)
    domain_error = models.TextField('خطای دامنه', blank=True)
    domain_staging = models.BooleanField('گواهیِ آزمایشی', default=False)
    cert_expires = models.CharField('پایانِ گواهی', max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'سایتِ منتشرشده'
        verbose_name_plural = 'سایت‌های منتشرشده'

    def __str__(self):
        return '%s (%s)' % (self.key, self.get_state_display())

    @property
    def domain_names(self):
        if not self.domain:
            return []
        return [self.domain, 'www.' + self.domain] if self.domain_www else [self.domain]


class SiteRelease(models.Model):
    BUILDING, OK, FAILED = 'building', 'ok', 'failed'
    site = models.ForeignKey(PublishedSite, on_delete=models.CASCADE, related_name='releases')
    rid = models.CharField(max_length=32)
    status = models.CharField(max_length=10, default=BUILDING)
    user = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=300, blank=True)
    db_backup = models.CharField(max_length=80, blank=True)
    migrations = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'نسخهٔ سایت'
        verbose_name_plural = 'نسخه‌های سایت'


class SiteJob(models.Model):
    """یک کارِ پس‌زمینه با پیشرفتِ قابلِ دیدن در پنل."""
    PUBLISH, ROLLBACK, DOMAIN, DOMAIN_OFF, STOP, START, UNPUBLISH, RESET_ADMIN = 'publish', 'rollback', 'domain', 'domain_off', 'stop', 'start', 'unpublish', 'reset_admin'
    QUEUED, RUNNING, OK, FAILED = 'queued', 'running', 'ok', 'failed'
    site = models.ForeignKey(PublishedSite, on_delete=models.CASCADE, related_name='jobs')
    kind = models.CharField(max_length=12)
    state = models.CharField(max_length=10, default=QUEUED)
    user = models.CharField(max_length=80, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    steps = models.JSONField(default=list, blank=True)
    message = models.TextField(blank=True)
    technical = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'کارِ انتشار'
        verbose_name_plural = 'کارهای انتشار'

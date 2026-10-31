# -*- coding: utf-8 -*-
"""موتورِ هوشِ مصنوعی — فازهای ۰۶ و ۰۷ از idea.md.

اصلِ کار (idea.md §۷.۳ «چرخهٔ امنِ اعمالِ تغییر»):
  درخواست ⇒ Context ِ محدود ⇒ پیشنهاد (AiProposal با چند AiChange)
  ⇒ وارسی ⇒ Diff ⇒ تأییدِ کاربر ⇒ اعمال ⇒ تولیدِ کد ⇒ (بازگردانی در صورتِ نیاز)

هیچ پیشنهادی خودش اعمال نمی‌شود. هر تغییر، «قبل» و «بعد» را نگه می‌دارد.
"""
from django.db import models


class AiSettings(models.Model):
    """تنظیماتِ سرویسِ هوشِ مصنوعی — یک ردیف (pk=1)، از جنگو ادمین قابلِ ویرایش.

    همهٔ درخواست‌ها با کتابخانهٔ رسمیِ `openai` فرستاده می‌شوند؛ پس هر سرویسی
    که API ِ سازگار با OpenAI دارد (OpenAI، Metis، OpenRouter، Groq، Together،
    DeepSeek، Ollama ِ محلی، …) با عوض‌کردنِ همین سه مقدار کار می‌کند:
    نشانیِ پایه (Base URL)، کلید (توکن) و نامِ مدل.
    """
    PROVIDERS = [
        ('openai', 'کتابخانهٔ OpenAI — هر سرویسِ سازگار (OpenAI، Metis، OpenRouter، …)'),
        ('mock', 'آزمایشی — بدونِ اینترنت و کلید (فقط برای امتحانِ روند)'),
    ]
    provider = models.CharField(max_length=12, choices=PROVIDERS, default='openai', verbose_name='سرویس')
    base_url = models.CharField(
        max_length=200, blank=True, verbose_name='نشانیِ پایه (Base URL)',
        help_text='OpenAI: https://api.openai.com/v1 · Metis: https://api.metisai.ir/openai/v1 · '
                  'OpenRouter: https://openrouter.ai/api/v1 — خالی = OpenAI')
    api_key = models.CharField(max_length=300, blank=True, verbose_name='کلید (توکن) API')
    model = models.CharField(max_length=120, default='gpt-4o-mini', verbose_name='نامِ مدل',
                             help_text='دقیقاً همان نامی که سرویس می‌شناسد، مثلاً gpt-4o-mini یا gpt-4.1')
    temperature = models.FloatField(default=0.3, verbose_name='خلاقیت (temperature)',
                                    help_text='0 تا 2؛ مدل‌هایی که نمی‌پذیرند خودکار بی‌آن فرستاده می‌شوند')
    max_tokens = models.PositiveIntegerField(default=6000, verbose_name='حداکثر توکنِ پاسخ')
    timeout_s = models.PositiveIntegerField(default=120, verbose_name='مهلت (ثانیه)')
    ROUTE_MODES = [('qwen_first', 'اول Qwen روی سرورِ پردازش؛ اگر نبود Metis'), ('metis_only', 'فقط Metis')]
    route_mode = models.CharField(max_length=12, choices=ROUTE_MODES, default='qwen_first', verbose_name='کارهای متن و کد کجا انجام شوند')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تنظیماتِ هوشِ مصنوعی'
        verbose_name_plural = 'تنظیماتِ هوشِ مصنوعی'

    def __str__(self):
        return '%s / %s' % (self.get_provider_display(), self.model)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        if obj.provider == 'openai' and not obj.api_key:
            # کلیدِ سراسریِ محصول (AI_API_* در .env) — تا سایت‌ساز بی‌تنظیمِ جداگانه کار کند
            from django.conf import settings
            conf = getattr(settings, 'UPMARKET_AI', {}) or {}
            if conf.get('AI_API_KEY'):
                obj.api_key = conf['AI_API_KEY']
                obj.base_url = obj.base_url or conf.get('AI_API_BASE_URL', '')
                obj.model = obj.model or conf.get('AI_API_MODEL_TEXT', 'gpt-4o-mini')
        return obj

    @property
    def masked_key(self):
        k = self.api_key or ''
        return (k[:4] + '…' + k[-3:]) if len(k) > 10 else ('•' * len(k))

    @property
    def is_ready(self):
        return self.provider == 'mock' or bool(self.api_key)


class AiProposal(models.Model):
    """یک «پیشنهادِ تغییر» — نتیجهٔ یک درخواست از AI."""
    TASKS = [
        ('generate_frontend', 'ساختِ فرانتِ اولیه'),
        ('edit_page', 'ویرایشِ یک صفحه'),
        ('edit_shared', 'ویرایشِ هدر/فوتر/CSS'),
        ('edit_view', 'ویرایشِ قالبِ یک ویو'),
        ('suggest_models', 'پیشنهادِ مدل و فیلد'),
    ]
    STATUS = [
        ('running', 'AI در حالِ کار'),
        ('pending', 'در انتظارِ تأیید'),
        ('applied', 'اعمال شد'),
        ('rejected', 'رد شد'),
        ('reverted', 'بازگردانده شد'),
        ('failed', 'ناموفق'),
    ]
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE,
                                related_name='ai_proposals', verbose_name='پروژه')
    task = models.CharField(max_length=20, choices=TASKS, verbose_name='نوعِ کار')
    title = models.CharField(max_length=200, blank=True, verbose_name='عنوان')
    prompt_text = models.TextField(blank=True, verbose_name='درخواستِ کاربر')
    summary = models.TextField(blank=True, verbose_name='خلاصهٔ AI')
    status = models.CharField(max_length=10, choices=STATUS, default='running', verbose_name='وضعیت')
    error = models.TextField(blank=True, verbose_name='خطا')
    provider_model = models.CharField(max_length=120, blank=True, verbose_name='سرویس/مدل')
    answered_by = models.CharField(max_length=120, blank=True, verbose_name='مدلی که جواب داد')
    fallback_note = models.CharField(max_length=400, blank=True, verbose_name='چرا جایگزین')
    calls = models.PositiveIntegerField(default=0, verbose_name='تعدادِ فراخوانی')
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'پیشنهادِ AI'
        verbose_name_plural = 'پیشنهادهای AI'
        ordering = ['-created_at']

    def __str__(self):
        return '%s — %s' % (self.get_task_display(), self.title or self.pk)

    @property
    def is_running(self):
        return self.status == 'running'

    @property
    def can_apply(self):
        return self.status == 'pending' and self.changes.exists() and not self.changes.filter(valid=False).exists()

    @property
    def can_revert(self):
        return self.status == 'applied'


class AiChange(models.Model):
    """یک تغییرِ مشخص روی یک هدفِ مشخص — همان «Patch» idea.md، با قبل/بعد."""
    TARGETS = [
        ('page_body', 'بدنهٔ صفحه'),
        ('page_css', 'CSSِ صفحه'),
        ('page_file', 'فایلِ قالبِ واردشده'),
        ('shared_header', 'هدر'),
        ('shared_footer', 'فوتر'),
        ('shared_css', 'CSSِ مشترک'),
        ('view_template', 'قالبِ ویو'),
        ('view_css', 'CSSِ ویو'),
        ('model_spec', 'مدل‌ها و فیلدها'),
        ('sample_data', 'دسته و محصولِ نمونه'),
    ]
    proposal = models.ForeignKey(AiProposal, on_delete=models.CASCADE, related_name='changes')
    target = models.CharField(max_length=16, choices=TARGETS, verbose_name='هدف')
    label = models.CharField(max_length=160, blank=True, verbose_name='برچسب')
    page = models.ForeignKey('projects.Page', on_delete=models.SET_NULL, null=True, blank=True)
    view = models.ForeignKey('projects.View', on_delete=models.SET_NULL, null=True, blank=True)
    old_content = models.TextField(blank=True, verbose_name='قبل')
    new_content = models.TextField(blank=True, verbose_name='بعد')
    diff_text = models.TextField(blank=True, verbose_name='Diff')
    valid = models.BooleanField(default=True, verbose_name='معتبر')
    issues = models.TextField(blank=True, verbose_name='ایرادها/هشدارها')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'تغییرِ AI'
        verbose_name_plural = 'تغییرهای AI'

    def __str__(self):
        return '%s: %s' % (self.get_target_display(), self.label)

    @property
    def is_css(self):
        return self.target in ('page_css', 'shared_css', 'view_css')

    @property
    def is_html(self):
        return self.target in ('page_body', 'page_file', 'shared_header', 'shared_footer', 'view_template')

    @property
    def unchanged(self):
        return (self.old_content or '').strip() == (self.new_content or '').strip()


class AiRouteLog(models.Model):
    """آخرین پاسخ‌ها: کدام مدل جواب داد و اگر جایگزین شد چرا؛ در صفحهٔ تنظیمات نشان داده می‌شود."""
    task = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=120, blank=True)
    via = models.CharField(max_length=10, default='node')
    fell_back = models.BooleanField(default=False)
    reason = models.CharField(max_length=400, blank=True)
    seconds = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'مسیرِ پاسخِ هوشِ مصنوعی'
        verbose_name_plural = 'مسیرِ پاسخ‌های هوشِ مصنوعی'

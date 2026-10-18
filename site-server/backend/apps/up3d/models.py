import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

STATES = [
    ('PENDING', 'در صف'), ('PLANNING', 'برنامه‌ریزی (AI)'), ('PLANNED', 'برنامه آماده'),
    ('SCENE_BUILDING', 'ساختِ صحنه'), ('RENDERING', 'رندر'), ('QUALITY_CHECK', 'کنترلِ کیفیت'),
    ('ASSEMBLING', 'مونتاژ'), ('COMPLETED', 'تمام شد'), ('FAILED', 'ناموفق'), ('CANCELLED', 'لغو شد'),
]
FINAL = ('COMPLETED', 'FAILED', 'CANCELLED')
KINDS = [('plan', 'برنامه‌ریزی'), ('render', 'ویدئو'), ('export', 'خروجیِ سه‌بعدی'), ('contact', 'نمونهٔ فریم'),
         ('thumbnail', 'تصویرِ دارایی')]


class AiSettings(models.Model):
    """تنظیمِ هوشِ مصنوعی و صدا — از جنگو ادمین. هر سرویسِ سازگار با OpenAI (Metis، OpenAI، …)."""
    enabled = models.BooleanField('کارگردانِ AI روشن باشد', default=True)
    base_url = models.CharField('Base URL', max_length=300, blank=True, help_text='مثلاً https://api.metisai.ir/openai/v1 ؛ خالی = OpenAI')
    api_key = models.CharField('کلید (توکن)', max_length=500, blank=True)
    model = models.CharField('مدلِ متن', max_length=100, default='gpt-4o-mini')
    temperature = models.FloatField('خلاقیت (temperature)', default=0.7)
    tts_enabled = models.BooleanField('صدای واقعی (TTS)', default=True)
    tts_model = models.CharField('مدلِ صدا', max_length=100, default='tts-1')
    tts_base_url = models.CharField('Base URL ِ صدا (اختیاری)', max_length=300, blank=True, help_text='خالی = همان بالا')
    tts_api_key = models.CharField('کلیدِ صدا (اختیاری)', max_length=500, blank=True, help_text='خالی = همان بالا')
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = 'تنظیماتِ هوشِ مصنوعی و صدا'

    def __str__(self):
        return 'تنظیماتِ AI (%s)' % (self.model or '-')

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        if not obj.api_key:
            # کلیدِ سراسریِ محصول (AI_API_* در .env) — تا کارگردانِ سه‌بعدی بی‌تنظیمِ جداگانه کار کند
            conf = getattr(settings, 'UPMARKET_AI', {}) or {}
            if conf.get('AI_API_KEY'):
                obj.api_key = conf['AI_API_KEY']
                obj.base_url = obj.base_url or conf.get('AI_API_BASE_URL', '')
                obj.model = obj.model or conf.get('AI_API_MODEL_TEXT', 'gpt-4o-mini')
        return obj

    def llm(self):
        return {'base_url': self.base_url, 'api_key': self.api_key, 'model': self.model, 'temperature': self.temperature}

    def tts(self):
        if not self.tts_enabled:
            return {'api_key': ''}
        return {'base_url': self.tts_base_url or self.base_url, 'api_key': self.tts_api_key or self.api_key,
                'model': self.tts_model}


class Project(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField('عنوان', max_length=200)
    brief = models.JSONField('خلاصهٔ کار', default=dict, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    current = models.ForeignKey('SceneVersion', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    poster = models.CharField(max_length=400, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated']
        verbose_name, verbose_name_plural = 'پروژه', 'پروژه‌ها'

    def __str__(self):
        return self.title

    def latest_video(self):
        return self.jobs.filter(kind='render', state='COMPLETED').order_by('-finished').first()


class SceneVersion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    document = models.JSONField()
    source = models.CharField(max_length=40, default='editor')
    note = models.CharField(max_length=300, blank=True)
    valid = models.BooleanField(default=False)
    report = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-number']
        unique_together = [('project', 'number')]
        verbose_name, verbose_name_plural = 'نسخهٔ صحنه', 'نسخه‌های صحنه'

    def __str__(self):
        return '%s · v%d' % (self.project.title, self.number)


def _token():
    return secrets.token_urlsafe(32)


class Worker(models.Model):
    name = models.CharField('نام', max_length=100, unique=True)
    token = models.CharField(max_length=80, unique=True, default=_token)
    enabled = models.BooleanField('فعال', default=True)
    profiles = models.JSONField('پروفایل‌های مجاز (خالی = خودکار)', default=list, blank=True)
    capabilities = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)      # {profile: {'sec_per_frame': x, 'n': k}}
    last_seen = models.DateTimeField(null=True, blank=True)
    jobs_done = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name, verbose_name_plural = 'کارگرِ رندر', 'کارگرهای رندر'

    def __str__(self):
        return self.name

    @property
    def online(self):
        return bool(self.last_seen and (timezone.now() - self.last_seen).total_seconds() < 90)

    @property
    def has_gpu(self):
        return bool((self.capabilities or {}).get('gpu'))

    def accepts(self, profile_asset):
        if self.profiles:
            return profile_asset.id in self.profiles
        if self.has_gpu:
            return True
        return (profile_asset or {}).get('recommended', 'cpu') == 'cpu'


class Job(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    version = models.ForeignKey(SceneVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
    kind = models.CharField(max_length=20, choices=KINDS, default='render')
    profile = models.CharField(max_length=40, blank=True)
    params = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=20, choices=STATES, default='PENDING', db_index=True)
    owner = models.CharField(max_length=10, default='panel', db_index=True)      # panel | worker
    worker = models.ForeignKey(Worker, null=True, blank=True, on_delete=models.SET_NULL, related_name='jobs')
    progress = models.FloatField(default=0.0)
    frames_done = models.IntegerField(default=0)
    frames_total = models.IntegerField(default=0)
    sec_per_frame = models.FloatField(null=True, blank=True)
    message = models.CharField(max_length=400, blank=True)
    error = models.TextField(blank=True)
    log = models.TextField(blank=True)
    qc = models.JSONField(default=dict, blank=True)
    report = models.JSONField(default=dict, blank=True)
    files = models.JSONField(default=dict, blank=True)         # {نام: مسیرِ نسبی در data/}
    estimate_seconds = models.FloatField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    started = models.DateTimeField(null=True, blank=True)
    claimed = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created']
        verbose_name, verbose_name_plural = 'کار', 'کارها'

    def __str__(self):
        return '%s #%s (%s)' % (self.get_kind_display(), self.pk, self.state)

    @property
    def final(self):
        return self.state in FINAL

    def dir_rel(self):
        return 'jobs/%s' % self.uid

    def add_log(self, line, save=True):
        stamp = timezone.localtime().strftime('%H:%M:%S')
        self.log = (self.log + '\n' if self.log else '') + '%s  %s' % (stamp, line)
        self.log = self.log[-60000:]
        if save:
            self.save(update_fields=['log'])

    def set_state(self, state, message='', owner=None):
        self.state = state
        if message:
            self.message = message[:400]
            self.add_log('[%s] %s' % (state, message), save=False)
        if owner:
            self.owner = owner
        if state in FINAL:
            self.finished = timezone.now()
        self.save()


class Upload(models.Model):
    KIND = [('image', 'تصویر'), ('model', 'مدلِ سه‌بعدی'), ('music', 'موسیقی'), ('other', 'دیگر')]
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=10, choices=KIND, default='image')
    name = models.CharField(max_length=200)
    path = models.CharField(max_length=400)
    size = models.IntegerField(default=0)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']
        verbose_name, verbose_name_plural = 'فایلِ بارگذاری‌شده', 'فایل‌های بارگذاری‌شده'

    def __str__(self):
        return self.name

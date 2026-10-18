from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from .models import AiSettings, Job, Project, SceneVersion, Upload, Worker


class AiSettingsForm(forms.ModelForm):
    api_key = forms.CharField(label='کلید (توکن)', required=False, widget=forms.PasswordInput(render_value=True))
    tts_api_key = forms.CharField(label='کلیدِ صدا (اختیاری)', required=False, widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = AiSettings
        fields = '__all__'


@admin.register(AiSettings)
class AiSettingsAdmin(admin.ModelAdmin):
    name_en = "3D AI settings"
    description = ("کارگردانِ هوشِ مصنوعی و صدای ویدیوی سه‌بعدی (مدلِ متن و TTS). خالی باشد، از کلیدِ سراسریِ "
                   "محصول (AI_API_* در .env) استفاده می‌شود.")
    form = AiSettingsForm
    list_display = ('__str__', 'enabled', 'model', 'base_url', 'tts_enabled', 'tts_model', 'updated')
    actions = ['test_connection']
    fieldsets = (('مدلِ متن (کارگردان)', {'fields': ('enabled', 'base_url', 'api_key', 'model', 'temperature')}),
                 ('صدا (TTS)', {'fields': ('tts_enabled', 'tts_model', 'tts_base_url', 'tts_api_key')}))

    def has_add_permission(self, request):
        return not AiSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='آزمونِ اتصال (متن + صدا)')
    def test_connection(self, request, queryset):
        from up3d import director, tts
        from up3d.assets import registry
        s = AiSettings.get()
        try:
            raw, usage = director._chat(s.llm(), [{'role': 'user', 'content': 'Reply with JSON {"ok": true, "fa": "<one Persian word>"}'}])
            self.message_user(request, 'مدلِ متن جواب داد: %s' % raw[:120], messages.SUCCESS)
        except Exception as e:
            self.message_user(request, 'مدلِ متن: %s' % e, messages.ERROR)
        try:
            out = tts.synthesize('سلام، این آزمونِ صدای فارسی است.', registry().default('voice'), s.tts())
            self.message_user(request, 'صدا ساخته شد: %.1f ثانیه (%s)' % (out['duration'], out['provider']), messages.SUCCESS)
        except Exception as e:
            self.message_user(request, 'صدا: %s' % e, messages.ERROR)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    name_en = "3D video projects"
    description = "هر پروژه یک ویدیوی تبلیغاتیِ سه‌بعدی است: خلاصهٔ کار، نسخه‌های صحنه و کارهای رندرش."
    list_display = ('id', 'title', 'current', 'owner', 'created', 'updated')
    search_fields = ('title', 'uid')
    list_filter = ('created',)
    readonly_fields = ('uid', 'created', 'updated')
    raw_id_fields = ('current',)


@admin.register(SceneVersion)
class SceneVersionAdmin(admin.ModelAdmin):
    name_en = "Scene versions"
    description = "سندِ صحنه (JSON) در هر بار ویرایش یک نسخهٔ تازه می‌گیرد؛ «معتبر» یعنی از وارسی گذشته است."
    list_display = ('id', 'project', 'number', 'source', 'valid', 'created')
    list_filter = ('source', 'valid')
    search_fields = ('project__title', 'note')
    readonly_fields = ('created',)
    raw_id_fields = ('project',)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    name_en = "3D jobs"
    description = ("برنامه‌ریزی، رندر، خروجیِ سه‌بعدی و نمونهٔ فریم. رندرهای سبک روی همین سرور (server-cpu) و "
                   "رندرهای باکیفیت روی سرورِ پردازشِ GPU انجام می‌شوند.")
    list_display = ('id', 'kind', 'profile', 'state', 'progress_pct', 'owner', 'worker', 'created', 'finished')
    list_filter = ('state', 'kind', 'profile', 'worker')
    search_fields = ('uid', 'project__title', 'message', 'error')
    date_hierarchy = 'created'
    readonly_fields = ('uid', 'progress', 'frames_done', 'frames_total', 'sec_per_frame', 'message', 'error', 'log',
                       'qc', 'report', 'files', 'estimate_seconds', 'created', 'started', 'claimed', 'finished')
    raw_id_fields = ('project', 'version')
    fieldsets = (
        (None, {'fields': ('uid', 'project', 'version', 'kind', 'profile', 'params', 'state', 'owner', 'worker')}),
        ('پیشرفت', {'fields': ('progress', 'frames_done', 'frames_total', 'sec_per_frame', 'estimate_seconds',
                               'message', 'error', 'cancel_requested')}),
        ('خروجی و گزارش', {'fields': ('files', 'qc', 'report', 'log'), 'classes': ('collapse',)}),
        ('زمان‌ها', {'fields': ('created', 'started', 'claimed', 'finished'), 'classes': ('collapse',)}),
    )

    @admin.display(description='پیشرفت', ordering='progress')
    def progress_pct(self, obj):
        return '%d٪' % int((obj.progress or 0) * 100)

    def has_add_permission(self, request):
        return False


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    name_en = "Render workers"
    description = ("کارگرهای رندرِ Blender. «server-cpu» همین سرور است (فقط انیمیک و پیش‌نمایش)؛ کارگرِ GPU همان "
                   "سرورِ پردازش است که با توکنِ خودش وصل می‌شود.")
    list_display = ('name', 'online_badge', 'enabled', 'gpu_text', 'jobs_done', 'last_seen')
    list_filter = ('enabled',)
    search_fields = ('name',)
    readonly_fields = ('token', 'capabilities', 'stats', 'last_seen', 'jobs_done', 'created')

    @admin.display(description='وضعیت')
    def online_badge(self, obj):
        if not obj.enabled:
            return format_html('<span style="color:#888">غیرفعال</span>')
        return format_html('<span style="color:#0a0">● آنلاین</span>') if obj.online else format_html(
            '<span style="color:#c00">● آفلاین</span>')

    @admin.display(description='سخت‌افزار')
    def gpu_text(self, obj):
        gpu = (obj.capabilities or {}).get('gpu')
        if gpu:
            return 'GPU: ' + (', '.join(gpu) if isinstance(gpu, list) else str(gpu))
        cpus = (obj.capabilities or {}).get('cpu_count')
        return 'CPU %s هسته' % cpus if cpus else '—'


@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    name_en = "3D uploads"
    description = "عکسِ برچسب، مدلِ سه‌بعدی و موسیقی که کاربر برای پروژه‌های سه‌بعدی بارگذاری کرده است."
    list_display = ('name', 'kind', 'size', 'owner', 'created')
    list_filter = ('kind',)
    search_fields = ('name',)
    readonly_fields = ('uid', 'created')

# -*- coding: utf-8 -*-
"""جنگو ادمین ⇐ «تنظیماتِ هوشِ مصنوعی»: نشانیِ پایه، کلید (توکن) و نامِ مدل.

· فقط یک ردیف هست؛ فهرست مستقیم به صفحهٔ ویرایشِ همان می‌رود.
· کلید هیچ‌وقت در صفحه نمایش داده نمی‌شود؛ خالی بگذاری، کلیدِ قبلی می‌ماند.
· دکمهٔ «ذخیره و آزمونِ اتصال» یک درخواستِ کوچک با کتابخانهٔ openai می‌فرستد
  و اگر سرویس اجازه بدهد، نامِ مدل‌هایش را هم نشان می‌دهد.
"""
from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from .models import AiChange, AiProposal, AiSettings
from .providers import AiError, get_provider


class AiSettingsForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False, label='کلید (توکن) API',
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password', 'style': 'width:32em'}),
        help_text='خالی بگذاری، کلیدِ قبلی می‌ماند. کلید فقط در دیتابیسِ همین سرور ذخیره می‌شود.')
    clear_key = forms.BooleanField(required=False, label='کلیدِ فعلی پاک شود')

    class Meta:
        model = AiSettings
        fields = ['provider', 'base_url', 'api_key', 'clear_key', 'model', 'temperature', 'max_tokens', 'timeout_s']
        widgets = {
            'base_url': forms.TextInput(attrs={'style': 'width:32em', 'dir': 'ltr'}),
            'model': forms.TextInput(attrs={'style': 'width:20em', 'dir': 'ltr'}),
        }

    def clean_api_key(self):
        v = (self.cleaned_data.get('api_key') or '').strip()
        return v or (self.instance.api_key if self.instance and self.instance.pk else '')

    def clean_base_url(self):
        v = (self.cleaned_data.get('base_url') or '').strip()
        if v and not v.startswith(('http://', 'https://')):
            raise forms.ValidationError('نشانی باید با http:// یا https:// شروع شود.')
        return v.rstrip('/')

    def clean_temperature(self):
        v = self.cleaned_data.get('temperature')
        if v is not None and not (0 <= v <= 2):
            raise forms.ValidationError('بین 0 و 2.')
        return v

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get('clear_key'):
            obj.api_key = ''
        if commit:
            obj.save()
        return obj


@admin.register(AiSettings)
class AiSettingsAdmin(admin.ModelAdmin):
    name_en = 'Studio AI settings'
    description = 'سرویسِ هوشِ مصنوعیِ سایت‌ساز (OpenAI/Metis/…): نشانیِ پایه، کلید و مدل. خالی باشد، کلیدِ سراسریِ محصول استفاده می‌شود.'
    form = AiSettingsForm
    change_form_template = 'admin/ai_engine/aisettings/change_form.html'
    readonly_fields = ['key_status', 'updated_at']
    fieldsets = [
        ('سرویس (کتابخانهٔ openai)', {'fields': ['provider', 'base_url', 'model']}),
        ('کلید', {'fields': ['key_status', 'api_key', 'clear_key']}),
        ('پیشرفته', {'fields': ['temperature', 'max_tokens', 'timeout_s', 'updated_at'], 'classes': ['collapse']}),
    ]
    list_display = ['provider', 'base_url', 'model', 'key_status', 'updated_at']

    @admin.display(description='کلیدِ ذخیره‌شده')
    def key_status(self, obj):
        if obj and obj.api_key:
            return format_html('<span style="color:#16a34a">✔ هست</span> <code dir="ltr">{}</code>', obj.masked_key)
        return format_html('<span style="color:#dc2626">✘ هنوز کلیدی گذاشته نشده</span>')

    def has_add_permission(self, request):
        # نوارِ کناریِ ادمین این را در هر صفحه‌ای صدا می‌زند؛ اگر دیتابیسِ استودیو در دسترس نباشد
        # (مثلاً در آزمونِ اپ‌های دیگر) نباید کلِ ادمین را بیندازد.
        try:
            return not AiSettings.objects.exists()
        except Exception:  # noqa: BLE001
            return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = AiSettings.get()
        return redirect(reverse('%s:ai_engine_aisettings_change' % self.admin_site.name, args=[obj.pk]))

    def response_change(self, request, obj):
        if '_test' in request.POST:
            test_connection(request, obj)
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)


def test_connection(request, cfg):
    """یک درخواستِ کوچک؛ نتیجه به‌صورتِ پیام. ⇒ True/False"""
    prov = get_provider(cfg)
    try:
        out = prov.ping()
    except AiError as exc:
        messages.error(request, 'اتصال برقرار نشد: %s' % exc)
        return False
    msg = 'اتصال برقرار است — مدلِ «%s» جواب داد: «%s»' % (cfg.model, (out or '').strip()[:80])
    names = prov.list_models(25)
    if names:
        msg += ' · مدل‌هایی که این سرویس اعلام می‌کند: ' + '، '.join(names)
    messages.success(request, msg)
    return True


class AiChangeInline(admin.TabularInline):
    model = AiChange
    extra = 0
    fields = ['target', 'label', 'valid', 'issues']
    readonly_fields = ['target', 'label', 'valid', 'issues']


@admin.register(AiProposal)
class AiProposalAdmin(admin.ModelAdmin):
    name_en = 'Studio AI proposals'
    description = 'پیشنهادهای هوشِ مصنوعی برای صفحه‌ها/ویوها/مدل‌ها؛ هیچ‌کدام بی‌تأییدِ کاربر اعمال نمی‌شود و قابلِ بازگردانی است.'
    list_display = ['project', 'task', 'title', 'status', 'calls', 'created_at']
    list_filter = ['task', 'status', 'project']
    inlines = [AiChangeInline]

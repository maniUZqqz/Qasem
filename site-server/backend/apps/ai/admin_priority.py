# -*- coding: utf-8 -*-
"""جنگو ادمین ⇐ «اولویتِ هوش مصنوعی (لوکال / متیس)»: همان تنظیمِ پنل (ادمین ⇐ موتورهای AI)، یک ردیفِ واحد."""
from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from .models import AiPriority, AiProviderState


class AiPriorityForm(forms.ModelForm):
    class Meta:
        model = AiPriority
        fields = "__all__"
        widgets = {
            "model_text": forms.TextInput(attrs={"dir": "ltr", "style": "width:20em", "placeholder": "gemma3:12b"}),
            "model_research": forms.TextInput(attrs={"dir": "ltr", "style": "width:20em", "placeholder": "qwq:32b"}),
            "model_code": forms.TextInput(attrs={"dir": "ltr", "style": "width:20em", "placeholder": "qwen3-coder:30b"}),
            "model_vision": forms.TextInput(attrs={"dir": "ltr", "style": "width:20em", "placeholder": "qwen3-vl:30b"}),
        }

    def clean(self):
        data = super().clean()
        for key in ("model_text", "model_research", "model_code", "model_vision"):
            value = (data.get(key) or "").strip()
            if any(c.isspace() for c in value):
                self.add_error(key, "نامِ مدل فاصله ندارد (مثلاً qwq:32b).")
            data[key] = value
        return data


@admin.register(AiPriority)
class AiPriorityAdmin(admin.ModelAdmin):
    name_en = "AI priority (local / Metis)"
    description = (
        "هر کارِ هوش مصنوعیِ NM می‌تواند هم روی سرورِ پردازش (لوکال: gemma3:12b / qwq:32b / qwen3-coder / qwen3-vl) و هم با متیس (API) "
        "انجام شود. این‌جا می‌گویی کدام اول باشد؛ اگر اولی در دسترس نبود (گره خاموش، مدل نصب نیست، مهلت، اعتبار تمام (۴۰۲)، "
        "۴۰۱/۴۰۳، ۵xx، قطعِ اتصال) خودکار دومی جواب می‌دهد. وضعِ زنده و دکمهٔ «آزمون» در پنل است: ادمین ⇐ موتورهای AI."
    )
    form = AiPriorityForm
    readonly_fields = ["live_status", "updated_at"]
    fieldsets = [
        ("اولویتِ کلی", {"fields": ["priority", "live_status"]}),
        ("اولویتِ هر نوعِ کار (اختیاری)", {"fields": ["priority_text", "priority_research", "priority_code", "priority_vision"],
                                          "description": "خالی = مثلِ اولویتِ کلی."}),
        ("مدلِ لوکالِ هر نوعِ کار", {"fields": ["model_text", "model_research", "model_code", "model_vision"],
                                    "description": "خالی = پیش‌فرض (gemma3:12b ⇐ متنِ روزمره، qwq:32b ⇐ پژوهش، qwen3-coder:30b ⇐ کد، "
                                                   "qwen3-vl:30b ⇐ بینایی). در پنل از روی مدل‌هایی که سرورِ پردازش گزارش کرده انتخاب می‌شود "
                                                   "و دکمهٔ «دانلود مدل» هم همان‌جاست."}),
        ("پیشرفته", {"fields": ["breaker_minutes", "updated_at"], "classes": ["collapse"]}),
    ]
    list_display = ["__str__", "priority_text", "priority_research", "priority_code", "priority_vision", "updated_at"]
    actions = ["test_local", "test_metis"]

    def has_add_permission(self, request):
        try:
            return not AiPriority.objects.exists()
        except Exception:  # noqa: BLE001
            return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = AiPriority.get()
        return redirect(reverse("%s:ai_aipriority_change" % self.admin_site.name, args=[obj.pk]))

    @admin.display(description="وضعِ این لحظه")
    def live_status(self, obj):
        from services.ai import status

        try:
            snap = status.snapshot()
        except Exception as exc:  # noqa: BLE001
            return "نامعلوم: %s" % exc
        local, metis = snap["local"], snap["metis"]
        l_txt = ("آنلاین (%s)" % local["node"]) if local["online"] else (local["reason"] or "خاموش")
        if metis["last_error"]:
            m_txt = "آخرین خطا: %s" % metis["last_error"]["message"]
        elif metis["configured"]:
            m_txt = "تنظیم شده (%s)" % metis["host"]
        else:
            m_txt = "تنظیم نشده"
        return format_html("لوکال: <b>{}</b><br>متیس: <b>{}</b>", l_txt, m_txt)

    @admin.action(description="آزمونِ لوکال (یک درخواستِ کوچک)")
    def test_local(self, request, queryset):
        from services.ai import status

        res = status.run_test("local", "text")
        self.message_user(request, res["message"], messages.SUCCESS if res["ok"] else messages.ERROR)

    @admin.action(description="آزمونِ متیس (یک درخواستِ کوچک)")
    def test_metis(self, request, queryset):
        from services.ai import status

        res = status.run_test("metis", "text")
        self.message_user(request, res["message"], messages.SUCCESS if res["ok"] else messages.ERROR)


@admin.register(AiProviderState)
class AiProviderStateAdmin(admin.ModelAdmin):
    name_en = "AI path state"
    description = ("حافظهٔ کوتاهِ شکست‌ها: مسیری که به‌تازگی خراب بوده چند دقیقه کنار گذاشته می‌شود تا هر درخواست منتظرِ مهلتِ "
                   "سرویسِ مرده نماند. فقط‌خواندنی؛ برای آزاد کردنِ زودتر، ردیف را حذف کن.")
    list_display = ["key", "fail_kind", "fail_message", "last_ok_at", "last_fail_at", "open_until", "fails"]
    readonly_fields = [f.name for f in AiProviderState._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import ImportReport


@admin.register(ImportReport)
class ImportReportAdmin(admin.ModelAdmin):
    name_en = 'Studio import reports'
    description = 'گزارشِ واردکردنِ یک پروژهٔ جنگوی موجود به سایت‌ساز (چه شناخته شد، چه نشد).'
    list_display = ['project', 'level', 'created_at']

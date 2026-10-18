from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    name_en = "Jobs"
    description = (
        "هر کاری که سیستم در پس‌زمینه انجام می‌دهد یک ردیف اینجاست — تحلیل محصول، "
        "ساخت کپشن، رندر ویدیو. اگر کاربری می‌گوید «زده‌ام ولی هیچ اتفاقی نیفتاد»، "
        "جوابش در ستون وضعیت و خطای همین جدول است."
    )
    list_display = ["id", "type", "state", "store", "progress_step", "total_steps", "created_at"]
    list_filter = ["type", "state"]
    readonly_fields = ["created_at", "updated_at"]

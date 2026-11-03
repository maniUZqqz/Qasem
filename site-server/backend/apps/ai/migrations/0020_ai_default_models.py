# -*- coding: utf-8 -*-
"""نگاشتِ تازهٔ «نوعِ کار ⇒ مدلِ لوکال» را در تنظیم ذخیره می‌کند (۱۴۰۵/۰۸/۱۲)، مگر مالک دستی چیزی انتخاب کرده باشد.

    متنِ روزمره  ⇒ gemma3:12b        پژوهش و استدلال ⇒ qwq:32b
    کد           ⇒ qwen3-coder:30b   بینایی          ⇒ qwen3-vl:30b

فقط خانهٔ «خالی» پر می‌شود (خالی = مالک هیچ‌وقت انتخاب نکرده بود)؛ هر مقداری که مالک گذاشته باشد — حتی اگر با پیش‌فرض
یکی باشد — دست‌نخورده می‌ماند. ردیف نبود ⇒ ساخته می‌شود. برگشت: بی‌اثر (مقدارها همان پیش‌فرضِ کد هستند).
"""
from django.db import migrations

DEFAULTS = {
    "model_text": "gemma3:12b",
    "model_research": "qwq:32b",
    "model_code": "qwen3-coder:30b",
    "model_vision": "qwen3-vl:30b",
}


def forwards(apps, schema_editor):
    AiPriority = apps.get_model("ai", "AiPriority")
    row = AiPriority.objects.filter(pk=1).first()
    if row is None:
        from apps.ai.priority_models import _legacy_priority

        AiPriority.objects.create(pk=1, priority=_legacy_priority(), **DEFAULTS)
        return
    changed = []
    for field, value in DEFAULTS.items():
        if not (getattr(row, field, "") or "").strip():
            setattr(row, field, value)
            changed.append(field)
    if changed:
        row.save(update_fields=changed + ["updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0019_ai_priority_research"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

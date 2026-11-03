# -*- coding: utf-8 -*-
"""اولویتِ هوش مصنوعی (لوکال / متیس): تنظیمِ واحد، حالتِ مسیرها، و ثبتِ اینکه کدام مسیر جواب داد."""
import django.core.validators
from django.db import migrations, models


def seed_priority(apps, schema_editor):
    """تنظیمِ قدیمیِ `route_mode` ِ سایت‌ساز را به اولویتِ جدید می‌برد (qwen_first ⇒ اول لوکال، metis_only ⇒ اول متیس)."""
    from apps.ai.priority_models import _legacy_priority

    AiPriority = apps.get_model("ai", "AiPriority")
    AiPriority.objects.get_or_create(pk=1, defaults={"priority": _legacy_priority()})


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0017_seed_node_audio_engines"),
    ]

    operations = [
        migrations.AddField(
            model_name="airequest",
            name="via",
            field=models.CharField(blank=True, default="", max_length=8, verbose_name="جواب از (لوکال/متیس)"),
        ),
        migrations.AddField(
            model_name="airequest",
            name="fell_back",
            field=models.BooleanField(default=False, verbose_name="مسیرِ پشتیبان جواب داد"),
        ),
        migrations.AddField(
            model_name="airequest",
            name="fallback_reason",
            field=models.CharField(blank=True, default="", max_length=400, verbose_name="چرا مسیرِ اول نشد"),
        ),
        migrations.CreateModel(
            name="AiPriority",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("priority", models.CharField(
                    choices=[("local_first", "اول لوکال (سرورِ پردازش)، متیس پشتیبان"), ("metis_first", "اول متیس، لوکال پشتیبان")],
                    default="local_first", max_length=12, verbose_name="اولویتِ هوش مصنوعی",
                    help_text="اگر اولی در دسترس نبود (سرورِ پردازش خاموش، مدل نصب نیست، مهلت، اعتبارِ متیس تمام، قطعِ اتصال) "
                              "همان لحظه خودکار دومی جواب می‌دهد.")),
                ("priority_text", models.CharField(
                    blank=True, choices=[("", "مثلِ تنظیمِ کلی"), ("local_first", "اول لوکال (سرورِ پردازش)، متیس پشتیبان"), ("metis_first", "اول متیس، لوکال پشتیبان")],
                    default="", max_length=12, verbose_name="اولویتِ کارهای متن و استدلال", help_text="خالی = مثلِ تنظیمِ کلی")),
                ("priority_code", models.CharField(
                    blank=True, choices=[("", "مثلِ تنظیمِ کلی"), ("local_first", "اول لوکال (سرورِ پردازش)، متیس پشتیبان"), ("metis_first", "اول متیس، لوکال پشتیبان")],
                    default="", max_length=12, verbose_name="اولویتِ کارهای کد و سایت‌ساز", help_text="خالی = مثلِ تنظیمِ کلی")),
                ("priority_vision", models.CharField(
                    blank=True, choices=[("", "مثلِ تنظیمِ کلی"), ("local_first", "اول لوکال (سرورِ پردازش)، متیس پشتیبان"), ("metis_first", "اول متیس، لوکال پشتیبان")],
                    default="", max_length=12, verbose_name="اولویتِ کارهای بینایی (تصویر)", help_text="خالی = مثلِ تنظیمِ کلی")),
                ("model_text", models.CharField(
                    blank=True, default="", max_length=120, verbose_name="مدلِ لوکالِ متن و استدلال",
                    help_text="خالی = پیش‌فرض (MODEL_REASONING در .env، مثلاً qwq:32b)")),
                ("model_code", models.CharField(
                    blank=True, default="", max_length=120, verbose_name="مدلِ لوکالِ کد و سایت‌ساز",
                    help_text="خالی = پیش‌فرض (MODEL_CODER در .env، مثلاً qwen3-coder:30b)")),
                ("model_vision", models.CharField(
                    blank=True, default="", max_length=120, verbose_name="مدلِ لوکالِ بینایی",
                    help_text="خالی = پیش‌فرض (MODEL_VISION در .env، مثلاً qwen3-vl:30b)")),
                ("breaker_minutes", models.PositiveSmallIntegerField(
                    default=5, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(120)],
                    verbose_name="چند دقیقه یک مسیرِ خراب کنار بماند",
                    help_text="شکستِ تازه (مهلت، ۴۰۲، ۴۰۱، ۵xx، قطعِ اتصال) این‌قدر یادش می‌ماند تا هر درخواست منتظرِ مهلتِ سرویسِ مرده نماند.")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
            ],
            options={
                "verbose_name": "اولویتِ هوش مصنوعی (لوکال / متیس)",
                "verbose_name_plural": "اولویتِ هوش مصنوعی (لوکال / متیس)",
            },
        ),
        migrations.CreateModel(
            name="AiProviderState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=160, unique=True, verbose_name="مسیر")),
                ("last_ok_at", models.DateTimeField(blank=True, null=True, verbose_name="آخرین جوابِ موفق")),
                ("last_fail_at", models.DateTimeField(blank=True, null=True, verbose_name="آخرین شکست")),
                ("fail_kind", models.CharField(blank=True, default="", max_length=20, verbose_name="نوعِ آخرین شکست")),
                ("fail_message", models.CharField(blank=True, default="", max_length=500, verbose_name="پیامِ آخرین شکست")),
                ("fails", models.PositiveIntegerField(default=0, verbose_name="شمارِ شکست‌ها")),
                ("open_until", models.DateTimeField(blank=True, null=True, verbose_name="کنار گذاشته تا")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
            ],
            options={
                "verbose_name": "حالتِ مسیرِ هوش مصنوعی",
                "verbose_name_plural": "حالتِ مسیرهای هوش مصنوعی",
                "ordering": ["key"],
            },
        ),
        migrations.RunPython(seed_priority, migrations.RunPython.noop),
    ]

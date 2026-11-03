# -*- coding: utf-8 -*-
"""اولویتِ هوش مصنوعی: نوعِ کارِ «پژوهش و استدلالِ عمیق» جدا از «متنِ روزمره» (۱۴۰۵/۰۸/۱۲)."""
from django.db import migrations, models

ORDERS = [
    ("", "مثلِ تنظیمِ کلی"),
    ("local_first", "اول لوکال (سرورِ پردازش)، متیس پشتیبان"),
    ("metis_first", "اول متیس، لوکال پشتیبان"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0018_ai_priority"),
    ]

    operations = [
        migrations.AddField(
            model_name="aipriority",
            name="priority_research",
            field=models.CharField(blank=True, choices=ORDERS, default="", help_text="خالی = مثلِ تنظیمِ کلی",
                                   max_length=12, verbose_name="اولویتِ کارهای پژوهش و استدلالِ عمیق"),
        ),
        migrations.AddField(
            model_name="aipriority",
            name="model_research",
            field=models.CharField(blank=True, default="", help_text="خالی = پیش‌فرض (MODEL_REASONING در .env، مثلاً qwq:32b)",
                                   max_length=120, verbose_name="مدلِ لوکالِ پژوهش و استدلالِ عمیق"),
        ),
        migrations.AlterField(
            model_name="aipriority",
            name="priority_text",
            field=models.CharField(blank=True, choices=ORDERS, default="", help_text="خالی = مثلِ تنظیمِ کلی",
                                   max_length=12, verbose_name="اولویتِ کارهای متنِ روزمره"),
        ),
        migrations.AlterField(
            model_name="aipriority",
            name="model_text",
            field=models.CharField(blank=True, default="", help_text="خالی = پیش‌فرض (MODEL_TEXT در .env، وگرنه gemma3:12b)",
                                   max_length=120, verbose_name="مدلِ لوکالِ متنِ روزمره (محتوا، کپشن، چت)"),
        ),
    ]

# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_engine', '0004_route_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiproposal',
            name='answered_via',
            field=models.CharField(blank=True, default='', max_length=8, verbose_name='جواب از (لوکال/متیس)'),
        ),
        migrations.AlterField(
            model_name='aisettings',
            name='route_mode',
            field=models.CharField(choices=[('qwen_first', 'اول Qwen روی سرورِ پردازش؛ اگر نبود Metis'), ('metis_only', 'فقط Metis')],
                                   default='qwen_first', max_length=12, verbose_name='(منسوخ) کارهای متن و کد کجا انجام شوند'),
        ),
    ]

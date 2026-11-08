# «پردازشِ دوباره»: پیوندِ کارِ سرورِ پردازش به کارِ فروشگاه (apps.jobs Job) که آن را ساخت. فقط یک ستونِ تازهٔ خالی‌پذیر.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('compute', '0007_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='computejob',
            name='job_ref',
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True, verbose_name='کارِ فروشگاه'),
        ),
    ]

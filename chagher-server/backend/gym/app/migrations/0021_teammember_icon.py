from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0020_programsharecode'),
    ]

    operations = [
        migrations.AddField(
            model_name='teammember',
            name='icon',
            field=models.CharField(
                blank=True,
                help_text='آیکون Bootstrap Icons بدون پیشوند bi- (مثال: code-slash، clipboard-pulse، headset). '
                          'وقتی عکس آپلود نشده باشد، همین آیکون روی کارت تیم نمایش داده می‌شود.',
                max_length=50,
                null=True,
                verbose_name='نام آیکون',
            ),
        ),
    ]

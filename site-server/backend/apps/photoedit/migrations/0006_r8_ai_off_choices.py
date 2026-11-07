"""دورِ ۸: پیش‌فرضِ «کمکِ هوش مصنوعی» خاموش (و همهٔ فروشگاه‌های فعلی خاموش)، انتخابِ «ویرایش با دستور» وقتی گره خاموش است،
مدلِ پیش‌فرضِ حذفِ پس‌زمینه."""
from django.db import migrations, models


def ai_off(apps, schema_editor):
    apps.get_model("photoedit", "PhotoStoreSetting").objects.update(ai_assist=False)


class Migration(migrations.Migration):

    dependencies = [
        ("photoedit", "0005_r4_settings_batch"),
    ]

    operations = [
        migrations.AlterField(
            model_name="photostoresetting",
            name="ai_assist",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="photostoresetting",
            name="smart_offline",
            field=models.CharField(default="ask", max_length=8),
        ),
        migrations.AddField(
            model_name="photostoresetting",
            name="matting_model",
            field=models.CharField(default="rvm", max_length=16),
        ),
        migrations.RunPython(ai_off, migrations.RunPython.noop),
    ]

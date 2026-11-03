from django.db import migrations, models


class Migration(migrations.Migration):
    """افزودنیِ بی‌خطر: JSON ِ اصلیِ پروژه پیش از کوچِ «قاب‌اول» (fv=1 ⇐ fv=2) نگه داشته می‌شود."""

    dependencies = [
        ('photoedit', '0002_pro_projects_presets'),
    ]

    operations = [
        migrations.AddField(
            model_name='photoproject',
            name='legacy',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

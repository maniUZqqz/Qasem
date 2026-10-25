# -*- coding: utf-8 -*-
"""کدینگِ پیش‌فرض + سالِ مالیِ جاری + تنظیمات، و تریگرهای قفلِ سندِ قطعی."""
from django.db import migrations
from django.utils import timezone


def seed(apps, schema_editor):
    from accounting.seed import seed_all
    seed_all(apps.get_model('accounting', 'Account'),
             apps.get_model('accounting', 'FiscalYear'),
             apps.get_model('accounting', 'AccountingSettings'),
             timezone.localdate())


def add_triggers(apps, schema_editor):
    from accounting.db import ensure_triggers
    ensure_triggers(schema_editor.connection)


def remove_triggers(apps, schema_editor):
    from accounting.db import drop_triggers
    drop_triggers(schema_editor.connection)


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_triggers, remove_triggers),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]

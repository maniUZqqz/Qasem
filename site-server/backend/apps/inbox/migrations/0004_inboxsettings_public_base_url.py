from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0003_fix_test_data_and_demo_wording'),
    ]

    operations = [
        migrations.AddField(
            model_name='inboxsettings',
            name='public_base_url',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]

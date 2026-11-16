from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='inboxsettings',
            name='handoff_message',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
    ]

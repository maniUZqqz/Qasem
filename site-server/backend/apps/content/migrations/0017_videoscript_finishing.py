from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0016_videoscene_speaker_on_camera"),
    ]

    operations = [
        migrations.AddField(
            model_name="videoscript",
            name="finishing",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stores", "0001_initial"),
        ("content", "0018_videoproject"),
    ]

    operations = [
        migrations.CreateModel(
            name="DirectorDraft",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("run", models.CharField(db_index=True, max_length=16)),
                ("job_id", models.IntegerField(blank=True, null=True)),
                ("key", models.CharField(max_length=4)),
                ("title", models.CharField(blank=True, max_length=200)),
                ("score", models.PositiveSmallIntegerField(default=0)),
                ("length", models.FloatField(default=0)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("promoted_at", models.DateTimeField(blank=True, null=True)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="from_drafts", to="content.videoproject")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="director_drafts", to="stores.store")),
            ],
            options={"ordering": ["-created_at", "key"]},
        ),
    ]

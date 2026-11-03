import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stores", "0001_initial"),
        ("content", "0017_videoscript_finishing"),
    ]

    operations = [
        migrations.CreateModel(
            name="VideoProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(blank=True, max_length=200)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("state", models.CharField(choices=[("DRAFT", "پیش‌نویس"), ("RENDERING", "در حال رندر"), ("READY", "رندر شد"), ("FAILED", "خطا")], default="DRAFT", max_length=12)),
                ("output", models.FileField(blank=True, null=True, upload_to="generated/projects/")),
                ("render_info", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True)),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="video_projects", to="stores.store")),
            ],
            options={"ordering": ["-updated_at"]},
        ),
    ]

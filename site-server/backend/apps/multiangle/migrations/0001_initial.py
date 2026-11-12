import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("stores", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MultiAngleRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mode", models.CharField(choices=[("virtual", "زاویه‌های مجازی"), ("move25d", "حرکتِ دوربینِ ۲٫۵بعدی"), ("selftest", "آزمونِ خودکار")], default="virtual", max_length=10)),
                ("state", models.CharField(choices=[("QUEUED", "در صف"), ("RUNNING", "در حال ساخت"), ("INGEST", "آوردنِ نتیجه به سایت"), ("READY", "آماده"), ("FAILED", "ناموفق"), ("CANCELLED", "لغو شد")], default="QUEUED", max_length=10)),
                ("title", models.CharField(blank=True, max_length=200, verbose_name="عنوان")),
                ("source_ref", models.CharField(blank=True, max_length=40)),
                ("params", models.JSONField(blank=True, default=dict)),
                ("job_uid", models.CharField(blank=True, db_index=True, max_length=40)),
                ("progress", models.FloatField(default=0.0)),
                ("message", models.CharField(blank=True, max_length=300)),
                ("error", models.TextField(blank=True)),
                ("plan", models.JSONField(blank=True, default=dict)),
                ("files", models.JSONField(blank=True, default=dict)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("project_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("checks", models.JSONField(blank=True, default=list)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("store", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="multiangle_runs", to="stores.store")),
            ],
            options={
                "verbose_name": "اجرای چندزاویه",
                "verbose_name_plural": "اجراهای چندزاویه",
                "ordering": ["-created_at"],
            },
        ),
    ]

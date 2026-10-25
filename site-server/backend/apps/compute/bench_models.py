"""«تست» of a voice model on one processing node: what a standard short job cost (history, newest first)."""
from django.conf import settings
from django.db import models

from .models import ComputeNode


class AudioBenchmark(models.Model):
    class Model(models.TextChoices):
        SPEECH = "speech", "گفتار"
        CLONE = "clone", "کلونِ صدا"
        SFX = "sfx", "صدای محیط"
        MUSIC = "music", "موسیقی"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حالِ اجرا"
        DONE = "DONE", "انجام شد"
        FAILED = "FAILED", "ناموفق"

    node = models.ForeignKey(ComputeNode, on_delete=models.CASCADE, related_name="audio_benchmarks", verbose_name="سرور")
    model = models.CharField("مدل", max_length=8, choices=Model.choices)
    status = models.CharField("وضعیت", max_length=8, choices=Status.choices, default=Status.QUEUED)
    job_uid = models.UUIDField(null=True, blank=True)
    #: load_s, gen_s, audio_s, rtf, vram_peak_mb, vram_base_mb, vram_total_mb, ram_peak_used_mb, ram_total_mb,
    #: gpu_util_peak, gpu_util_avg, cold, gpu, agent
    result = models.JSONField(default=dict, blank=True)
    verdict = models.CharField("حکم", max_length=8, blank=True)
    error = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "تستِ مدلِ صدا"
        verbose_name_plural = "تست‌های مدل‌های صدا"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.node.name} · {self.get_model_display()} · {self.get_status_display()}"

"""«گزارشِ سرورهای پردازش»: دو جدولِ سبک که از روی heartbeat ِ گره‌ها پر می‌شوند.

  * ComputeNodeSession  — هر ردیف یک «نوبتِ وصل بودن» است: از اولین heartbeat تا آخرین heartbeat پیش از یک وقفهٔ
    بیش از ۹۰ ثانیه (همان تعریفِ «خاموش» در ComputeNode.online). روشن/خاموش بودنِ گره در بازه‌های گذشته
    (و درصدِ آنلاین بودن) از همین‌ها حساب می‌شود.
  * ComputeNodeSample   — نمونهٔ منابع (RAM، VRAM، دیسک، GPU) حداکثر دقیقه‌ای یک‌بار. نمونه‌های خام ۴۸ ساعت می‌مانند، بعد
    به میانگینِ ۱۵ دقیقه‌ای (kind="15m"، در همین جدول) تبدیل و خام‌ها پاک می‌شوند؛ هرچه از «نگه‌داریِ آمار»
    (ComputeSettings.retention_days) قدیمی‌تر است حذف می‌شود تا پایگاه داده کوچک بماند.

منطقِ نوشتن/نگه‌داری در report.py است؛ این‌جا فقط مدل‌ها.
"""
from django.db import models

from .models import ComputeNode


class ComputeNodeSession(models.Model):
    node = models.ForeignKey(ComputeNode, on_delete=models.CASCADE, related_name="sessions", verbose_name="سرور")
    started_at = models.DateTimeField("شروعِ اتصال")
    #: آخرین heartbeat ی که همین نوبت را ادامه داد
    last_beat = models.DateTimeField("آخرین تپش")
    #: خالی = هنوز وصل است (یا تا بستنِ بعدی)؛ هنگامِ بستن برابرِ last_beat می‌شود
    ended_at = models.DateTimeField("پایانِ اتصال", null=True, blank=True)
    agent = models.CharField("نسخهٔ نرم‌افزارِ سرور", max_length=20, blank=True)
    hostname = models.CharField("نامِ کامپیوتر", max_length=80, blank=True)
    gpu = models.CharField("کارتِ گرافیک", max_length=200, blank=True)

    class Meta:
        verbose_name = "نوبتِ اتصالِ سرورِ پردازش"
        verbose_name_plural = "نوبت‌های اتصالِ سرورهای پردازش"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["node", "started_at"], name="cmp_sess_node_start"),
            models.Index(fields=["node", "ended_at"], name="cmp_sess_node_open"),
            models.Index(fields=["ended_at", "last_beat"], name="cmp_sess_open"),
        ]

    def __str__(self):
        return f"{self.node.name} {self.started_at:%Y-%m-%d %H:%M}"


class ComputeNodeSample(models.Model):
    RAW = "raw"
    M15 = "15m"
    KINDS = [(RAW, "خام"), (M15, "میانگینِ ۱۵ دقیقه")]

    node = models.ForeignKey(ComputeNode, on_delete=models.CASCADE, related_name="samples", verbose_name="سرور")
    at = models.DateTimeField("زمان")
    kind = models.CharField("نوع", max_length=4, choices=KINDS, default=RAW)
    ram_free_mb = models.FloatField(null=True, blank=True)
    ram_total_mb = models.FloatField(null=True, blank=True)
    vram_used_mb = models.FloatField(null=True, blank=True)
    vram_total_mb = models.FloatField(null=True, blank=True)
    disk_free_gb = models.FloatField(null=True, blank=True)
    disk_total_gb = models.FloatField(null=True, blank=True)
    gpu_util_pct = models.FloatField(null=True, blank=True)
    gpu_temp_c = models.FloatField(null=True, blank=True)
    #: چند کار همان لحظه روی این گره در حالِ اجرا بود (در ردیفِ ۱۵ دقیقه‌ای: بیشینه)
    running_jobs = models.PositiveSmallIntegerField(default=0)
    #: {"comfyui": true, "ollama": false, ...} — کوچک و فقط درست/نادرست
    services = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "نمونهٔ منابعِ سرورِ پردازش"
        verbose_name_plural = "نمونه‌های منابعِ سرورهای پردازش"
        ordering = ["at"]
        indexes = [
            models.Index(fields=["node", "at"], name="cmp_samp_node_at"),
            models.Index(fields=["kind", "at"], name="cmp_samp_kind_at"),
        ]
        constraints = [
            # هر سطلِ ۱۵ دقیقه‌ای برای هر گره فقط یک ردیف دارد (دو پردازهٔ هم‌زمانِ نگه‌داری نمی‌توانند دوتا بسازند)
            models.UniqueConstraint(fields=["node", "at"], condition=models.Q(kind="15m"), name="cmp_samp_15m_uniq"),
        ]

    def __str__(self):
        return f"{self.node.name} {self.kind} {self.at:%Y-%m-%d %H:%M}"

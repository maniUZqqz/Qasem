# -*- coding: utf-8 -*-
"""تنظیمِ اولویتِ هوش مصنوعی (لوکال / متیس) و حافظهٔ کوتاهِ شکست‌ها.

یک ردیفِ واحد (pk=1) که هم در جنگو ادمین و هم در پنل ویرایش می‌شود. منطقش در `services/ai/priority.py` و
`services/ai/routing.py` است؛ این‌جا فقط داده.
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

ORDERS = [
    ("local_first", "اول لوکال (سرورِ پردازش)، متیس پشتیبان"),
    ("metis_first", "اول متیس، لوکال پشتیبان"),
]
OVERRIDES = [("", "مثلِ تنظیمِ کلی")] + ORDERS


def _legacy_priority() -> str:
    """تنظیمِ قدیمیِ سایت‌ساز (`ai_engine.AiSettings.route_mode`) را به اولویتِ جدید برمی‌گرداند.

    qwen_first ⇒ اول لوکال؛ metis_only ⇒ اول متیس (لوکال پشتیبان — «فقط» دیگر وجود ندارد).
    هر خطایی ⇒ پیش‌فرض (اول لوکال).
    """
    try:
        from django.db import connections

        conn = connections["studio"]
        with conn.cursor() as cur:
            cur.execute("SELECT route_mode FROM ai_engine_aisettings WHERE id = 1")
            row = cur.fetchone()
        if row and row[0] == "metis_only":
            return "metis_first"
    except Exception:  # noqa: BLE001 — جدولِ استودیو هنوز نیست / آزمون
        pass
    return "local_first"


class AiPriority(models.Model):
    """«اول متیس / اول لوکال» برای همهٔ کارهای هوش مصنوعیِ NM — ردیفِ واحد."""

    priority = models.CharField("اولویتِ هوش مصنوعی", max_length=12, choices=ORDERS, default="local_first",
                                help_text="اگر اولی در دسترس نبود (سرورِ پردازش خاموش، مدل نصب نیست، مهلت، اعتبارِ متیس تمام، قطعِ اتصال) "
                                          "همان لحظه خودکار دومی جواب می‌دهد.")
    priority_text = models.CharField("اولویتِ کارهای متنِ روزمره", max_length=12, choices=OVERRIDES, blank=True, default="",
                                     help_text="خالی = مثلِ تنظیمِ کلی")
    priority_research = models.CharField("اولویتِ کارهای پژوهش و استدلالِ عمیق", max_length=12, choices=OVERRIDES, blank=True,
                                         default="", help_text="خالی = مثلِ تنظیمِ کلی")
    priority_code = models.CharField("اولویتِ کارهای کد و سایت‌ساز", max_length=12, choices=OVERRIDES, blank=True, default="",
                                     help_text="خالی = مثلِ تنظیمِ کلی")
    priority_vision = models.CharField("اولویتِ کارهای بینایی (تصویر)", max_length=12, choices=OVERRIDES, blank=True, default="",
                                       help_text="خالی = مثلِ تنظیمِ کلی")
    model_text = models.CharField("مدلِ لوکالِ متنِ روزمره (محتوا، کپشن، چت)", max_length=120, blank=True, default="",
                                  help_text="خالی = پیش‌فرض (MODEL_TEXT در .env، وگرنه gemma3:12b)")
    model_research = models.CharField("مدلِ لوکالِ پژوهش و استدلالِ عمیق", max_length=120, blank=True, default="",
                                      help_text="خالی = پیش‌فرض (MODEL_REASONING در .env، مثلاً qwq:32b)")
    model_code = models.CharField("مدلِ لوکالِ کد و سایت‌ساز", max_length=120, blank=True, default="",
                                  help_text="خالی = پیش‌فرض (MODEL_CODER در .env، مثلاً qwen3-coder:30b)")
    model_vision = models.CharField("مدلِ لوکالِ بینایی", max_length=120, blank=True, default="",
                                    help_text="خالی = پیش‌فرض (MODEL_VISION در .env، مثلاً qwen3-vl:30b)")
    breaker_minutes = models.PositiveSmallIntegerField(
        "چند دقیقه یک مسیرِ خراب کنار بماند", default=5,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
        help_text="شکستِ تازه (مهلت، ۴۰۲، ۴۰۱، ۵xx، قطعِ اتصال) این‌قدر یادش می‌ماند تا هر درخواست منتظرِ مهلتِ سرویسِ مرده نماند.")
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "اولویتِ هوش مصنوعی (لوکال / متیس)"
        verbose_name_plural = "اولویتِ هوش مصنوعی (لوکال / متیس)"

    def __str__(self):
        return self.get_priority_display()

    @classmethod
    def get(cls):
        obj = cls.objects.filter(pk=1).first()
        if obj is not None:
            return obj
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"priority": _legacy_priority()})
        return obj


class AiProviderState(models.Model):
    """آخرین حالتِ هر مسیر: «local»، «local:<مدل>»، «metis». کلیدِ مدار (circuit breaker) بین پردازه‌ها."""

    key = models.CharField("مسیر", max_length=160, unique=True)
    last_ok_at = models.DateTimeField("آخرین جوابِ موفق", null=True, blank=True)
    last_fail_at = models.DateTimeField("آخرین شکست", null=True, blank=True)
    fail_kind = models.CharField("نوعِ آخرین شکست", max_length=20, blank=True, default="")
    fail_message = models.CharField("پیامِ آخرین شکست", max_length=500, blank=True, default="")
    fails = models.PositiveIntegerField("شمارِ شکست‌ها", default=0)
    open_until = models.DateTimeField("کنار گذاشته تا", null=True, blank=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "حالتِ مسیرِ هوش مصنوعی"
        verbose_name_plural = "حالتِ مسیرهای هوش مصنوعی"
        ordering = ["key"]

    def __str__(self):
        return self.key

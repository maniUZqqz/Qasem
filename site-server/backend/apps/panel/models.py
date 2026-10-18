"""دفترِ صفحه‌ها و قابلیت‌های پنل — از جنگو ادمین خاموش/روشن می‌شوند.

سه سطح: **دسته** (گروهِ منو مثلِ «فروشگاه»، «بازار») ⇐ **صفحه** (هر مسیرِ پنل مثلِ «محصولات»، «آمار»)
⇐ **قابلیت** (بخشی از یک صفحه مثلِ «کارتِ قدم‌های بعدی» یا زبانهٔ «ویدیو» در استودیوی محتوا).

تیکِ «فعال» را برداری، پنل همان را نشان نمی‌دهد: دسته از منو می‌رود، صفحه از منو و از مسیر
(با پیامِ «این صفحه فعلاً غیرفعال است»)، قابلیت از داخلِ صفحه. چیزی که در این جدول‌ها نباشد
فعال به حساب می‌آید (پیش‌فرضِ باز)، پس افزودنِ صفحهٔ تازه به پنل هیچ‌وقت چیزی را نمی‌بندد.
فهرستِ اولیه از `registry.py` می‌آید و بعد از هر migrate خودکار کامل می‌شود (ردیفِ موجود دست نمی‌خورد).
"""
from django.db import models


class PanelSection(models.Model):
    key = models.SlugField("کلید", max_length=40, unique=True)
    title = models.CharField("عنوان", max_length=80)
    order = models.PositiveSmallIntegerField("ترتیب", default=100)
    enabled = models.BooleanField("فعال", default=True)
    staff_only = models.BooleanField("فقط کارکنان", default=False)
    description = models.CharField("توضیح", max_length=300, blank=True)

    class Meta:
        verbose_name = "دستهٔ منوی پنل"
        verbose_name_plural = "دسته‌های منوی پنل"
        ordering = ["order", "key"]

    def __str__(self):
        return self.title


class PanelPage(models.Model):
    section = models.ForeignKey(PanelSection, on_delete=models.CASCADE, related_name="pages", verbose_name="دسته")
    key = models.SlugField("کلید", max_length=60, unique=True)
    title = models.CharField("عنوان", max_length=80)
    path = models.CharField("مسیر در پنل", max_length=120, blank=True,
                            help_text="الگوی مسیر، مثلاً /stores/:id/analytics")
    order = models.PositiveSmallIntegerField("ترتیب", default=100)
    enabled = models.BooleanField("فعال", default=True)
    staff_only = models.BooleanField("فقط کارکنان", default=False)
    description = models.CharField("توضیح", max_length=300, blank=True)

    class Meta:
        verbose_name = "صفحهٔ پنل"
        verbose_name_plural = "صفحه‌های پنل"
        ordering = ["section__order", "order", "key"]

    def __str__(self):
        return f"{self.section.title} ⇐ {self.title}"


class PanelFeature(models.Model):
    page = models.ForeignKey(PanelPage, on_delete=models.CASCADE, related_name="features", verbose_name="صفحه")
    key = models.SlugField("کلید", max_length=80, unique=True)
    title = models.CharField("عنوان", max_length=100)
    enabled = models.BooleanField("فعال", default=True)
    description = models.CharField("توضیح", max_length=300, blank=True)

    class Meta:
        verbose_name = "قابلیتِ صفحه"
        verbose_name_plural = "قابلیت‌های صفحه‌ها"
        ordering = ["page__section__order", "page__order", "key"]

    def __str__(self):
        return f"{self.page.title} ⇐ {self.title}"

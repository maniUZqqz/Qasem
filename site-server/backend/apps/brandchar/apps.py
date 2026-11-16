from django.apps import AppConfig


class BrandcharConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.brandchar"
    verbose_name = "شخصیتِ برند"

    def ready(self):                                   # سبک‌های برداری را به موتورِ ماسکوت می‌شناساند
        from .engine import figure

        figure.register()

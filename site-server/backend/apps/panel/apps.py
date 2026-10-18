from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _seed(sender, **kwargs):
    """بعد از هر migrate، صفحه‌های تازهٔ پنل به دفتر اضافه می‌شوند (ردیفِ موجود دست نمی‌خورد)."""
    if kwargs.get("using", "default") != "default":
        return
    from . import registry

    registry.seed()


class PanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.panel"
    verbose_name = "صفحه‌ها و قابلیت‌های پنل"

    def ready(self):
        post_migrate.connect(_seed, sender=self, dispatch_uid="panel_seed")

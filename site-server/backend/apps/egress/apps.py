from django.apps import AppConfig


class EgressConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.egress"
    label = "egress"
    verbose_name = "پراکسی و VPN"

    def ready(self):
        from . import signals  # noqa: F401  (a saved proxy / route makes every process re-read the table)

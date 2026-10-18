from django.apps import AppConfig


class CmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cms"
    verbose_name = "وبلاگ و محتوای سایت"

    def ready(self):
        # Saving anything the public site shows tells the site at once,
        # instead of leaving it up to two minutes behind (see signals.py).
        from . import signals

        signals.connect()

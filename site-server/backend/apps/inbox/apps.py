from django.apps import AppConfig


class InboxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inbox"
    verbose_name = "صندوق یکپارچه"

    def ready(self):
        from . import signals  # noqa: F401  (registers the receivers)
        try:  # list the inbox scopes and endpoints on the platform's API-key page (idempotent)
            from .views_dev import register_endpoint_docs

            register_endpoint_docs()
        except Exception:  # noqa: BLE001 - a docs nicety, never a reason to stop the app
            pass

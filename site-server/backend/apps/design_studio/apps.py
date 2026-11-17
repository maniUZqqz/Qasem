from django.apps import AppConfig


class DesignStudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.design_studio"
    verbose_name = "استودیوی طراحی"

    def ready(self):
        # هر راهِ پاک‌شدنِ سند (حتی زنجیره‌ای با پاک‌شدنِ فروشگاه یا از ادمین) فایل‌های خروجی‌اش را هم ببرد.
        from django.db import transaction
        from django.db.models.signals import post_delete

        from .models import DesignDoc

        def _cleanup(sender, instance, **kwargs):
            from . import services

            sid, did = instance.store_id, instance.pk
            transaction.on_commit(lambda: services.remove_doc_files(sid, did))

        post_delete.connect(_cleanup, sender=DesignDoc, dispatch_uid="design_studio_doc_files_cleanup")

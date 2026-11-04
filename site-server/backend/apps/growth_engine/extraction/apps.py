from django.apps import AppConfig


class GrowthExtractionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.growth_engine.extraction"
    label = "growth_extraction"
    verbose_name = "جذب مشتری ‹ استخراجِ اطلاعاتِ تماس"

    def ready(self):
        # wiring that needs no shared file: a dashboard block, and "extract after import" for CSV imports
        from apps.growth_engine.analytics import registry
        from apps.growth_engine.discovery.signals import discovery_job_finished

        from . import receivers
        from .services import dashboard

        registry.register("extraction", dashboard.block)
        discovery_job_finished.connect(receivers.on_discovery_job_finished, dispatch_uid="growth_extraction_after_import")

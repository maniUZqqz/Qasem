from django.apps import AppConfig


class GrowthComplianceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.growth_engine.compliance"
    label = "growth_compliance"
    verbose_name = "جذب مشتری ‹ رعایتِ قواعد"

    def ready(self):
        from apps.growth_engine.analytics import registry

        from .services import dashboard

        registry.register("compliance", dashboard.block)

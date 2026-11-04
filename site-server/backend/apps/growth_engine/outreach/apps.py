from django.apps import AppConfig


class GrowthOutreachConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.growth_engine.outreach"
    label = "growth_outreach"
    verbose_name = "جذب مشتری ‹ پیام‌رسانی"

    def ready(self):
        # wiring that needs no shared file: a dashboard block, and the daily cap counting our own send attempts
        from apps.growth_engine.analytics import registry
        from apps.growth_engine.compliance.services import limits as compliance_limits

        from .services import dashboard, limits

        registry.register("outreach", dashboard.block)
        compliance_limits.register_counter(limits.attempts_on)

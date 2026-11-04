from django.apps import AppConfig


def revoke_phone_queue(actor=None) -> None:
    """The emergency-stop hook: every SMS the phone has not sent yet is called back."""
    from .channels import sms

    sms.revoke_pending()


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

        from apps.growth_engine.compliance.services import settings as compliance_settings

        registry.register("outreach", dashboard.block)
        compliance_limits.register_counter(limits.attempts_on)
        # an emergency stop must also take back the SMS already waiting in the phone's queue
        compliance_settings.register_stop_hook(revoke_phone_queue)

from django.apps import AppConfig


class GrowthCrawlerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.growth_engine.crawler"
    label = "growth_crawler"
    verbose_name = "جذب مشتری ‹ مشتری‌یاب"

    def ready(self):
        # a block on the Growth dashboard, without touching the dashboard's own code
        from apps.growth_engine.analytics import registry

        from .services import dashboard

        registry.register("finder", dashboard.block)

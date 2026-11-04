from django.apps import AppConfig
from django.db.models.signals import post_migrate


class GrowthKnowledgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.growth_engine.knowledge"
    label = "growth_knowledge"
    verbose_name = "جذب مشتری ‹ دانشِ محصول و نویسندهٔ هوشمند"

    def ready(self):
        from .services import seed

        # the default knowledge and templates are in place after every migrate (never overwriting what was edited)
        post_migrate.connect(seed.seed_after_migrate, sender=self, dispatch_uid="growth_knowledge_seed")

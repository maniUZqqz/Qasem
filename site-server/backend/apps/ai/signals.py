"""Keep product embeddings fresh (only when EMBEDDINGS_ENABLED=true)."""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.products.models import Product
from services.ai import embeddings as embedding_service

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Product, dispatch_uid="ai_embed_product_on_save")
def schedule_product_embedding(sender, instance, **kwargs):
    if not embedding_service.is_enabled():
        return
    from .tasks import embed_product_task

    try:
        embed_product_task.delay(instance.id)
    except Exception as exc:  # broker down — search just falls back to keywords
        logger.warning("Could not queue embedding for product %s: %s", instance.id, exc)

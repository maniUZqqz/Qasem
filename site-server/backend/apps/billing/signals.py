"""A new store gets its free trial immediately.

The product promise is «دو هفته رایگان، بدون کارت بانکی», so the trial starts
when the store is created — not lazily on the first generation, which would
make the panel show an empty, alarming quota screen to a brand-new customer.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.stores.models import Store

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Store, dispatch_uid="billing_start_trial")
def start_trial(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import NoSubscription, billing_enabled, subscription_for

    if not billing_enabled():
        return
    try:
        sub = subscription_for(instance)
    except NoSubscription:
        # no trial plan configured yet (fresh install before seed_plans) —
        # the store still works, it just has to pick a plan first
        logger.info("No trial plan configured; store %s starts without one", instance.pk)
        return
    logger.info("Store %s started on %s until %s", instance.pk, sub.plan.slug, sub.period_end)

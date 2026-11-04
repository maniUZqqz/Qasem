"""The outreach block of the Growth Dashboard (``extra.outreach``): counts straight from the database."""
from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import limits

from ..models import Campaign, ItemStatus, OutreachItem


def block() -> dict:
    return {
        "sent_today": limits.sent_today(),
        "daily_cap": GrowthSettings.load().daily_cap,
        "campaigns_active": Campaign.objects.filter(status=Campaign.Status.ACTIVE).count(),
        "items_ready": OutreachItem.objects.filter(status=ItemStatus.READY).count(),
        "items_needs_manual": OutreachItem.objects.filter(status=ItemStatus.NEEDS_MANUAL).count(),
        "sent_total": OutreachItem.objects.filter(status__in=[ItemStatus.SENT, ItemStatus.MANUAL_SENT]).count(),
    }

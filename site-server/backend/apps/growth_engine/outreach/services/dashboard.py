"""The outreach block of the Growth Dashboard (``extra.outreach``): counts straight from the database."""
from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import limits

from django.db.models import Count

from ..models import Campaign, Channel, ItemStatus, OutreachItem


def block() -> dict:
    by_channel = {
        row["channel"]: row["n"]
        for row in OutreachItem.objects.filter(status__in=[ItemStatus.SENT, ItemStatus.MANUAL_SENT]).values("channel").annotate(n=Count("id"))
    }
    return {
        "sent_by_channel": [{"channel": c.value, "label": c.label, "sent": by_channel.get(c.value, 0)} for c in Channel],
        "handed_off": OutreachItem.objects.filter(status=ItemStatus.HANDED_OFF).count(),
        "sent_today": limits.sent_today(),
        "daily_cap": GrowthSettings.load().daily_cap,
        "campaigns_active": Campaign.objects.filter(status=Campaign.Status.ACTIVE).count(),
        "items_ready": OutreachItem.objects.filter(status=ItemStatus.READY).count(),
        "items_needs_manual": OutreachItem.objects.filter(status=ItemStatus.NEEDS_MANUAL).count(),
        "sent_total": OutreachItem.objects.filter(status__in=[ItemStatus.SENT, ItemStatus.MANUAL_SENT]).count(),
    }

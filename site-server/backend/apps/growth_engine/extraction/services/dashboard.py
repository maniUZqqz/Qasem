"""The extraction block of the Growth Dashboard (``extra.extraction``): counts straight from the database."""
from apps.growth_engine.leads.models import ContactPoint

from ..models import ExtractionJob, ExtractionRun


def block() -> dict:
    last = ExtractionJob.objects.first()
    return {
        "leads_extracted": ExtractionRun.objects.filter(status=ExtractionRun.Status.DONE).values("lead").distinct().count(),
        "runs_total": ExtractionRun.objects.filter(status__in=[ExtractionRun.Status.DONE, ExtractionRun.Status.FAILED]).count(),
        "contacts_found": ContactPoint.objects.filter(source_ref__startswith="extract:").count(),
        "last_job": None
        if last is None
        else {
            "id": last.pk, "status": last.status, "status_label": last.get_status_display(), "progress": last.progress,
            "total_items": last.total_items, "contacts_added": last.contacts_added, "queued_at": last.queued_at,
        },
    }

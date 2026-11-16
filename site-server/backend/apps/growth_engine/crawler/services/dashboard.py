"""The finder's block of the Growth dashboard (``extra.finder``): plain counts from the database, nothing estimated."""
from django.db.models import Count
from django.utils import timezone

from ..models import CrawlFinding, CrawlMission, CrawlRun, LeadReminder, OutreachDraft


def block() -> dict:
    last = CrawlRun.objects.select_related("mission").first()
    now = timezone.now()
    return {
        "missions": CrawlMission.objects.filter(is_archived=False).count(),
        "findings": CrawlFinding.objects.count(),
        "good_fits": CrawlFinding.objects.filter(level="high").count(),
        "running": CrawlRun.objects.filter(status__in=[CrawlRun.Status.QUEUED, CrawlRun.Status.RUNNING]).count(),
        "reminders_overdue": LeadReminder.objects.filter(done_at__isnull=True, due_at__lt=now).count(),
        "drafts_waiting": OutreachDraft.objects.filter(status__in=[OutreachDraft.Status.DRAFT, OutreachDraft.Status.APPROVED]).count(),
        "by_level": dict(CrawlFinding.objects.values_list("level").annotate(n=Count("id"))),
        "last_run": None if last is None else {"id": last.pk, "mission": last.mission.name, "status": last.status, "state_label": last.state_label, "created": last.created_count, "finished_at": last.finished_at},
    }

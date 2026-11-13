"""Queue the improved automatic edit for the videos a shop uploaded recently (run once after deploying; safe to run again).

    manage.py queue_autoedit_rerun                 every upload of the last 6 days that has a long talking track
    manage.py queue_autoedit_rerun --upload 22     just that one
    manage.py queue_autoedit_rerun --dry-run       only say what would be queued

The job is the director's «polish» run with `require_words`: if the processing server is off it PARKS itself in the durable queue
(`wait.node`) and starts by itself when the server comes online, so nothing is left for a person to click.  No cloud AI is used
(`use_ai: false`): the whole run is deterministic code plus the owner's own GPU server.  The result is an ordinary draft in the editor's drafts list.
Running it twice does not queue a video twice (a finished or waiting run of the same upload is skipped unless --force).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.content.models import UploadedVideo
from apps.content.tasks_director import director_task
from apps.content.views_autoedit import autoedit_payload
from apps.jobs.models import Job
from apps.jobs.services import dispatch_job


class Command(BaseCommand):
    help = "Queue the polish run of the automatic edit for recently uploaded talking videos."

    def add_arguments(self, parser):
        parser.add_argument("--upload", type=int, action="append", default=[], help="an upload id (repeatable); default: every recent one")
        parser.add_argument("--days", type=int, default=6)
        parser.add_argument("--min-seconds", type=float, default=20.0)
        parser.add_argument("--force", action="store_true", help="queue again even if a run of this upload already exists")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        rows = UploadedVideo.objects.select_related("store").filter(has_audio=True, duration__gte=opts["min_seconds"])
        rows = rows.filter(pk__in=opts["upload"]) if opts["upload"] else rows.filter(created_at__gte=timezone.now() - timedelta(days=opts["days"]))
        rows = rows.filter(state__in=[UploadedVideo.State.READY, UploadedVideo.State.EDITED]).order_by("id")
        queued = 0
        for upload in rows:
            earlier = Job.objects.filter(store=upload.store, type=Job.Type.VIDEO_EDIT, context__origin="autoedit-rerun", context__upload_id=upload.pk)
            earlier = earlier.exclude(state__in=[Job.State.FAILED, Job.State.CANCELLED])
            if earlier.exists() and not opts["force"]:
                self.stdout.write(f"upload {upload.pk} «{upload.title}»: already queued (job {earlier.first().pk}) - skipped")
                continue
            if opts["dry_run"]:
                self.stdout.write(f"upload {upload.pk} «{upload.title}» ({upload.duration:.0f}s, store {upload.store_id}): would be queued")
                continue
            job = Job.objects.create(store=upload.store, type=Job.Type.VIDEO_EDIT, context={
                "what": "director", "kind": "run", "origin": "autoedit-rerun", "upload_id": upload.pk})
            failed = dispatch_job(job, director_task, job.id, autoedit_payload(upload.pk, require_words=True))
            if failed is not None:
                self.stderr.write(f"upload {upload.pk}: the queue is not available - nothing was started")
                continue
            queued += 1
            self.stdout.write(f"upload {upload.pk} «{upload.title}»: queued as job {job.pk} (it waits for the processing server by itself)")
        self.stdout.write(f"done: {queued} queued")

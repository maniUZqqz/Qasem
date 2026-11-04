"""Signal receivers. Connected in ``AppConfig.ready``."""
import logging

from .services import runner
from .tasks import enqueue_extraction

logger = logging.getLogger(__name__)


def on_discovery_job_finished(sender, job, **kwargs):
    """"Extract after import": when a CSV import that asked for it completes, read the websites of its leads.

    Never lets a problem here break the import's own completion."""
    try:
        if job.status != "completed" or not (job.params or {}).get("extract_after"):
            return
        for extraction_job in runner.create_jobs(job.created_by, discovery_job_id=job.pk):
            enqueue_extraction(extraction_job.pk)
    except runner.JobRequestError as exc:
        logger.info("growth extraction after import %s: nothing to do (%s)", getattr(job, "pk", "?"), exc)
    except Exception:  # noqa: BLE001
        logger.exception("growth extraction after import %s failed to start", getattr(job, "pk", "?"))

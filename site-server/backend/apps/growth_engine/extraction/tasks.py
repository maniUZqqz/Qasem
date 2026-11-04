"""Celery tasks of the extraction module."""
from celery import shared_task


@shared_task(name="apps.growth_engine.extraction.tasks.run_extraction_job", ignore_result=True)
def run_extraction_job(job_id: int) -> str:
    """Run (or resume) one extraction job. Safe to enqueue twice: a finished job is left alone."""
    from .services import runner

    return runner.run_extraction(job_id)


def enqueue_extraction(job_id: int) -> None:
    """Queue a job once the surrounding transaction has committed (so the worker can see the row)."""
    from django.db import transaction

    from apps.growth_engine.core.dispatch import dispatch

    from .models import ExtractionJob

    def _send():
        dispatch(run_extraction_job, ExtractionJob, job_id)

    transaction.on_commit(_send)

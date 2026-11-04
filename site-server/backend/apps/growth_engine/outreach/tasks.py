"""Celery tasks of the outreach module (long work never runs inside a request)."""
from celery import shared_task


@shared_task(name="apps.growth_engine.outreach.tasks.run_prepare_job", ignore_result=True)
def run_prepare_job(job_id: int) -> str:
    """Read the contact pages of a campaign's items and store each form's dry run. Safe to enqueue twice."""
    from .services import preparing

    return preparing.run_prepare(job_id)


@shared_task(name="apps.growth_engine.outreach.tasks.run_send_job", ignore_result=True)
def run_send_job(job_id: int) -> str:
    """Submit a campaign's approved items, one by one, inside the caps. Safe to enqueue twice: a finished job is left alone,
    and an item can only be claimed once."""
    from .services import sending

    return sending.run_send(job_id)


def enqueue(job) -> None:
    """Queue a job once the surrounding transaction has committed (so the worker can see the row)."""
    from django.db import transaction

    from apps.growth_engine.core.dispatch import dispatch

    from .models import OutreachJob

    task = run_prepare_job if job.kind == OutreachJob.Kind.PREPARE else run_send_job
    job_id = job.pk

    def _send():
        dispatch(task, OutreachJob, job_id)

    transaction.on_commit(_send)

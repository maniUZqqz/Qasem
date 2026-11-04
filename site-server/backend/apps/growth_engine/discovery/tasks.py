"""Celery tasks of the discovery module."""
from celery import shared_task


@shared_task(name="apps.growth_engine.discovery.tasks.run_csv_import", ignore_result=True)
def run_csv_import(job_id: int) -> str:
    """Run (or resume) one CSV import job. Safe to enqueue twice: a finished job is left alone."""
    from .services import csv_import

    return csv_import.run_import(job_id)


def enqueue_import(job_id: int) -> None:
    """Queue a job once the surrounding transaction has committed (so the worker can see the row)."""
    from django.db import transaction

    from apps.growth_engine.core.dispatch import dispatch

    from .models import DiscoveryJob

    def _send():
        dispatch(run_csv_import, DiscoveryJob, job_id)

    transaction.on_commit(_send)

"""Celery task of the AI message writer. It runs on the ``ai`` queue (a model call can take minutes and must not hold up the send job)."""
from celery import shared_task


@shared_task(name="apps.growth_engine.knowledge.tasks.write_version", ignore_result=True, queue="ai")
def write_version(version_id: int) -> str:
    """Fill one ``generating`` version. Safe to run twice: a finished version is left alone."""
    from .services import writer

    version = writer.run(version_id)
    return version.status if version is not None else "missing"


def enqueue(version_id: int) -> None:
    """Queue the writer once the surrounding transaction has committed (so the worker can see the row)."""
    from django.db import transaction

    def _send():
        write_version.apply_async(args=[version_id])

    transaction.on_commit(_send)

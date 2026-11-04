"""Sending a Celery task for a background job."""
from __future__ import annotations

import uuid


def dispatch(task, model, job_id: int) -> str:
    """Queue ``task(job_id)`` and remember its Celery id on the job row.

    The id is written BEFORE the message is sent: writing it after ``.delay()`` raced the worker's first transaction on
    SQLite (the web process committed an UPDATE a few milliseconds after the worker started, which made the worker's first
    write fail with «database is locked»)."""
    task_id = uuid.uuid4().hex
    model.objects.filter(pk=job_id).update(celery_task_id=task_id)
    task.apply_async(args=[job_id], task_id=task_id)
    return task_id

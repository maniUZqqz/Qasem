from celery import shared_task


@shared_task(name="apps.igtrends.tasks.auto_scan")
def auto_scan():
    """Every half hour: one small scan per store that wants it, when the node is READY (signed in, line open). Otherwise nothing."""
    from . import dispatch
    return dispatch.auto_scan_all()


@shared_task(name="apps.igtrends.tasks.sync")
def sync():
    """Every ten minutes: take in finished scans the finish hook missed, forget old readings."""
    from . import dispatch, ingest
    return {"synced": dispatch.sync_runs(), "pruned": ingest.prune_snapshots()}

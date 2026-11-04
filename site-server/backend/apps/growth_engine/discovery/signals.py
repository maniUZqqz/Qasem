"""Signals other modules can listen to without discovery knowing about them."""
from django.dispatch import Signal

#: sent when an import job ends (any final status): ``sender=DiscoveryJob, job=<DiscoveryJob>``
discovery_job_finished = Signal()

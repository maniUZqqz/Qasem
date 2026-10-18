import sys

from django.apps import AppConfig
from django.core.signals import request_started

# management commands that must never touch job rows (the table may not even
# exist yet) — reaping is only meaningful when the server actually serves
_NON_SERVER_COMMANDS = {
    "migrate",
    "makemigrations",
    "collectstatic",
    "test",
    "shell",
    "createsuperuser",
    "showmigrations",
    "loaddata",
    "dumpdata",
}


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.jobs"
    label = "jobs"
    verbose_name = "کارها و صف پردازش"

    def ready(self):
        """Arm a one-shot cleanup of jobs orphaned by a previous process.

        In synchronous mode a QUEUED/RUNNING row can only be alive while the
        request that owns it is running, so anything left over from an earlier
        process is dead and would otherwise show an eternal spinner
        (beter.md v2 #1/#2). The DB is touched on the first request, never
        during app initialisation.
        """
        if len(sys.argv) > 1 and sys.argv[1] in _NON_SERVER_COMMANDS:
            return

        state = {"done": False}

        def _reap_once(**_kwargs):
            if state["done"]:
                return
            state["done"] = True
            request_started.disconnect(_reap_once, dispatch_uid="jobs.reap_on_start")
            from . import staleness

            staleness.reap_on_start()

        request_started.connect(_reap_once, weak=False, dispatch_uid="jobs.reap_on_start")

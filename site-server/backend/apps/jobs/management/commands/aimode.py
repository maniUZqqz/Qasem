"""`python manage.py aimode` — what the launcher needs to start.

start.bat needs to know whether this machine has to launch Ollama and ComfyUI
at all. Parsing .env from batch is fragile (carets, quoting, empty values), and
worse, it would be a *second* place that decides the mode — free to drift from
what Django actually does.

So the launcher asks Django instead. One source of truth: settings +
services.ai.providers.

Two forms, both bare output because the launcher captures stdout:

    aimode            → `api` or `local`  (overall, kept for older scripts)
    aimode --needs    → `ollama comfyui`, `ollama`, `comfyui`, or `none`
"""
from django.core.management.base import BaseCommand

from services.ai import providers


class Command(BaseCommand):
    help = "چاپ حالت هوش مصنوعی برای start.bat"

    def add_arguments(self, parser):
        parser.add_argument(
            "--needs", action="store_true",
            help="موتورهای محلی لازم را چاپ کن، نه فقط api/local",
        )

    def handle(self, *args, **options):
        if options["needs"]:
            # Sorted so the launcher's string comparisons are stable.
            needed = sorted(providers.local_services_needed())
            self.stdout.write(" ".join(needed) if needed else "none", ending="")
            return

        # Overall mode: "api" only when NOTHING local is required. A machine
        # that sends text to an API but still renders video here is not in
        # "api" mode from the launcher's point of view — it still needs a GPU.
        any_local = bool(providers.local_services_needed())
        self.stdout.write("local" if any_local else "api", ending="")

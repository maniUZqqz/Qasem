"""خودآزمونِ بی‌گره: ``python manage.py design_selftest`` (خروجی ۰ = قبول)."""
import sys

from django.core.management.base import BaseCommand

from apps.design_studio import selftest


class Command(BaseCommand):
    help = "چیدمان، PDF چاپی، PPTX، فریم‌های UI و نگهبانِ عدد را بی‌گره می‌آزماید"

    def handle(self, *args, **opts):
        res = selftest.run_offline()
        for c in res["checks"]:
            self.stdout.write(("✓ " if c["ok"] else "✗ ") + f"{c['key']}: {c['detail']}")
        if not res["ok"]:
            sys.exit(1)

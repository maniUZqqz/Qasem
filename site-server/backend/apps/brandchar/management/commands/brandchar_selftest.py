import sys

from django.core.management.base import BaseCommand

from apps.brandchar import selftest


class Command(BaseCommand):
    help = "خودآزمونِ شخصیتِ برند: هر چهار سبک × ژست‌های نمونه × چهار اندازه (کدِ خروج ۱ اگر چیزی رد شد)"

    def handle(self, *args, **opts):
        res = selftest.run_engine()
        self.stdout.write("%d/%d تصویر قبول (%ss)" % (res["passed"], res["total"], res["seconds"]))
        for f in res["failed"][:20]:
            self.stdout.write("  رد: %s / %s / %s: %s" % (f["style"], f["pose"], f["size"], "؛ ".join(f["notes"])))
        if not res["ok"]:
            sys.exit(1)

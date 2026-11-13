from django.core.management.base import BaseCommand, CommandError

from apps.motion import buildlib


class Command(BaseCommand):
    help = "استودیوی موشن: ابزار، فونت‌ها، بستهٔ رندر، پخش‌کننده، مرورگرِ سایت و بستهٔ گرهٔ ویندوزی را می‌سازد (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--only", nargs="+", choices=buildlib.ORDER, help="فقط این مرحله‌ها")
        parser.add_argument("--skip", nargs="+", choices=buildlib.ORDER, help="این مرحله‌ها را نساز")

    def handle(self, *args, **opts):
        failures = buildlib.build(opts.get("only"), opts.get("skip"))
        if failures:
            raise CommandError(f"{failures} مرحله ناموفق بود")
        self.stdout.write(self.style.SUCCESS("motion_build: همه چیز آماده است"))

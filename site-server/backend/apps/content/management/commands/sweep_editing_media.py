"""Remove what deleted videos left behind in the editor's folders (the daily job does the same).

    python manage.py sweep_editing_media --dry-run      # only say what would go
    python manage.py sweep_editing_media                # remove: a work folder with no video older than 3 days,
                                                        #         an uploaded file no row points at older than 7 days
"""
from django.core.management.base import BaseCommand

from apps.content import media_cleanup


class Command(BaseCommand):
    help = "پوشهٔ کاریِ ویدیوهای پاک‌شده و فایل‌های آپلودیِ بی‌صاحب را (فقط قدیمی‌ها) پاک می‌کند."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط بگو چه چیزی پاک می‌شد")
        parser.add_argument("--work-days", type=float, default=media_cleanup.ORPHAN_WORK_DAYS)
        parser.add_argument("--upload-days", type=float, default=media_cleanup.ORPHAN_UPLOAD_DAYS)

    def handle(self, *args, **opts):
        report = media_cleanup.sweep_orphans(dry_run=opts["dry_run"], work_days=opts["work_days"], upload_days=opts["upload_days"])
        verb = "پاک می‌شد" if opts["dry_run"] else "پاک شد"
        for item in report["removed"]:
            self.stdout.write(f"{verb}: {item}")
        for item in report["kept"]:
            self.stdout.write(f"مانده: {item}")
        self.stdout.write(f"جمع: {len(report['removed'])} مورد، {report['bytes'] / 1e6:.1f} مگابایت")

"""همهٔ پروژه‌های ادیتورِ عکس را به مدلِ «قاب‌اول» (fv=2) کوچ می‌دهد.

    manage.py photoedit_migrate_frames --dry-run     # فقط گزارش؛ نه داده می‌نویسد نه ماسک
    manage.py photoedit_migrate_frames               # کوچِ واقعی (هر پروژه: rev+۱، اصل در legacy، ماسک‌ها v1-mask-<id>.png)

کوچ ایدمپوتنت است (پروژهٔ fv=2 دست نمی‌خورد) و همین کار هنگامِ بازکردنِ پروژه هم «تنبل» انجام می‌شود.
"""
from django.core.management.base import BaseCommand

from apps.photoedit import frames, services
from apps.photoedit.models import PhotoProject


class Command(BaseCommand):
    help = "کوچِ پروژه‌های ادیتورِ عکس به مدلِ قاب‌اول (fv=2)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش بده، چیزی ننویس")

    def handle(self, *args, **opts):
        dry = bool(opts.get("dry_run"))
        total = already = migrated = trivial = failed = masks = layers = 0
        for p in PhotoProject.objects.select_related("asset", "store").order_by("pk"):
            total += 1
            data = p.data if isinstance(p.data, dict) else {}
            if frames._fv(data) >= frames.FV:
                already += 1
                continue
            if dry:
                a = p.asset
                new, rep = frames.migrate_v1_to_v2(data, a.width, a.height, services.project_dir(p),
                                                   asset_path=services.abs_path(a.original) if a.original else None,
                                                   write_masks=False)
            else:
                _p, rep = services.ensure_frame_v2(p)
                if rep is None:      # هم‌زمان کسی کوچ داده بود
                    already += 1
                    continue
            if rep["stamped"]:
                migrated += 1
                trivial += 1 if rep["trivial"] else 0
                masks += rep["masks"]
                layers += rep["layers"]
                kind = "بی‌اثر" if rep["trivial"] else f"{rep['layers']} لایه، {rep['masks']} ماسک"
                self.stdout.write(f"  پروژهٔ {p.pk} (عکس {p.asset_id}): {'می‌شود' if dry else 'کوچ شد'} — {kind}")
                for n in rep["notes"]:
                    self.stdout.write(f"      · {n}")
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  پروژهٔ {p.pk} (عکس {p.asset_id}): کوچ نشد — {rep['error'] or rep['notes']}"))
        self.stdout.write(f"SUMMARY dry_run={int(dry)} total={total} already={already} migrated={migrated} trivial={trivial} "
                          f"failed={failed} layers={layers} masks={masks}")
        verb = "کوچ می‌شود" if dry else "کوچ شد"
        self.stdout.write(self.style.SUCCESS(
            f"{'[dry-run] ' if dry else ''}کل: {total} — از قبل fv=2: {already} — {verb}: {migrated} "
            f"(قابِ بی‌اثر: {trivial}، لایه‌ها: {layers}، ماسک‌های رنگ‌آمیزی: {masks}) — ناموفق: {failed}"))

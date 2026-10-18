"""Join a showcase item's five-second segments into one video.

The pipeline renders in five-second shots because that is what the video model
produces in one pass, and the last frame of each shot is the first frame of the
next — so they are already one continuous take, cut into files.

The site used to render them as five `<video>` tags side by side, all playing
at once. That shows a visitor our rendering architecture instead of our work,
and it is the single least convincing thing on a page whose only job is being
convincing. It also loads five files to play five seconds each.

So: stitch them, store the result on the item, and let the site play one video.

    python manage.py stitch_showcase              # every item that needs it
    python manage.py stitch_showcase --slug decor
    python manage.py stitch_showcase --force      # re-stitch even if a video exists

Needs ffmpeg. Without it the command says so and changes nothing — an item
keeps its segments and can be stitched later, which is better than leaving half
a file on disk.
"""
import tempfile
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from apps.cms.models import ShowcaseItem
from services.video.ffmpeg import VideoProcessingError, concat_videos


class Command(BaseCommand):
    help = "قطعه‌های ۵ ثانیه‌ای نمونه‌کارها را به هم می‌چسباند و یک ویدیو می‌سازد"

    def add_arguments(self, parser):
        parser.add_argument("--slug", help="فقط همین نمونه‌کار")
        parser.add_argument(
            "--force",
            action="store_true",
            help="حتی اگر ویدیوی چسبانده‌شده دارد، دوباره بساز",
        )

    def handle(self, *args, **options):
        rows = ShowcaseItem.objects.prefetch_related("segments")
        if options["slug"]:
            rows = rows.filter(slug=options["slug"])

        done = skipped = 0
        for item in rows:
            segments = list(item.segments.all())
            if len(segments) < 2:
                continue
            if item.video and not options["force"]:
                self.stdout.write(f"  - {item.slug}: ویدیو دارد (--force برای بازسازی)")
                skipped += 1
                continue

            paths = [Path(s.clip.path) for s in segments if s.clip]
            missing = [p for p in paths if not p.exists()]
            if missing:
                self.stderr.write(
                    self.style.WARNING(
                        f"  ! {item.slug}: {len(missing)} قطعه روی دیسک نیست — رد شد"
                    )
                )
                skipped += 1
                continue

            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / f"{item.slug}.mp4"
                try:
                    concat_videos(paths, out)
                except VideoProcessingError as exc:
                    self.stderr.write(self.style.ERROR(f"  ! {item.slug}: {exc}"))
                    skipped += 1
                    continue
                with out.open("rb") as fh:
                    # save=True writes the row; the old file is left on disk on
                    # purpose, because a botched stitch should be recoverable.
                    item.video.save(f"{item.slug}.mp4", File(fh), save=True)

            seconds = len(segments) * 5
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ {item.slug}: {len(segments)} قطعه → یک ویدیوی ~{seconds} ثانیه‌ای"
                )
            )
            done += 1

        self.stdout.write(f"\nچسبانده شد: {done} · رد شد: {skipped}")

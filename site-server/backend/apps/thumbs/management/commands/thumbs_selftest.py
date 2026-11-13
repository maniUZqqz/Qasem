"""خودآزمونِ «پس‌زمینهٔ هوش مصنوعی» روی سرورِ پردازش.

    python manage.py thumbs_selftest              # کار را در صفِ ماندگار می‌گذارد (اگر کارِ بازی نیست) و وضعیتِ آخرین کار را می‌گوید
    python manage.py thumbs_selftest --wait 900   # تا ۹۰۰ ثانیه منتظرِ نتیجه می‌ماند (خروجی ۰ = قبول، ۱ = رد یا بی‌پاسخ)؛ بدونِ --wait فقط ثبت می‌کند و وضعیت را می‌گوید (۰)

وقتی گره روشن شد کار را خودش برمی‌دارد؛ نتیجه با ``apps.thumbs.selftest.check`` سنجیده می‌شود (شرطِ قبولی: docs/selftests/thumbnails.md).
"""
import time

from django.core.management.base import BaseCommand, CommandError

from apps.compute.models import ComputeJob
from apps.thumbs import selftest


class Command(BaseCommand):
    help = "خودآزمونِ پس‌زمینهٔ هوش مصنوعیِ تامنیل‌ساز (FLUX روی سرورِ پردازش)."

    def add_arguments(self, parser):
        parser.add_argument("--wait", type=int, default=0, help="ثانیه‌های انتظار برای نتیجه")
        parser.add_argument("--no-enqueue", action="store_true", help="کارِ تازه نگذار؛ فقط آخرین نتیجه را بسنج")

    def handle(self, *args, **o):
        job = selftest.latest()
        active = (ComputeJob.State.QUEUED, ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING)
        if not o["no_enqueue"] and (job is None or job.state not in active):
            try:
                job = selftest.enqueue()
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"کار در صف نرفت: {exc}") from exc
            self.stdout.write(f"کارِ خودآزمون در صف گذاشته شد ({job.uid}).")
        if job is None:
            raise CommandError("هنوز خودآزمونی اجرا نشده است.")
        deadline = time.time() + max(0, o["wait"])
        while True:
            job.refresh_from_db()
            if job.state not in active or time.time() >= deadline:
                break
            time.sleep(5)
        if job.state in active:
            self.stdout.write(f"هنوز تمام نشده ({job.state}): {job.message}")
            if o["wait"] > 0:
                raise SystemExit(1)            # منتظر ماندیم و جواب نیامد
            return                             # فقط ثبت یا گزارشِ وضعیت: «در انتظار» شکست نیست
        ok, msg = selftest.check(job)
        self.stdout.write(("قبول: " if ok else "رد: ") + msg)
        if not ok:
            raise SystemExit(1)

"""گرهٔ پردازشِ ساختگی برای آزمونِ «پیش‌نمایشِ دقیق» و «انتخابِ سوژه» در مرورگر (بی GPU).

    manage.py photoedit_fake_node online              گرهٔ «gpu-fake» را برای ~۹۰ ثانیه آنلاین می‌کند (با تکرارِ همین فرمان تمدید می‌شود)
    manage.py photoedit_fake_node finish [--factor 1.2] [--job UID]
                                                      کارِ صفِ photoexact/photosubject را (قدیمی‌ترین یا UID) با خروجیِ ساختگی تمام می‌کند
    manage.py photoedit_fake_node offline             گره را حذف می‌کند (کارهای نیمه‌کاره می‌مانند)

فقط کارهای origin = photoexact / photosubject را برمی‌دارد؛ کارِ واقعیِ هیچ کاربری را نه.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.compute.models import ComputeJob, ComputeNode
from apps.photoedit import services

ORIGINS = ("photoexact", "photosubject", "photogenfill")


class Command(BaseCommand):
    help = "گرهٔ پردازشِ ساختگی برای آزمونِ ادیتورِ عکس (online | finish | offline)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["online", "finish", "offline"])
        parser.add_argument("--name", default="gpu-fake")
        parser.add_argument("--factor", type=float, default=1.2, help="روشن‌کردنِ عکس (فقط exact)")
        parser.add_argument("--job", default="", help="UID ِ کار؛ خالی = قدیمی‌ترین کارِ در صف")
        parser.add_argument("--comfy", action="store_true",
                            help="گره ComfyUI (چک‌پوینتِ FLUX dev) هم داشته باشد — برای «پرکردنِ هوشمند» (photogenfill)")

    def handle(self, *args, **opt):
        name = opt["name"]
        if opt["action"] == "offline":
            n, _ = ComputeNode.objects.filter(name=name).delete()
            self.stdout.write(f"deleted {n} node(s)")
            return
        if opt["action"] == "online":
            node, _ = ComputeNode.objects.get_or_create(name=name, defaults={"capabilities": {"photo": True}})
        else:
            node = ComputeNode.objects.filter(name=name).first()
            if node is None:
                raise CommandError("گرهٔ ساختگی نیست؛ اول «online» را بزنید.")
        node.enabled, node.last_seen = True, timezone.now()
        node.capabilities = (node.capabilities or {}) | {"photo": True}
        if opt["comfy"]:
            node.capabilities = node.capabilities | services.genfill_fake_caps()
        node.save()
        if opt["action"] == "online":
            self.stdout.write(f"node {name} online until {timezone.now() + timedelta(seconds=90):%H:%M:%S}")
            return
        qs = ComputeJob.objects.filter(origin__in=ORIGINS, state=ComputeJob.State.QUEUED).order_by("created_at")
        if opt["job"]:
            qs = qs.filter(uid=opt["job"])
        job = qs.first()
        if job is None:
            raise CommandError("کارِ در صفِ photoexact/photosubject نیست.")
        if job.origin == "photogenfill":
            done = services.genfill_finish_for_test(job, node)
        else:
            done = services.exact_finish_for_test(job, node, factor=opt["factor"])
        self.stdout.write(f"finished {done.uid} ({done.origin}) -> {done.state}")

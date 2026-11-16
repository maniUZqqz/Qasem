"""ساختِ سه پیش‌نویسِ «چغر» در استودیوی طراحی (کاتالوگ، ارائهٔ کوتاه، طرحِ صفحهٔ فرود) و فرستادنِ طرحِ UI به سایت‌ساز به‌صورتِ پیش‌نویس.

    python manage.py design_chagher_drafts [--store 34] [--no-site]

بی‌خطر و تکرارپذیر: اگر پیش‌نویس‌ها هست چیزی بازنویسی نمی‌شود؛ هیچ‌چیز منتشر نمی‌شود. فروشگاهِ چغر پیش‌فرض: نامی که «چغر» دارد.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.design_studio import chagher
from apps.stores.models import Store


class Command(BaseCommand):
    help = "پیش‌نویسِ کاتالوگ، ارائه و طرحِ UI ِ چغر (فقط از دادهٔ واقعیِ ثبت‌شده)"

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, default=0, help="شناسهٔ فروشگاه (پیش‌فرض: فروشگاهی که نامش «چغر» دارد)")
        parser.add_argument("--no-site", action="store_true", help="طرحِ UI را به سایت‌ساز نفرست")

    def handle(self, *args, **opts):
        qs = Store.objects.filter(pk=opts["store"]) if opts["store"] else Store.objects.filter(name__contains="چغر")
        store = qs.order_by("pk").first()
        if store is None:
            raise CommandError("فروشگاهِ چغر پیدا نشد.")
        out = chagher.ensure_drafts(store, None, send_to_site=not opts["no_site"])
        self.stdout.write(json.dumps(out, ensure_ascii=False, indent=1))

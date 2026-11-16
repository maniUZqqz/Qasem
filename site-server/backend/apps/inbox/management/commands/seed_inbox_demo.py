"""`manage.py seed_inbox_demo --store 34` - a draft inbox setup with marked test conversations.

Sends nothing and switches nothing on: see `apps.inbox.demo` for exactly what it writes.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.stores.models import Store


class Command(BaseCommand):
    help = "پیش‌نویسِ تنظیمات صندوق پیام + گفتگوهای آزمایشیِ علامت‌دار برای یک فروشگاه (بدون هیچ ارسالی)."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, required=True, help="شناسهٔ فروشگاه (چغر = ۳۴)")

    def handle(self, *args, **options):
        from apps.inbox import demo

        store = Store.objects.filter(pk=options["store"]).select_related("owner").first()
        if store is None:
            raise CommandError("فروشگاهی با این شناسه نیست.")
        made = demo.seed(store, owner=store.owner)
        self.stdout.write(self.style.SUCCESS(
            f"فروشگاه «{store.name}»: {made['conversations']} گفتگوی آزمایشی، {made['contacts']} مخاطب، "
            f"{made['canned']} پاسخ آماده ساخته شد. هیچ کانالی روشن نشد و چیزی فرستاده نشد."
        ))

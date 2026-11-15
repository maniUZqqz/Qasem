"""نمونهٔ «چغر». ``manage.py ideabank_demo [--store 34] [--ai] [--save] [--count 8]``

ایده‌هایی می‌سازد که فقط از واقعیت‌های ``docs/chagher/brand-facts-fa.md`` (شعار، «پیش‌نویسِ برنامه در کمتر از یک دقیقه»، لحنِ برند) و پروفایلِ فروشگاه
استفاده می‌کنند؛ هیچ قیمت یا آماری ندارند. بدونِ ``--save`` چیزی در پایگاه‌داده نوشته نمی‌شود. بدونِ ``--ai`` فقط فرمول‌ها (همیشه کار می‌کنند).
"""
from django.core.management.base import BaseCommand

from apps.ideabank import demo


class Command(BaseCommand):
    help = "ایده‌های نمونه برای چغر از روی واقعیت‌های برند"

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, default=0, help="شناسهٔ فروشگاه (پیش‌فرض: فروشگاهِ ساختگیِ چغر بدونِ دیتابیس)")
        parser.add_argument("--ai", action="store_true", help="اول هوش مصنوعی را امتحان کن")
        parser.add_argument("--save", action="store_true", help="ایده‌ها را در بانکِ فروشگاه ذخیره کن (نیازِ --store)")
        parser.add_argument("--count", type=int, default=8)

    def handle(self, *args, **opts):
        store = None
        if opts["store"]:
            from apps.stores.models import Store

            store = Store.objects.filter(pk=opts["store"]).first()
            if store is None:
                self.stderr.write(f"فروشگاهِ {opts['store']} پیدا نشد.")
                raise SystemExit(2)
        res = demo.run(store, count=opts["count"], use_ai=opts["ai"], save=opts["save"])
        self.stdout.write(f"via={res['via']} · {res['message']}")
        for i in res["ideas"]:
            e = i if "filled" in i else None
            title = e["filled"]["title"] if e else i["title"]
            self.stdout.write(f"- [{i['category']}/{i['format']}] {title}")
            self.stdout.write(f"    قلاب: {(e['filled']['hook'] if e else i['hook'])}")
        if opts["save"]:
            self.stdout.write(f"ذخیره شد: {res.get('saved', 0)} · تکراری/رد: {res.get('skipped', 0)}")

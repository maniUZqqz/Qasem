# -*- coding: utf-8 -*-
"""نمونهٔ زنده با محصولِ مالک («چغر»، فروشگاهِ ۳۴): از یک صفحهٔ فرودِ واقعی عکس می‌گیرد، تبدیل می‌کند و **پیش‌نویسِ** صفحه را در سایت‌ساز (و، اگر استودیوی طراحی روشن است، یک سندِ UI) می‌سازد.

    cd backend && ../venv/bin/python manage.py img2code_demo --store 34 --url https://chagher.ir/ [--user <نامِ کاربریِ کارمند>] [--mode responsive|exact] [--no-ui]

چیزی منتشر نمی‌شود؛ فقط یک ردیفِ «تاریخچهٔ تبدیل»، یک پروژهٔ پیش‌نویسِ سایت‌ساز و یک سندِ UI ساخته می‌شود و مسیرهایشان چاپ می‌شود. تبدیل را worker ِ celery انجام می‌دهد (مثلِ دکمهٔ صفحه)؛
اگر worker روشن نباشد همین‌جا تا ۵ دقیقه صبر می‌کند و می‌گوید.
"""
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.img2code import services, sitedraft, uidesign
from apps.img2code.models import Conversion
from apps.stores.models import Store


class Command(BaseCommand):
    help = "از یک نشانیِ عمومی (پیش‌فرض: چغر) عکس می‌گیرد، تبدیل می‌کند و پیش‌نویسِ سایت‌ساز (+ سندِ UI) را برای یک فروشگاه می‌سازد."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, required=True)
        parser.add_argument("--url", default="https://chagher.ir/")
        parser.add_argument("--user", default="", help="نامِ کاربریِ یک کارمند (پیش‌فرض: اولین ابرکاربر)")
        parser.add_argument("--mode", default="responsive", choices=["responsive", "exact"])
        parser.add_argument("--no-ui", action="store_true")
        parser.add_argument("--wait", type=int, default=300)

    def handle(self, *args, **o):
        User = get_user_model()
        store = Store.objects.filter(pk=o["store"]).first()
        if store is None:
            raise CommandError("فروشگاهِ %s پیدا نشد." % o["store"])
        user = User.objects.filter(username=o["user"], is_staff=True).first() if o["user"] else User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        if user is None:
            raise CommandError("کاربرِ کارمند پیدا نشد.")
        eng = services.engine_status(refresh=True)
        if not eng["ready"] or not eng["url_ok"]:
            raise CommandError("موتور یا مرورگر آماده نیست: " + "؛ ".join(eng["messages"]))
        conv = services.create_url(store, user, o["url"], o["mode"], "fa", 1280, True, "نمونهٔ چغر — از نشانیِ صفحه")
        self.stdout.write("تبدیل #%d ساخته شد؛ منتظرِ worker ..." % conv.pk)
        t0 = time.time()
        while time.time() - t0 < o["wait"]:
            conv.refresh_from_db()
            if not conv.active:
                break
            time.sleep(3)
        if conv.state != Conversion.State.READY:
            raise CommandError("تبدیل تمام نشد (%s): %s" % (conv.state, conv.error or conv.message))
        self.stdout.write("تبدیل آماده شد: %s" % "، ".join("%s %s" % (s["label"], s["display"]) for s in conv.scores))
        out = sitedraft.create_draft(conv, user)
        self.stdout.write("پیش‌نویسِ سایت‌ساز (منتشر نشده): %s  [%d بلوک، %d تصویر]" % (out["url"], out["stats"].get("blocks", 0), out["stats"].get("images", 0)))
        if not o["no_ui"] and uidesign.enabled():
            ui = uidesign.create_doc(conv, user)
            self.stdout.write("سندِ طراحیِ UI: %s" % ui["url"])
        self.stdout.write("پنل: /stores/%d/design/image-to-code" % store.pk)

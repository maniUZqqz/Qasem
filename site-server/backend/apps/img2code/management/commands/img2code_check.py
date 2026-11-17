# -*- coding: utf-8 -*-
"""آزمونِ پذیرشِ «تصویر به کد» روی همین سرور (بی‌پایگاه‌داده؛ فقط پوشهٔ موقت):

    cd backend && ../venv/bin/python manage.py img2code_check [--url https://chagher.ir/]

مرحله‌ها: وارسیِ موتور ⇒ ساختنِ یک صفحهٔ کوچک ⇒ تبدیل (پردازهٔ جدا) ⇒ نمایش و سنجش در مرورگر ⇒ درخت ⇒ سندِ سایت‌ساز (clean_doc) ⇒ (اگر --url) عکس از نشانی.
کدِ خروج ۰ یعنی همه‌چیز کار می‌کند؛ هر مرحله «PASS/FAIL» چاپ می‌کند. همین منطق آزمونِ خودکارِ سرورِ پردازش (selftests/img2code.py) هم هست.
"""
import sys

from django.core.management.base import BaseCommand

from apps.img2code import selftest


class Command(BaseCommand):
    help = "آزمونِ پذیرشِ «تصویر به کد»: یک تبدیلِ واقعیِ کوچک از آغاز تا سندِ سایت‌ساز (بی‌پایگاه‌داده)."

    def add_arguments(self, parser):
        parser.add_argument("--url", default="", help="اگر داده شود از این نشانیِ عمومی هم عکس می‌گیرد و تبدیل می‌کند")

    def handle(self, *args, **opts):
        res = selftest.run_engine(opts["url"])
        for s in res["steps"]:
            self.stdout.write(("PASS " if s["ok"] else "FAIL ") + s["name"] + ((" :: " + s["detail"]) if s["detail"] else ""))
        self.stdout.write("%s in %ss" % ("OK" if res["ok"] else "FAILURES: %d" % sum(1 for s in res["steps"] if not s["ok"]), res["seconds"]))
        sys.exit(0 if res["ok"] else 1)

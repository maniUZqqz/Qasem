# -*- coding: utf-8 -*-
"""سنجشِ دوبارهٔ همهٔ قطعه‌های تبدیل‌شده در مرورگر (RTL، «خالیِ ایستا»، خوانایی روی پوستهٔ روشن/تیره، رویِ‌هم‌افتادگی، «بی‌متن»).

    python manage.py c21_recheck [--all] [--batch 20] [--max-minutes 90]

پیش‌فرض فقط رکوردهایی را می‌سنجد که با نسخهٔ فعلیِ سنجش (c21_rtl.CHECK_VERSION) نسنجیده‌اند (تسکِ Celery هم هر نوبت ۵۰ تا را همین‌طور می‌سنجد)؛ ``--all`` همه را.
خروجی هر دسته یک سطرِ JSON است و آخرین سطر ``DONE`` یا ``FAILED`` (برای اجرای جداشده با setsid/nohup).
"""
import json
import time

from django.core.management.base import BaseCommand

from apps.projects.builder import c21_convert as CV, c21_rtl


class Command(BaseCommand):
    help = "سنجشِ دوبارهٔ قطعه‌های 21st.dev در مرورگر (خوانایی روی روشن و تیره، سرریز، خالی، رویِ‌هم‌افتاده)"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="همه را بسنج، نه فقط نسخهٔ کهنه‌ها")
        parser.add_argument("--batch", type=int, default=20)
        parser.add_argument("--max-minutes", type=float, default=90.0)

    def handle(self, *a, **o):
        n = CV.relicense_all()                                    # بی‌مرورگر: مجوزِ مخزن در رکورد و فهرست (کاتالوگ «MIT»، مخزن «Apache-2.0»)
        self.stdout.write(json.dumps({"relicensed": n}))
        ok, why = c21_rtl.available()
        if not ok:
            self.stdout.write("FAILED browser unavailable: %s" % why)
            return
        end = time.monotonic() + o["max_minutes"] * 60
        done = 0
        keys = [e["key"] for e in CV.load_index().values()] if o["all"] else None
        while time.monotonic() < end:
            batch = (keys[done:done + o["batch"]] if keys is not None else c21_rtl.outdated_keys(o["batch"]))
            if not batch:
                break
            res = c21_rtl.apply(batch)
            done += len(batch)
            counts = {}
            for k in batch:
                rec = CV.load_record(k) or {}
                st = (rec.get("rtl") or {}).get("status", "?")
                counts[st] = counts.get(st, 0) + 1
            self.stdout.write(json.dumps({"checked": done, "batch": counts, "skipped": sum(1 for r in res.values() if r.get("status") == "skipped")}, ensure_ascii=False))
            self.stdout.flush()
            if keys is None and all((r.get("status") == "skipped") for r in res.values()):
                self.stdout.write("FAILED the browser did not answer")
                return
        self.stdout.write("DONE checked=%d" % done)

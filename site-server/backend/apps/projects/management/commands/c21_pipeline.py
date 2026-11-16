# -*- coding: utf-8 -*-
"""تبدیلِ قطعه‌های 21st.dev به «قطعهٔ قابلِ درج» (نوبتی؛ قابلِ ازسرگیری).

    python manage.py c21_pipeline [--max-hours 4] [--libs 3] [--only owner/library] [--no-rtl] [--reset-failed]

برای هر کتابخانه‌ای که مخزنِ عمومیِ GitHub دارد و مجوزِ مخزن آزاد است، قطعه‌های با مجوزِ آزادش را پیدا و تبدیل می‌کند. پیش‌نیاز: خزشِ کاتالوگ (c21_crawl)
و جعبه‌ابزارِ /opt/nm-c21 (deploy/c21/install.sh). خودکار با Celery هم همین کار انجام می‌شود (apps.projects.tasks.c21_convert).
"""
import json
import time

from django.core.management.base import BaseCommand

from apps.projects.builder import c21_convert, c21_pipeline, c21st


class Command(BaseCommand):
    help = "تبدیلِ قطعه‌های 21st.dev (مجوزِ آزاد + مخزنِ عمومی) به قطعهٔ قابلِ درج"

    def add_arguments(self, parser):
        parser.add_argument("--max-hours", type=float, default=4.0)
        parser.add_argument("--libs", type=int, default=3, help="چند کتابخانه در هر نوبت")
        parser.add_argument("--only", action="append", default=[], help="فقط این کتابخانه(ها)، مثلاً dillionverma/magic-ui")
        parser.add_argument("--no-rtl", action="store_true", help="سنجشِ راست‌به‌چپ در مرورگر انجام نشود")
        parser.add_argument("--reset-failed", action="store_true", help="قطعه‌های «failed» دوباره تلاش شوند")

    def handle(self, *a, **o):
        if not c21_convert.toolchain_ready():
            self.stdout.write("FAILED toolchain missing (/opt/nm-c21): run deploy/c21/install.sh")
            return
        if o["reset_failed"]:
            rows = c21st.load()
            for r in rows:
                if (r.get("conv") or {}).get("state") == "failed":
                    r.pop("conv", None)
            c21st.save(rows)
        end = time.monotonic() + o["max_hours"] * 3600
        while time.monotonic() < end:
            st = c21_pipeline.run(max_seconds=900.0, libs_limit=o["libs"], only_libs=set(o["only"]) or None, rtl=not o["no_rtl"])
            self.stdout.write(json.dumps({k: st.get(k) for k in ("converted", "failed", "no_source", "libs_done", "remaining_libs", "converted_total", "errors")}, ensure_ascii=False))
            self.stdout.flush()
            if not st.get("remaining_libs") or (not st.get("libs_done") and not st.get("converted")):
                self.stdout.write("DONE")
                return
        self.stdout.write("TIME-LIMIT")

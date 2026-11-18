# -*- coding: utf-8 -*-
"""قطعه‌های 21st.dev که پیش‌تر تبدیل شده‌اند را با مبدّلِ تازه دوباره می‌سازد (از همان commit ِ ذخیره‌شده) و در مرورگر می‌سنجد.

    python manage.py c21_reconvert --all [--only owner/comp ...] [--dry] [--dump DIR] [--no-rtl] [--max-minutes 55]

دورِ ۵: پنل‌های بسته‌شوی آکاردئون/تب در HTML می‌آیند (همهٔ پاسخ‌ها ویرایش‌پذیرند)، رولرِ رقمِ قیمت متنِ ساده می‌شود و سیگنالِ «تعاملی؟» (interact_src) در رکورد می‌نشیند.
رکوردی که تبدیلِ تازه‌اش شکست بخورد دست‌نخورده می‌ماند. خروجی خط‌به‌خط است و آخرین سطر ``DONE`` یا ``FAILED`` (برای setsid/nohup).
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.projects.builder import c21_convert as CV, c21_pipeline


class Command(BaseCommand):
    help = "تبدیلِ دوبارهٔ قطعه‌های 21st.dev با مبدّلِ تازه (رکورد قدیمی در صورتِ شکست می‌ماند)"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="همهٔ قطعه‌های تبدیل‌شده")
        parser.add_argument("--only", action="append", default=[], help="فقط این قطعه(ها)، مثلاً mohammadshehadeh/faq-05")
        parser.add_argument("--dry", action="store_true", help="چیزی ذخیره نشود (با --dump خروجی را می‌نویسد)")
        parser.add_argument("--dump", default="", help="پوشه‌ای که HTML/CSS/سیگنالِ هر قطعهٔ تازه در آن نوشته شود (با --dry)")
        parser.add_argument("--no-rtl", action="store_true")
        parser.add_argument("--max-minutes", type=float, default=55.0)

    def handle(self, *a, **o):
        if not CV.toolchain_ready():
            self.stdout.write("FAILED toolchain missing (/opt/nm-c21): run deploy/c21/install.sh")
            return
        if not o["all"] and not o["only"]:
            self.stdout.write("FAILED give --all or --only")
            return

        def say(*parts):
            self.stdout.write(" ".join(str(p) for p in parts))
            self.stdout.flush()

        st = c21_pipeline.reconvert(o["only"] or None, rtl=not o["no_rtl"], dry=o["dry"], max_seconds=o["max_minutes"] * 60, log=say)
        if o["dump"] and st.get("records"):
            d = Path(o["dump"])
            d.mkdir(parents=True, exist_ok=True)
            for rec in st["records"]:
                (d / (rec["id"].replace("/", "__") + ".json")).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        say(json.dumps({k: st.get(k) for k in ("converted", "failed", "kept_old", "libs", "errors")}, ensure_ascii=False))
        say("DONE converted=%d failed=%d" % (st.get("converted", 0), st.get("failed", 0)))

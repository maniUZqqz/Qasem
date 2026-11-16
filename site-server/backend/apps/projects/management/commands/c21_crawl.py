# -*- coding: utf-8 -*-
"""خزشِ مؤدبانهٔ 21st.dev تا تمام شدن (یا تا سقفِ زمان)؛ قابلِ ازسرگیری.

    python manage.py c21_crawl [--max-hours 6] [--turn-seconds 240] [--detail-limit 120] [--delay 1.2]

هر نوبت وضعیت را در NM_DATA_DIR/c21st/crawl.json می‌نویسد؛ قطع و وصل شد، از همان‌جا ادامه می‌دهد.
خودکارِ سایت همین کار را با Celery (apps.projects.tasks.c21_pipeline) می‌کند؛ این دستور برای اجرای یک‌جا و دستی است.
"""
import json
import time

from django.core.management.base import BaseCommand

from apps.projects.builder import c21_crawl, c21st


class Command(BaseCommand):
    help = "خزشِ مؤدبانهٔ 21st.dev (نقشهٔ سایت، جزئیات، کتابخانه‌ها، پیش‌نمایش)"

    def add_arguments(self, parser):
        parser.add_argument("--max-hours", type=float, default=6.0)
        parser.add_argument("--turn-seconds", type=float, default=240.0)
        parser.add_argument("--detail-limit", type=int, default=120)
        parser.add_argument("--preview-limit", type=int, default=40)
        parser.add_argument("--delay", type=float, default=c21_crawl.DELAY)

    def handle(self, *a, **o):
        end = time.monotonic() + o["max_hours"] * 3600
        n = 0
        unreadable = 0
        while time.monotonic() < end:
            n += 1
            sess = c21_crawl.Session(delay=o["delay"])
            st = c21_crawl.run_turn(session=sess, max_seconds=o["turn_seconds"], detail_limit=o["detail_limit"], preview_limit=o["preview_limit"])
            self.stdout.write(json.dumps({"turn": n, "total": st.get("total"), "remaining": st.get("remaining"), "usable": st.get("usable"),
                                          "previews": st.get("previews"), "libs": st.get("libraries"), "requests": st.get("requests"),
                                          "blocked": st.get("blocked"), "errors": (st.get("errors") or [])[-2:]}, ensure_ascii=False))
            self.stdout.flush()
            if st.get("finished"):
                self.stdout.write("DONE")
                return
            if st.get("blocked"):
                self.stdout.write("FAILED blocked (403) - the GPU node job crawl21.run is the way around")
                return
            if not st.get("robots_ok", True):
                unreadable += 1
                if unreadable >= 30:                                 # سی نوبتِ پشت‌سرهم (~یک ساعت) نشد ⇒ بس است؛ نوبتِ بعدیِ Celery دوباره امتحان می‌کند
                    self.stdout.write("FAILED robots.txt unreadable")
                    return
                self.stdout.write("robots.txt unreadable; waiting 120 s")
                time.sleep(120)
            else:
                unreadable = 0
        self.stdout.write("TIME-LIMIT")

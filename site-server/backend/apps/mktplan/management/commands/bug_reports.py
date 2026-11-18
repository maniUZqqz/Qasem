"""گزارش‌های ایرادی که مالک از پنل فرستاده را می‌خواند (برای رفعِ ایراد).

    python manage.py bug_reports                    # گزارش‌های جدید و دیده‌نشده
    python manage.py bug_reports --all              # همه
    python manage.py bug_reports --json             # خروجیِ ماشینی (با نشانیِ عکس و زمینه)
    python manage.py bug_reports --mark 12 fixed    # وضعیت را عوض کن (new|seen|fixed|wontfix)
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.mktplan.models import BugReport
from apps.mktplan.views import bug_public


class Command(BaseCommand):
    help = "خواندنِ گزارش‌های ایراد"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--section", default="")
        parser.add_argument("--mark", nargs=2, metavar=("ID", "STATE"))

    def handle(self, *args, **o):
        if o["mark"]:
            pk, state = o["mark"]
            if state not in dict(BugReport.State.choices):
                raise CommandError("وضعیت باید یکی از new, seen, fixed, wontfix باشد.")
            n = BugReport.objects.filter(pk=int(pk)).update(state=state)
            self.stdout.write(f"{n} گزارش به‌روز شد.")
            return
        qs = BugReport.objects.select_related("user", "store").order_by("-id")
        if not o["all"]:
            qs = qs.filter(state__in=("new", "seen"))
        if o["section"]:
            qs = qs.filter(section=o["section"])
        rows = list(qs[:200])
        if o["json"]:
            self.stdout.write(json.dumps([bug_public(b) for b in rows], ensure_ascii=False, indent=1))
            return
        if not rows:
            self.stdout.write("گزارشی برای رسیدگی نیست.")
            return
        for b in rows:
            self.stdout.write(f"#{b.pk} [{b.get_state_display()}] {b.created_at:%Y-%m-%d %H:%M} · {b.section_title or b.section} · {b.page_url}")
            self.stdout.write(f"    {b.note[:300]}")
            if b.screenshot:
                self.stdout.write(f"    عکس: {b.screenshot.url}")
            errs = (b.context or {}).get("errors") or []
            for e in errs[:3]:
                self.stdout.write(f"    ! {str(e)[:160]}")

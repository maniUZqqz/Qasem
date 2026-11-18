"""«برنامهٔ بازاریابی» را برای یک فروشگاه می‌سازد و اجرا می‌کند (تکرارپذیر؛ چیزِ موجود دوباره ساخته نمی‌شود).

    python manage.py marketing_plan_run --store 34                 # بساز + اجرا (ساخت و پیوند و صف‌گذاریِ کارهای سرورِ پردازش)
    python manage.py marketing_plan_run --store 34 --no-run        # فقط ساختارِ برنامه
    python manage.py marketing_plan_run --store 34 --sync          # فقط وضعیت‌ها را از روی چیزهای ساخته‌شده تازه کن
    python manage.py marketing_plan_run --name چغر --restart       # تاریخِ شروع را به فردا ببر و زمان‌ها را تازه کن
    python manage.py marketing_plan_run --store 34 --report        # فقط گزارشِ وضعیت

هیچ‌چیز منتشر یا فرستاده نمی‌شود. کارهای GPU در صفِ ماندگار می‌مانند و با روشن‌شدنِ سرورِ پردازش خودشان اجرا می‌شوند.
"""
from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.mktplan import kinds, planner, runner
from apps.mktplan.models import MarketingPlan
from apps.stores.models import Store


class Command(BaseCommand):
    help = "ساخت و اجرای برنامهٔ بازاریابیِ دو‌هفته‌ای یک فروشگاه"

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, default=0)
        parser.add_argument("--name", default="", help="بخشی از نامِ فروشگاه (اگر شناسه را نمی‌دانید)")
        parser.add_argument("--start", default="", help="تاریخِ شروع (YYYY-MM-DD)؛ پیش‌فرض فردا")
        parser.add_argument("--restart", action="store_true")
        parser.add_argument("--no-run", action="store_true")
        parser.add_argument("--sync", action="store_true")
        parser.add_argument("--report", action="store_true")
        parser.add_argument("--tick", action="store_true", help="یک تیکِ پس‌زمینه (همگام + پیش‌بردنِ کارهای منتظر)")

    def handle(self, *args, **o):
        qs = Store.objects.filter(pk=o["store"]) if o["store"] else Store.objects.filter(name__contains=o["name"]) if o["name"] else None
        if qs is None:
            raise CommandError("--store یا --name را بدهید.")
        store = qs.order_by("pk").first()
        if store is None:
            raise CommandError("فروشگاه پیدا نشد.")
        start = dt.date.fromisoformat(o["start"]) if o["start"] else None
        plan = MarketingPlan.objects.filter(store=store, key="starter").first()
        if o["report"] or o["sync"] or o["tick"]:
            if plan is None:
                raise CommandError("برای این فروشگاه هنوز برنامه‌ای نیست.")
            if o["tick"]:
                self.stdout.write(str(runner.tick(plan.pk)))
            else:
                runner.sync_plan(plan, refresh=True)
            return self._report(plan)
        plan, info = planner.ensure_plan(store, None, start=start, restart=o["restart"])
        self.stdout.write(f"برنامه: «{plan.name}» · شروع {plan.start_date} · {info}")
        if not o["no_run"]:
            res = runner.run_plan(plan, user=None, force=True)
            self.stdout.write(f"اجرا: {res['ran']} کار · موفق {res['ok']} · ناموفق {res['failed']} · منتظرِ گره {res['waiting']} · ردشده/تصمیم‌گرفته {res['skipped']}")
        self._report(plan)

    def _report(self, plan: MarketingPlan):
        plan.refresh_from_db()
        node = runner.node_state()
        self.stdout.write(f"\nسرورِ پردازش: {'روشن' if node['online'] else 'خاموش'} ({node['name'] or '—'})")
        c = runner.counts(plan)
        self.stdout.write("وضعیت‌ها: " + "، ".join(f"{kinds.STATUS_FA.get(k, k)}={v}" for k, v in sorted(c["by_status"].items())))
        for i in plan.items.order_by("day", "order", "id"):
            refs = ",".join(f"{r.get('type')}#{r.get('id')}" for r in (i.refs or []))
            self.stdout.write(f"  روز {i.day:>2} {i.key:<22} {kinds.STATUS_FA.get(i.status, i.status):<24} {i.title[:46]} [{refs}]")
            if i.last_error:
                self.stdout.write(f"        ! {i.last_error[:160]}")

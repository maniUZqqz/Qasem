# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from accounting import services


class Command(BaseCommand):
    help = 'خریدهای پرداخت‌شدهٔ توکن را به سندِ درآمد تبدیل می‌کند (هر خرید فقط یک بار).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='فقط نشان بده، ثبت نکن.')

    def handle(self, *args, dry_run=False, **opts):
        created, rows, stale = services.import_payments(user=None, dry_run=dry_run)
        ready = [r for r in rows if not r['problem']]
        blocked = [r for r in rows if r['problem']]
        self.stdout.write('آماده: %d (جمع %s)' % (len(ready), services.money(sum(r['amount'] for r in ready))))
        self.stdout.write('ثبت شد: %d' % len(created))
        for r in blocked:
            self.stdout.write('  رد شد: خریدِ #%s — %s' % (r['purchase'].pk, r['problem']))
        for s in stale:
            self.stdout.write('  ⚠ خریدِ #%s دیگر «پرداخت‌شده» نیست ولی سندِ %s دارد؛ اگر لازم است برگشت بزنید.'
                              % (s['purchase_id'], s['entry_id']))

"""هماهنگ‌کنندهٔ کارها (نیمهٔ پنل): برنامه‌ریزی، آماده‌سازی (صدا/لب/برچسب)، کنترلِ کیفیت و مونتاژ.
رندرِ سنگین این‌جا نیست؛ کارگرها انجامش می‌دهند.   python manage.py orchestrator"""
import os
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.up3d import services


class Command(BaseCommand):
    help = 'اجرای مداومِ صفِ کارهای پنل'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **opts):
        if hasattr(os, 'nice'):
            os.nice(5)
        n = services.recover_interrupted()
        self.stdout.write('orchestrator started (recovered %d)' % n)
        while True:
            close_old_connections()
            try:
                did = services.orchestrate_once()
            except Exception as e:   # حلقه نباید بمیرد
                self.stderr.write('orchestrator error: %s' % e)
                did = 0
            if opts['once']:
                return
            time.sleep(0.5 if did else 2.0)

# -*- coding: utf-8 -*-
"""پایه دستورات مدیریتی با خروجی فارسی سالم روی کنسول ویندوز.

کنسول پیش‌فرض ویندوز cp1252 است و `self.stdout.write` با متن فارسی
UnicodeEncodeError می‌دهد — یعنی دستور با خطا تمام می‌شود حتی وقتی کارش
را درست انجام داده. این پایه، جریان خروجی را روی UTF-8 تنظیم می‌کند.
"""
from django.core.management.base import BaseCommand


class Utf8Command(BaseCommand):
    """BaseCommand با خروجی UTF-8 (برای پیام‌های فارسی)"""

    def _use_utf8_output(self):
        for stream in (self.stdout, self.stderr):
            reconfigure = getattr(getattr(stream, '_out', None), 'reconfigure', None)
            if reconfigure:
                try:
                    reconfigure(encoding='utf-8', errors='replace')
                except (ValueError, OSError):
                    pass

    def create_parser(self, *args, **kwargs):
        # --help را argparse مستقیم روی sys.stdout چاپ می‌کند، پیش از execute
        self._use_utf8_output()
        return super().create_parser(*args, **kwargs)

    def execute(self, *args, **options):
        self._use_utf8_output()
        return super().execute(*args, **options)

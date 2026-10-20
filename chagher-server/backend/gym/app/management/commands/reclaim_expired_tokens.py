# -*- coding: utf-8 -*-
"""بازگرداندن توکن‌های رزروشده‌ی منقضی به حساب مربی.

اگر مربی روی یک کد دسترسی توکن رزرو کند و مشتری تا مهلت تعیین‌شده کد را
فعال نکند، توکن‌ها به حساب مربی برمی‌گردند تا بلااستفاده نمانند.

مهلت از پنل ادمین تنظیم می‌شود: تنظیمات سامانه → مهلت توکن رزروشده (روز).

اجرا:
    python manage.py reclaim_expired_tokens            # اعمال واقعی
    python manage.py reclaim_expired_tokens --dry-run  # فقط گزارش، بدون تغییر
    python manage.py reclaim_expired_tokens --days 15  # نادیده‌گرفتن تنظیم ادمین

پیشنهاد: روزی یک‌بار با زمان‌بند سیستم (cron / Task Scheduler) اجرا شود.
"""
import logging

from app.management.utf8_command import Utf8Command

from app.models import GymClient, PlatformSettings

logger = logging.getLogger(__name__)


class Command(Utf8Command):
    help = 'بازگرداندن توکن‌های رزروشده منقضی روی کدهای دسترسی استفاده‌نشده به مربی'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='فقط گزارش بده، چیزی تغییر نده')
        parser.add_argument('--days', type=int, default=None,
                            help='مهلت دلخواه (روز) به‌جای مقدار تنظیم‌شده در ادمین')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        expiry_days = options['days']

        if expiry_days is None:
            expiry_days = PlatformSettings.get_solo().pending_token_expiry_days

        if expiry_days <= 0:
            self.stdout.write(self.style.WARNING(
                'مهلت روی صفر تنظیم شده است — بازگشت خودکار غیرفعال است.'
            ))
            return

        candidates = GymClient.objects.filter(
            is_used=False,
            pending_tokens__gt=0,
            tokens_reserved_at__isnull=False,
        ).select_related('gym_owner')

        expired = [c for c in candidates if c.pending_tokens_expired(expiry_days)]

        if not expired:
            self.stdout.write('هیچ توکن رزروشده منقضی‌ای پیدا نشد.')
            return

        total = 0
        for client in expired:
            amount = client.pending_tokens
            owner = client.gym_owner.phone_number
            if dry_run:
                self.stdout.write(
                    f'[آزمایشی] کد {client.access_code}: {amount} توکن به {owner} برمی‌گشت.'
                )
                total += amount
                continue

            returned = client.reclaim_pending_tokens()
            if returned:
                total += returned
                logger.info(
                    f'Reclaimed {returned} expired tokens from access code '
                    f'{client.access_code} back to coach {owner}'
                )
                self.stdout.write(self.style.SUCCESS(
                    f'کد {client.access_code}: {returned} توکن به {owner} بازگشت.'
                ))

        prefix = '[آزمایشی] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{prefix}جمع: {total} توکن روی {len(expired)} کد (مهلت: {expiry_days} روز).'
        ))

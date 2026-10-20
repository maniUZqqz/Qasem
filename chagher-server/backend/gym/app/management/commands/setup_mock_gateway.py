# -*- coding: utf-8 -*-
"""فعال‌سازی سریع درگاه پرداخت تستی برای محیط توسعه."""
from app.management.utf8_command import Utf8Command
from app.models import PaymentGatewayConfig


class Command(Utf8Command):
    help = 'ساخت/فعال‌سازی درگاه پرداخت تستی (mock) — بدون پول واقعی'

    def add_arguments(self, parser):
        parser.add_argument(
            '--callback',
            default='http://localhost:8000/api/payment-callback/',
            help='آدرس کال‌بک (پیش‌فرض: http://localhost:8000/api/payment-callback/)',
        )
        parser.add_argument(
            '--off',
            action='store_true',
            help='غیرفعال کردن درگاه تستی به‌جای فعال کردن آن',
        )

    def handle(self, *args, **options):
        if options['off']:
            updated = PaymentGatewayConfig.objects.filter(gateway_type='mock').update(is_active=False)
            self.stdout.write(self.style.WARNING(f'درگاه تستی غیرفعال شد ({updated} رکورد).'))
            return

        config, created = PaymentGatewayConfig.objects.get_or_create(
            gateway_type='mock',
            defaults={'merchant_id': '', 'callback_url': options['callback'], 'is_sandbox': True},
        )
        config.callback_url = options['callback']
        config.is_sandbox = True
        config.is_active = True  # save() بقیه درگاه‌ها را خودکار غیرفعال می‌کند
        config.save()

        action = 'ساخته و فعال شد' if created else 'فعال شد'
        self.stdout.write(self.style.SUCCESS(f'درگاه پرداخت تستی {action}.'))
        self.stdout.write(f'  Callback: {config.callback_url}')
        self.stdout.write('  صفحه شبیه‌ساز: /api/mock-payment/?Authority=...')
        self.stdout.write(self.style.WARNING(
            '  یادآوری: قبل از production درگاه واقعی را در پنل ادمین فعال کنید.'
        ))

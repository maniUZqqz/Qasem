"""فهرستِ صفحه‌ها/قابلیت‌های پنل را از registry.py کامل می‌کند (ایده‌مپوتنت):  python manage.py panel_seed"""
from django.core.management.base import BaseCommand

from apps.panel import registry


class Command(BaseCommand):
    def handle(self, *args, **options):
        made = registry.seed()
        self.stdout.write("panel registry: +%(sections)s sections, +%(pages)s pages, +%(features)s features" % made)

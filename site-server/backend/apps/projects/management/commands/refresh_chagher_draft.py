# -*- coding: utf-8 -*-
"""پیش‌نویس‌های ساخته‌شدهٔ «صفحهٔ فرودِ چغر» را به آخرین طرح می‌رساند: لوگو در سربرگ و پابرگ، نمادهای درست، بی‌پیوندِ «#»، جای تصویرِ بالای صفحه.

    python manage.py refresh_chagher_draft [--slug chagher-landing --slug chagher-landing-aurora] [--dry-run]

بی‌خطر و تکرارپذیر: اگر مالک در پروژه چیزی را ذخیره یا منتشر کرده باشد (rev ِ هر سند ≠ ۱، نسخه یا انتشار دارد) آن پروژه دست نمی‌خورد و دلیلش نوشته می‌شود.
سبکِ انتخاب‌شده (پوسته) هرگز عوض نمی‌شود؛ فقط سندهای صفحه، سربرگ و پابرگ. چیزی منتشر نمی‌شود.
"""
from django.core.management.base import BaseCommand

from apps.projects.builder import chagher_draft as D

DEFAULT_SLUGS = ('chagher-landing', 'chagher-landing-aurora')


class Command(BaseCommand):
    help = 'پیش‌نویسِ صفحهٔ فرودِ چغر را (اگر مالک دست نزده) به آخرین طرح می‌رساند.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', action='append', help='نامِ پروژه؛ چندبار قابل‌تکرار (پیش‌فرض: %s)' % '، '.join(DEFAULT_SLUGS))
        parser.add_argument('--dry-run', action='store_true', help='فقط بگو چه می‌شد')

    def handle(self, *args, **opts):
        from apps.projects.models import Design, Project
        for slug in opts['slug'] or DEFAULT_SLUGS:
            if opts['dry_run']:
                p = Project.objects.filter(slug=slug).first()
                untouched = bool(p) and all(d.rev == 1 and not d.published and not d.published_at and not d.versions.exists()
                                            for d in Design.objects.filter(project=p))
                self.stdout.write('%s: %s' % (slug, 'می‌شد به‌روز شود' if untouched else ('نیست' if not p else 'دست‌خورده؛ رها می‌شد')))
                continue
            done, why = D.refresh_draft(slug)
            self.stdout.write('%s: %s — %s' % (slug, 'انجام شد' if done else 'رها شد', why))

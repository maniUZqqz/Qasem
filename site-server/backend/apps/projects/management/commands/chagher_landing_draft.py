# -*- coding: utf-8 -*-
"""ساختِ پروژهٔ پیش‌نویسِ «صفحهٔ فرودِ چغر» در سایت‌ساز (فقط پیش‌نویس؛ منتشر نمی‌شود).

    python manage.py chagher_landing_draft [--slug chagher-landing] [--style bento-grid] [--html خروجی.html]

بعدش در پنل: ابزارها ⇐ سایت‌ساز ⇐ «چغر — پیش‌نویسِ صفحهٔ فرود» ⇐ ویرایشگرِ دیداری؛ سبک را از «پوسته ⇐ سبکِ طراحی» عوض کن.
--html یک نسخهٔ مستقل برای دیدنِ سریع در مرورگر می‌نویسد (قلم‌ها را از پوشهٔ fonts/ کنارش می‌خواهد).
"""
import os
import shutil

from django.core.management.base import BaseCommand, CommandError

from apps.projects.builder import chagher_draft as D, styles, theme as T


class Command(BaseCommand):
    help = 'پیش‌نویسِ صفحهٔ فرودِ چغر با سبکِ طراحی و قطعه‌های آماده (فقط پیش‌نویس).'

    def add_arguments(self, parser):
        parser.add_argument('--slug', default='chagher-landing')
        parser.add_argument('--style', default=D.DEFAULT_STYLE, help='یکی از: %s' % ', '.join(styles.ORDER))
        parser.add_argument('--html', default='', help='مسیرِ یک فایلِ HTML برای پیش‌نمایشِ مستقل (اختیاری)')

    def handle(self, *args, **opts):
        if opts['style'] not in styles.STYLES:
            raise CommandError('سبکِ ناشناخته: %s' % opts['style'])
        project, created = D.create_draft(opts['slug'], opts['style'])
        self.stdout.write('%s پروژهٔ «%s» (%s)' % ('ساخته شد' if created else 'از قبل بود', project.name, project.slug))
        if opts['html']:
            out = os.path.abspath(opts['html'])
            os.makedirs(os.path.join(os.path.dirname(out), 'fonts'), exist_ok=True)
            parts = D.build(opts['style'])
            with open(out, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(D.static_page(parts))
            _faces, used = T.font_faces(parts['theme'])
            for key in used:
                for entry in T.FONTS[key]['files']:
                    shutil.copyfile(os.path.join(T.FONT_DIR, entry[0]), os.path.join(os.path.dirname(out), 'fonts', entry[0]))
            self.stdout.write('پیش‌نمایش: %s' % out)

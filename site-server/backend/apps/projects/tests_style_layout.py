# -*- coding: utf-8 -*-
"""سبک‌های سایت‌ساز در فارسی (۲۰۲۶-۱۱-۱۴): «مجله‌ای» عنوان و توضیح را کنارِ هم می‌چید و حرفِ اولِ درشت (drop cap) حرفِ فارسی را از کلمه می‌کَند؛
تیترِ سربرگ در چند سبک یک کلمهٔ تنها در خطِ آخر داشت. این‌جا ریشه‌ها (CSS) سنجیده می‌شوند و، اگر Playwright نصب باشد، هر ۱۴ سبک در مرورگرِ واقعی."""
import os
import re
import subprocess
import sys
import tempfile
from unittest import SkipTest

from django.test import SimpleTestCase

from apps.projects.builder import blocks_css, components, render as R, starters, styles as S, theme as T
from apps.projects.builder.clean import clean_doc

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'browser_checks')


def _all_style_css():
    for key in S.ORDER:
        yield key, S.style_css(key)


class StyleCssRootCauseTests(SimpleTestCase):
    def test_no_style_uses_a_first_letter_drop_cap(self):
        """::first-letter یک ترفندِ لاتین است؛ روی فارسی حرفِ اولِ کلمه از بقیه جدا می‌افتد."""
        for key, st in S.STYLES.items():
            self.assertNotIn('::first-letter', st.get('extra', ''), key)
            self.assertNotIn('first-letter', S.style_css(key), key)
        self.assertNotIn('first-letter', blocks_css.BLOCK_CSS)
        self.assertNotIn('first-letter', components.BASE)

    def test_editorial_title_is_a_block_so_the_subtitle_never_sits_beside_it(self):
        extra = S.STYLES['editorial']['extra']
        self.assertRegex(extra, r'\.nb-head \.nb-title\{display:block;width:fit-content')
        self.assertNotRegex(extra, r'(?<!\.nb-head )\.nb-title\{[^}]*display:block;width:fit-content', 'فقط داخلِ سرتیتر؛ تیترِ وسط‌چینِ CTA جابه‌جا نشود')

    def test_amiri_headings_have_room_for_persian_marks(self):
        """قلمِ امیری (نیم‌نقطه‌ها و کشیده‌ها) با ارتفاعِ خطِ ۱٫۱۲ در هم می‌رود؛ سبک‌های امیری‌دار ≥ ۱٫۴."""
        amiri = [k for k, st in S.STYLES.items() if st['theme']['font_head'] == 'amiri']
        self.assertIn('editorial', amiri)
        self.assertIn('dark-luxury', amiri)
        for key in amiri:
            css = S.style_css(key)
            self.assertRegex(css, r'\.nb-hero\.nbv-start h1\.nb-hero-title\{line-height:1\.4\}', key)
            self.assertNotRegex(css, r'\.nb-hero-title\{[^}]*line-height:1\.12', key)

    def test_block_css_balances_titles_and_prettifies_paragraphs(self):
        css = blocks_css.BLOCK_CSS
        self.assertRegex(css, r'h1,h2,h3,\.nb-hero-title,\.nb-title\{text-wrap:balance\}')
        self.assertRegex(css, r'p,\.nb-sub\{text-wrap:pretty\}')
        self.assertIn('text-wrap:balance', components.BASE)
        self.assertIn('text-wrap:pretty', components.BASE)

    def test_submenu_rules_do_not_hit_the_subtitle_paragraph(self):
        """ریشهٔ برخوردِ عنوان/توضیح: قاعدهٔ زیرمنو روی `.nb-sub` (که توضیحِ بخش هم هست) display:inline-flex می‌گذاشت."""
        css = blocks_css.BLOCK_CSS
        self.assertNotRegex(css, r'(?m)^\.nb-sub\{position:relative;display:inline-flex\}')
        self.assertIn('div.nb-sub{position:relative;display:inline-flex}', css)
        self.assertIn('div.nb-sub:hover .nb-sub-menu', css)
        self.assertRegex(css, r'(?m)^\.nb-sub\{font-size:1\.06rem')           # توضیحِ بخش همان است که بود
        # و نشانه‌گذاریِ منو هنوز همان div است که قاعده‌ها هدفش می‌گیرند
        self.assertIn('<div class="nb-sub"><a href=', R.NAV_TREE)

    def test_theme_css_of_every_style_carries_the_text_wrap_rules(self):
        th = T.clean_theme(S.apply_to_theme(T.default_theme(), 'editorial'))
        css = T.blocks_css(th, '../fonts/')
        self.assertIn('text-wrap:balance', css)
        self.assertIn('div.nb-sub', css)
        self.assertNotIn('::first-letter', css)

    def test_every_style_still_renders_its_home_starter(self):
        for key in S.ORDER:
            doc = S.apply_to_doc(clean_doc(starters.starter_doc('home'), 'page'), key)
            out = R.render_doc(doc, R.Ctx(canvas=False, target='page', theme=S.STYLES[key]['theme']['colors']))
            self.assertIn('nb-hero-title', out.html, key)


class StyleBrowserLayoutTests(SimpleTestCase):
    """هر ۱۴ سبک، صفحهٔ اصلیِ آماده، در ۱۴۴۰ و ۳۹۰ پیکسل: عنوان و توضیح هم‌پوشانی نداشته باشند و حرفِ اولِ درشت نباشد.
    فقط جایی که Playwright و کرومیوم هست اجرا می‌شود (روی سرور نیست؛ روی ماشینِ توسعه یا QA)."""

    def test_home_starter_of_every_style_has_no_overlap_and_no_drop_cap(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                p.chromium.launch(channel='chromium').close()
        except Exception as exc:                     # noqa: BLE001 — نبودِ مرورگر یعنی «رد شد» نه «خراب شد»
            raise SkipTest('Playwright/Chromium نیست: %s' % str(exc)[:80])
        with tempfile.TemporaryDirectory() as out:
            backend = os.path.dirname(os.path.dirname(HERE))
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            r1 = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(TOOLS, 'render_style_pages.py'), out], cwd=backend, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=300)
            self.assertEqual(r1.returncode, 0, r1.stderr[-800:])
            r2 = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(TOOLS, 'check_style_layout.py'), out], env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=600)
            self.assertEqual(r2.returncode, 0, (r2.stdout[-1500:] + r2.stderr[-500:]))
            self.assertTrue(re.search(r'RESULT PASS', r2.stdout), r2.stdout[-500:])

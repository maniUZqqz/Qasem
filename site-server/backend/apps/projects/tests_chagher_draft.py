# -*- coding: utf-8 -*-
"""پیش‌نویسِ صفحهٔ فرودِ چغر — کیفیت (۲۰۲۶-۱۱-۱۴): لوگو در سربرگ و پابرگ، نمادِ درست برای هر مورد، بی‌پیوندِ «#»، یک جای تصویرِ روشن (نه اسکرین‌شاتِ ساختگی)،
و به‌روزرسانیِ پیش‌نویسِ زنده فقط وقتی مالک دست نزده. (همهٔ جمله‌ها همچنان فقط از واقعیت‌های برند؛ آزمونِ آن در tests_styles.ChagherDraftTests است.)"""
import io
import os
import re

from django.core.management import call_command
from PIL import Image

from apps.projects.builder import chagher_draft as D, publish as P, render as R
from apps.projects.builder.clean import clean_doc, walk
from apps.projects.models import Design, MediaAsset, SiteTheme
from apps.projects.tests_builder import Base


def all_props(doc):
    for b in walk(doc['blocks']):
        yield b, b['props']


def hrefs(html):
    return re.findall(r'href="([^"]*)"', html)


class DraftContentTests(Base):
    def test_logo_file_is_a_small_real_image_of_the_brand(self):
        im = Image.open(D.LOGO_FILE)
        self.assertEqual(im.format, 'WEBP')
        self.assertTrue(120 <= im.width <= 600 and 120 <= im.height <= 600, im.size)
        self.assertIn('A', im.getbands(), 'پس‌زمینهٔ شفاف')
        self.assertLess(os.path.getsize(D.LOGO_FILE), 40_000)
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(D.LOGO_FILE), 'README.md')), 'مبدأ و مجوز نوشته شده')

    def test_create_draft_imports_the_logo_into_the_projects_own_media_and_uses_it_in_header_and_footer(self):
        p, created = D.create_draft('chg-logo')
        self.assertTrue(created)
        assets = list(MediaAsset.objects.filter(project=p))
        self.assertEqual(len(assets), 1)
        ref = 'm:%d' % assets[0].pk
        header = Design.objects.get(project=p, target='header').draft
        footer = Design.objects.get(project=p, target='footer').draft
        self.assertEqual(header['blocks'][0]['props']['logo'], ref)
        self.assertEqual(header['blocks'][0]['props']['logo_alt'], 'چغر')
        self.assertEqual(footer['blocks'][0]['props']['logo'], ref)
        # روی بوم و در خروجیِ نهایی تصویر می‌آید و اندازه‌اش مهار است
        h = R.render_doc(header, R.build_ctx(p, canvas=False, target='header'))
        self.assertIn('class="nb-logo"', h.html)
        self.assertIn('.nbc .nb-brand .nb-logo{height:', h.css)
        f = R.render_doc(footer, R.build_ctx(p, canvas=False, target='footer'))
        self.assertIn('nbc-fc-logo', f.html)
        self.assertIn('.nbc .nbc-fc-logo{display:block;height:44px', f.css)
        self.assertIn('background:#fff', header['extra_css'], 'روی سربرگِ تیره روی کاشیِ سفید (شناسنامهٔ برند)')
        # دوباره ساختن همان فایل را برمی‌گرداند، نه فایلِ تکراری
        self.assertEqual(D.import_logo(p), ref)
        self.assertEqual(MediaAsset.objects.filter(project=p).count(), 1)

    def test_no_link_in_the_draft_goes_nowhere(self):
        parts = D.build()
        for target in ('header', 'page', 'footer'):
            out = R.render_doc(parts[target], R.Ctx(canvas=False, target=target, theme=parts['theme']['colors']))
            self.assertEqual([h for h in hrefs(out.html) if h in ('#', '')], [], target)
            for _b, props in all_props(parts[target]):
                for k, v in props.items():
                    if k.endswith('link'):
                        self.assertNotEqual(v, '#', (target, k))
                for row in props.get('items') or []:
                    if isinstance(row, dict):
                        self.assertNotEqual(row.get('link'), '#')

    def test_each_feature_has_an_icon_that_means_it(self):
        parts = D.build()
        feat = next(p for b, p in all_props(parts['page']) if b['type'] == 'c_feat_bento_showcase')
        by_title = {r['title']: r['icon'] for r in feat['items']}
        self.assertEqual(by_title['کتابخانهٔ بیش از ۱٬۳۰۰ حرکت'], 'gallery', 'کتابخانهٔ حرکت‌ها «کاربر» نیست')
        self.assertEqual(by_title['اسکنِ دستگاه‌های باشگاه'], 'camera')
        self.assertEqual(by_title['خروجیِ PDFِ برندشده'], 'book')
        self.assertEqual(by_title['پیش‌نویسِ برنامه در کمتر از یک دقیقه'], 'zap')
        self.assertEqual(len(set(by_title.values())), len(by_title), 'هر مورد نمادِ خودش را دارد')

    def test_the_hero_has_one_clear_visual_slot_and_never_a_fake_screenshot(self):
        parts = D.build()
        kinds = [b['type'] for b in parts['page']['blocks']]
        self.assertEqual(kinds[0], 'c_hero_center_glow')
        self.assertEqual(kinds[1], 'section')
        img = parts['page']['blocks'][1]['children'][0]
        self.assertEqual((img['type'], img['props']['src']), ('image', ''))
        self.assertFalse(any(re.search(r'(?i)screenshot|اسکرین', str(p)) for b, p in all_props(parts['page']) if b['type'] == 'image'))
        # روی بوم جای خالیِ تصویر دیده می‌شود، روی سایتِ نهایی هیچ‌چیزِ ساختگی
        p, _ = D.create_draft('chg-slot')
        pg = p.pages.get()
        d = self.c.get('/api/v1/studio/projects/chg-slot/builder/bootstrap/', {'target': 'page', 'page': pg.pk}).json()
        cv = self.c.post('/api/v1/studio/projects/chg-slot/builder/render/', {'target': 'page', 'page': pg.pk, 'doc': d['doc'], 'theme': d['theme']}, format='json').json()
        self.assertIn('data-nb-ph', ''.join(x['html'] for x in cv['parts']))
        live = R.render_doc(parts['page'], R.Ctx(canvas=False, target='page', theme=parts['theme']['colors']))
        self.assertNotIn('<img', live.html.split('nbc-feat')[0], 'بی‌تصویر منتشر نمی‌شود، ولی هشدار می‌ماند')
        self.assertTrue(any(w['kind'] == 'media' for w in live.warnings))

    def test_publish_check_lists_only_the_missing_hero_picture_for_the_draft(self):
        p, _ = D.create_draft('chg-check')
        pg = p.pages.get()
        design = Design.objects.get(project=p, target='page')
        r = self.c.post('/api/v1/studio/projects/chg-check/builder/check/', {'target': 'page', 'page': pg.pk, 'doc': design.draft}, format='json')
        out = r.json()['findings']
        self.assertEqual([(f['kind'], f['type']) for f in out], [('media', 'image')], out)

    def test_nothing_in_the_draft_invents_prices_or_statistics(self):
        parts = D.build(logo='m:1')
        texts = []

        def take(v):
            if isinstance(v, str):
                texts.append(v)
            elif isinstance(v, dict):
                for x in v.values():
                    take(x)
            elif isinstance(v, list):
                for x in v:
                    take(x)
        for t in ('header', 'page', 'footer'):
            take([b['props'] for b in walk(parts[t]['blocks'])])
        joined = ' '.join(x for x in texts if not x.startswith('m:'))
        for banned in ('تومان', 'ریال', '٪', '%', '۹۸', '۲۴/۷', 'رضایت', 'تضمین', 'ضمانت'):
            self.assertNotIn(banned, joined)


class RefreshLiveDraftTests(Base):
    def _legacy(self, slug):
        """پیش‌نویسِ قدیمی: بی‌لوگو، نمادِ «users» و پیوندِ «#»."""
        p, _ = D.create_draft(slug)
        p.site_title = p.name                       # همان‌طور که روی سرورِ زنده بود
        p.save(update_fields=['site_title'])
        MediaAsset.objects.filter(project=p).delete()
        old = D.build()
        page = old['page']
        page['blocks'] = [b for b in page['blocks'] if b['type'] != 'section']
        for b in page['blocks']:
            for row in b['props'].get('items') or []:
                if isinstance(row, dict) and 'link' in row and not row.get('link'):
                    row['link'] = '#'
        for target, doc in (('page', page), ('header', old['header']), ('footer', old['footer'])):
            Design.objects.filter(project=p, target=target).update(draft=doc, rev=1)
        return p

    def test_an_untouched_live_draft_gets_the_new_design_and_the_theme_is_kept(self):
        p = self._legacy('chg-old')
        theme_before = SiteTheme.objects.get(project=p).draft
        done, why = D.refresh_draft('chg-old')
        self.assertTrue(done, why)
        header = Design.objects.get(project=p, target='header')
        self.assertTrue(header.draft['blocks'][0]['props']['logo'].startswith('m:'))
        self.assertEqual(header.rev, 2, 'ویرایشگرِ بازِ قدیمی با ذخیره‌اش 409 می‌گیرد، نه این‌که طرحِ تازه را بنویسد')
        page = Design.objects.get(project=p, target='page')
        self.assertEqual([b['type'] for b in page.draft['blocks']][:2], ['c_hero_center_glow', 'section'])
        self.assertEqual(MediaAsset.objects.filter(project=p).count(), 1)
        self.assertEqual(SiteTheme.objects.get(project=p).draft, theme_before)
        p.refresh_from_db()
        self.assertEqual(p.site_title, 'چغر', 'نامِ سایت فقط «چغر» است، نه نامِ پیش‌نویس')
        again, why2 = D.refresh_draft('chg-old')
        self.assertFalse(again)
        self.assertIn('همین حالا', why2)

    def test_the_owners_edit_is_never_overwritten(self):
        p = self._legacy('chg-edited')
        d = Design.objects.get(project=p, target='page')
        doc = clean_doc(d.draft, 'page')
        doc['blocks'][0]['props']['title'] = 'عنوانِ تازهٔ مالک'
        P.save_draft(d, doc, d.rev)                                    # مثلِ ذخیرهٔ ویرایشگر: rev ← ۲
        done, why = D.refresh_draft('chg-edited')
        self.assertFalse(done)
        self.assertIn('دست نخورد', why)
        d.refresh_from_db()
        self.assertEqual(d.draft['blocks'][0]['props']['title'], 'عنوانِ تازهٔ مالک')
        self.assertFalse(MediaAsset.objects.filter(project=p).exists(), 'وقتی چیزی عوض نمی‌شود لوگو هم وارد نمی‌شود')

    def test_a_published_or_versioned_draft_is_left_alone(self):
        p = self._legacy('chg-pub')
        Design.objects.filter(project=p, target='footer').update(published={'v': 1, 'blocks': []})
        self.assertFalse(D.refresh_draft('chg-pub')[0])
        q = self._legacy('chg-ver')
        P.snapshot(Design.objects.get(project=q, target='page'), {'v': 1, 'blocks': []}, '', 'x', 'draft')
        self.assertFalse(D.refresh_draft('chg-ver')[0])
        self.assertEqual(D.refresh_draft('no-such-project'), (False, 'پروژه‌ای با این نام نیست'))

    def test_management_command_dry_run_then_run(self):
        self._legacy('chagher-landing')
        out = io.StringIO()
        call_command('refresh_chagher_draft', '--dry-run', stdout=out)
        self.assertIn('می‌شد به‌روز شود', out.getvalue())
        self.assertIn('chagher-landing-aurora: نیست', out.getvalue())
        self.assertFalse(MediaAsset.objects.exists())
        out = io.StringIO()
        call_command('refresh_chagher_draft', stdout=out)
        self.assertIn('chagher-landing: انجام شد', out.getvalue())
        self.assertTrue(MediaAsset.objects.exists())
        out = io.StringIO()
        call_command('refresh_chagher_draft', stdout=out)
        self.assertIn('رها شد', out.getvalue())

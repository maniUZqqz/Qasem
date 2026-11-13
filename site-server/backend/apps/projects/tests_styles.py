# -*- coding: utf-8 -*-
"""آزمونِ «سبک‌های طراحی + قطعه‌های آماده» در سایت‌ساز.

· سبک: ۱۴ سبکِ درخواستی با توکن، قلمِ فارسی‌پذیر، تباینِ رنگ، لایهٔ CSS و چیدمانِ بخش‌ها؛ اعمال روی پوسته و صفحه؛ سازگاریِ بی‌سبک (بایت‌به‌بایت).
· قطعه‌ها: ۴۹ قطعه، مبدأ و مجوزِ هر کدام، رندر در سه حالت، راست‌به‌چپ، escape، ویرایشِ درجا، چرخهٔ AI (importer)، CSSِ فقط-برای-قطعه‌های-به‌کاررفته.
· AI: بسته‌ای که به مدل می‌رسد کوچک و محدود است (سقفِ ۹۰۰۰ نویسه و ۵ قطعه) و CSSِ قطعه‌های به‌کاررفته خودکار به صفحه می‌چسبد.
"""
import json
import os
import re

from django.template import Engine
from django.test import SimpleTestCase
from unittest import mock

from apps.ai_engine import services as ai
from apps.projects.builder import ai_context, components as C, importer, render as R, starters, styles as S, theme as T, variants as V
from apps.projects.builder import clean
from apps.projects.builder.catalog import BLOCKS, catalog_json
from apps.projects.models import Design, Page, Project, SharedPart, SiteTheme
from apps.projects.tests_builder import API, Base, MockProvider

REQUESTED = ['Glassmorphism', 'Claymorphism', 'Neumorphism', 'Neo-brutalism', 'Bento grid', 'Minimalism', 'Aurora', 'Dark luxury', 'Soft pastel',
             'Corporate clean', 'Editorial', 'Retro', 'Swiss', 'Organic']
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = T.FONT_DIR
PERSIAN_PROBE = 'پچژگکیء۰۱۲۳۴۵۶۷۸۹'


def engine():
    return Engine(libraries={'static': 'django.templatetags.static'}, builtins=['django.templatetags.static', 'apps.projects.builder.nb_filters'])


class StyleDataTests(Base):
    def test_all_fourteen_requested_styles_exist(self):
        names = ' | '.join(st['en'] for st in S.STYLES.values()).lower()
        for want in REQUESTED:
            self.assertIn(want.lower(), names, want)
        self.assertEqual(len(S.ORDER), 14)
        self.assertEqual(set(S.ORDER), set(S.STYLES))

    def test_every_style_is_complete(self):
        for key, st in S.STYLES.items():
            for f in ('label', 'en', 'mood', 'desc', 'tags', 'theme', 'tokens', 'sections', 'uiux'):
                self.assertTrue(st.get(f) is not None, (key, f))
            th = st['theme']
            self.assertEqual(set(th['colors']), set(T.COLOR_VARS), key)
            for v in th['colors'].values():
                self.assertRegex(v, r'^#[0-9a-f]{6}$', key)
            self.assertIn(th['font_head'], T.FONTS, key)
            self.assertIn(th['font_body'], T.FONTS, key)
            self.assertIn(th['button'], T.BUTTONS, key)
            self.assertTrue(0 <= th['radius'] <= 40 and 800 <= th['width'] <= 1600, key)
            self.assertFalse(set(st['tokens']) - set(S.css.DEFAULTS), '%s توکنِ ناشناخته دارد' % key)
            for btype, variant in st['sections'].items():
                self.assertTrue(V.has_field(btype), (key, btype))
                if variant:
                    self.assertTrue(V.has(btype, variant), (key, btype, variant))
            ref = S.uiux.reference_for(st)
            self.assertTrue(ref['style'], '%s در دادهٔ ui-ux-pro-max پیدا نشد' % key)
            self.assertTrue(ref['font_pairing'] and ref['palette'], key)

    def test_colour_contrast_is_accessible_in_every_style(self):
        for key, st in S.STYLES.items():
            c = st['theme']['colors']
            self.assertGreaterEqual(R.contrast(c['text'], c['bg']), 7, (key, 'text/bg'))
            self.assertGreaterEqual(R.contrast(c['text'], c['surface']), 7, (key, 'text/surface'))
            self.assertGreaterEqual(R.contrast(c['text2'], c['bg']), 4.5, (key, 'text2/bg'))
            self.assertGreaterEqual(R.contrast(c['muted'], c['bg']), 4.5, (key, 'muted/bg'))
            self.assertGreaterEqual(R.contrast(c['muted'], c['surface']), 4.5, (key, 'muted/surface'))
            self.assertGreaterEqual(R.contrast(c['on_primary'], c['primary']), 4.5, (key, 'button text'))
            self.assertGreaterEqual(R.contrast(c['primary'], c['bg']), 4.5, (key, 'brand on background'))

    def test_fonts_have_persian_glyphs_and_licenses(self):
        """حروفِ فارسی در هر قلمِ به‌کاررفته هست. woff2 را fontTools فقط با brotli می‌خواند (روی سرور نیست)؛ پس گزارشِ check_fonts.py (با sha256 ِ هر فایل)
        سنجیده می‌شود و اگر brotli باشد گزارش از نو ساخته و مقایسه می‌شود."""
        import hashlib
        rep = json.load(open(os.path.join(FONT_DIR, 'coverage.json'), encoding='utf-8'))
        self.assertEqual(rep['probe'], PERSIAN_PROBE)
        used = set()
        for st in S.STYLES.values():
            used |= {st['theme']['font_head'], st['theme']['font_body']}
        for fk in sorted(used):
            row = rep['fonts'][fk]
            self.assertEqual(row['missing'], '', '%s حرف یا رقمِ فارسی را ندارد' % fk)
            self.assertEqual([f['file'] for f in row['files']], [e[0] for e in T.FONTS[fk]['files']], fk)
            for f in row['files']:
                with open(os.path.join(FONT_DIR, f['file']), 'rb') as fh:
                    self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), f['sha256'], '%s عوض شده؛ check_fonts.py را دوباره اجرا کن' % f['file'])
        try:
            import brotli  # noqa
            from apps.projects.builder.styles import check_fonts
        except ImportError:
            check_fonts = None
        if check_fonts is not None:
            self.assertEqual(check_fonts.compute()['fonts'], rep['fonts'])
        for lic in ('amiri', 'ibm-plex-sans-arabic', 'variable-baloo-bhaijaan-2', 'variable-cairo', 'variable-noto-kufi-arabic'):
            path = os.path.join(FONT_DIR, 'LICENSE-fontsource-%s.txt' % lic)
            self.assertTrue(os.path.isfile(path), lic)
            self.assertIn('Open Font License', open(path, encoding='utf-8').read())

    def test_uiux_data_is_mit_attributed(self):
        info = S.uiux.attribution()
        self.assertEqual(info['license'], 'MIT')
        self.assertIn('nextlevelbuilder/ui-ux-pro-max-skill', info['source'])
        self.assertTrue(info['copyright'])
        for kind in ('styles', 'colors', 'fonts', 'ux', 'landing'):
            self.assertGreater(info['counts'][kind], 20, kind)
        lic = open(os.path.join(S.uiux.HERE, 'dataset', 'LICENSE-ui-ux-pro-max-skill.txt'), encoding='utf-8').read()
        self.assertIn('MIT License', lic)
        self.assertIn('Next Level Builder', lic)
        rows = S.uiux.search('styles', 'glassmorphism frosted blur')
        self.assertTrue(rows and 'glass' in rows[0]['name'].lower())

    def test_style_css_is_safe_and_scoped(self):
        for key in S.ORDER:
            css = S.style_css(key)
            self.assertEqual(css.count('{'), css.count('}'), key)
            self.assertNotIn('</style', css.lower())
            self.assertNotIn('@import', css)
            self.assertNotIn('url(', css)
            self.assertNotIn('expression(', css.lower())
            self.assertLess(len(css), 14000, key)
            self.assertIn('--st-card-bg', css)
        self.assertEqual(S.style_css('no-such-style'), '')


class StyleApplyTests(Base):
    def test_unstyled_theme_gets_byte_identical_blocks_css(self):
        th = T.clean_theme({})
        self.assertNotIn('style', th)
        css = T.blocks_css(th, '../fonts/', '')
        faces, _ = T.font_faces(th, '../fonts/')
        body = T.FONTS['vazirmatn']['family']
        tokens = ':root{--nb-font-body:"%s",%s;--nb-font-head:"%s","%s",%s;--nb-btn-radius:%dpx;--nb-width:%dpx}' % (body, T.FALLBACK, body, body, T.FALLBACK, 999, 1140)
        self.assertEqual(css, '\n'.join([faces, tokens, T.BLOCK_CSS]) + '\n')
        self.assertNotIn('--st-', css)

    def test_tokens_apply_to_theme_and_css(self):
        for key in S.ORDER:
            th = T.clean_theme(S.apply_to_theme(T.default_theme(), key))
            self.assertEqual(th['style'], key)
            for ck, cv in S.STYLES[key]['theme']['colors'].items():
                self.assertEqual(th['colors'][ck], cv, (key, ck))
            self.assertEqual(th['font_head'], S.STYLES[key]['theme']['font_head'])
            css = T.blocks_css(th, '../fonts/', '')
            self.assertIn('--st-card-bg:', css)
            self.assertIn(S.STYLES[key]['label'], css)
            fam = T.FONTS[th['font_head']]['family']
            self.assertIn('font-family:"%s"' % fam, css)
            zone = T.colors_zone(th)
            self.assertIn('--brand: %s' % S.STYLES[key]['theme']['colors']['primary'], zone)
        # توکنِ یک سبک واقعاً در CSS می‌نشیند
        glass = T.blocks_css(T.clean_theme(S.apply_to_theme(T.default_theme(), 'glassmorphism')), '', '')
        self.assertIn('--st-bf:blur(18px) saturate(1.5)', glass)
        brut = T.blocks_css(T.clean_theme(S.apply_to_theme(T.default_theme(), 'neo-brutalism')), '', '')
        self.assertIn('--st-card-sh:6px 6px 0 #000', brut)

    def test_unknown_style_is_dropped_and_keep_brand_works(self):
        self.assertNotIn('style', T.clean_theme({'style': 'nope'}))
        base = T.clean_theme({'colors': {'primary': '#112233', 'on_primary': '#fafafa'}})
        kept = S.apply_to_theme(base, 'dark-luxury', keep_brand=True)
        self.assertEqual(kept['colors']['primary'], '#112233')
        self.assertEqual(kept['colors']['bg'], S.STYLES['dark-luxury']['theme']['colors']['bg'])
        self.assertEqual(S.apply_to_theme(base, 'dark-luxury')['colors']['primary'], '#d4af37')

    def test_keep_brand_rebrands_style_css(self):
        th = T.clean_theme(S.apply_to_theme(T.clean_theme({'colors': {'primary': '#126f85'}}), 'bento-grid', keep_brand=True))
        self.assertTrue(th['style_keep'])
        css = T.blocks_css(th, '', '')
        self.assertNotIn('#006cd9', css)
        self.assertNotIn('0,108,217', css)
        self.assertIn('color-mix(in srgb,var(--brand)', css)
        plain = T.blocks_css(T.clean_theme(S.apply_to_theme(T.default_theme(), 'bento-grid')), '', '')
        self.assertIn('rgba(0,108,217', plain)
        self.assertNotIn('style_keep', S.apply_to_theme(th, 'aurora'))
        self.assertNotIn('style_keep', T.clean_theme({'style_keep': True}))
        self.assertEqual(S.css.rebrand_text('a #ff0000 b rgba(255,0,0,.5) c rgba(1,2,3,.5)', '#ff0000'),
                         'a var(--brand) b color-mix(in srgb,var(--brand) 50%,transparent) c rgba(1,2,3,.5)')

    def test_find_by_text_suggests_a_style(self):
        self.assertIn('dark-luxury', S.find_by_text('برند لوکس جواهر مشکی طلایی'))
        self.assertIn('claymorphism', S.find_by_text('خمیری کودک بازیگوش'))

    def test_apply_style_to_page_sets_only_variants(self):
        doc = clean.clean_doc(self.doc(clean.new_block('hero'), clean.new_block('features'), clean.new_block('pricing'), clean.new_block('heading', text='متنِ من')))
        out = S.apply_to_doc(doc, 'swiss')
        by = {b['type']: b for b in out['blocks']}
        self.assertEqual(by['hero']['props']['variant'], 'start')
        self.assertEqual(by['features']['props']['variant'], 'numbered')
        self.assertEqual(by['pricing']['props']['variant'], 'flat')
        self.assertNotIn('variant', by['heading']['props'])
        self.assertEqual(by['hero']['props']['title'], doc['blocks'][0]['props']['title'])      # متن‌ها دست نمی‌خورند
        self.assertEqual(S.clear_doc(out), clean.clean_doc(S.clear_doc(out)))
        self.assertNotIn('variant', S.clear_doc(out)['blocks'][0]['props'])
        self.assertEqual(S.clear_doc(S.apply_to_doc(doc, 'minimalism')), S.clear_doc(doc))

    def test_style_apply_api(self):
        p = self.project('sa1')
        pg = Page.objects.create(project=p, title='ص', slug='x')
        doc = self.doc(clean.new_block('hero'), clean.new_block('features'))
        r = self.c.post(API % p.slug + 'style/apply/', {'style': 'aurora', 'doc': doc, 'apply_layout': True, 'target': 'page', 'page': pg.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d['theme']['style'], 'aurora')
        self.assertEqual(d['theme']['colors']['bg'], '#0b1020')
        self.assertEqual(d['doc']['blocks'][0]['props']['variant'], 'aurora')
        self.assertFalse(Design.objects.filter(project=p).exists(), 'اعمالِ سبک نباید چیزی ذخیره کند')
        self.assertFalse(SiteTheme.objects.filter(project=p, active=True).exists())
        r = self.c.post(API % p.slug + 'style/apply/', {'style': ''}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('style', r.json()['theme'])
        self.assertEqual(self.c.post(API % p.slug + 'style/apply/', {'style': 'nope'}, format='json').status_code, 400)

    def test_theme_roundtrip_keeps_style_and_renders_in_canvas(self):
        p = self.project('sa2')
        pg = Page.objects.create(project=p, title='ص', slug='x')
        th = S.apply_to_theme(T.default_theme(p), 'claymorphism')
        self.assertEqual(self.c.put(API % p.slug + 'theme/', {'theme': th}, format='json').status_code, 200)
        got = self.c.get(API % p.slug + 'theme/').json()['theme']
        self.assertEqual(got['style'], 'claymorphism')
        out = self.c.post(API % p.slug + 'render/', {'target': 'page', 'page': pg.pk, 'doc': self.doc(clean.new_block('hero')), 'theme': got}, format='json').json()
        self.assertIn('--st-card-bd:3px solid #ffffff', out['base_css'])
        self.assertIn('Baloo Bhaijaan 2', out['base_css'])

    def test_theme_options_expose_styles(self):
        opts = T.public_json()
        self.assertEqual([s['key'] for s in opts['styles']], S.ORDER)
        for s in opts['styles']:
            self.assertTrue(s['theme']['colors'] and s['tokens'] and s['label'])
        for f in ('cairo', 'kufi', 'plex', 'amiri', 'baloo'):
            self.assertIn(f, [x['value'] for x in opts['fonts']])


class VariantTests(Base):
    def render(self, *blocks):
        doc = clean.clean_doc(self.doc(*blocks))
        return R.render_doc(doc, self.ctx())

    def test_no_variant_is_byte_identical_to_before(self):
        for btype in V.VARIANTS:
            if btype == 'site_header':
                continue
            b = clean.new_block(btype)
            plain = self.render(b)
            self.assertNotIn('nbv-', plain.html)
            self.assertNotIn('nbc', plain.css)
            with_key = clean.new_block(btype)
            with_key['props']['variant'] = ''
            self.assertEqual(self.render(with_key).html.replace(with_key['id'], 'X'), plain.html.replace(b['id'], 'X'))

    def test_every_variant_renders_class_and_only_its_css(self):
        n = 0
        for btype, (root, rows) in V.VARIANTS.items():
            target = 'header' if btype == 'site_header' else 'page'
            for key in rows:
                b = clean.new_block(btype)
                b['props']['variant'] = key
                doc = clean.clean_doc(self.doc(b), target)
                self.assertEqual(doc['blocks'][0]['props']['variant'], key)
                out = R.render_doc(doc, R.Ctx(target=target))
                self.assertIn('nbv-' + key, out.html, (btype, key))
                self.assertIn(root + '.nbv-' + key, out.css.replace(' ', ''), (btype, key))
                others = [k for k in rows if k != key]
                for o in others:
                    self.assertNotIn('.nbv-%s' % o, out.css, (btype, key, o))
                n += 1
        self.assertGreaterEqual(n, 24)

    def test_unknown_variant_is_dropped_by_cleaner(self):
        b = clean.new_block('hero')
        b['props']['variant'] = 'bogus'
        self.assertNotIn('variant', clean.clean_doc(self.doc(b))['blocks'][0]['props'])
        b['props']['variant'] = 'framed'
        self.assertEqual(clean.clean_doc(self.doc(b))['blocks'][0]['props']['variant'], 'framed')
        plain = clean.clean_doc(self.doc(clean.new_block('hero')))
        self.assertNotIn('variant', plain['blocks'][0]['props'], 'سندِ قدیمی نباید کلیدِ تازه بگیرد')

    def test_catalog_offers_the_variant_field(self):
        cat = {b['type']: b for b in catalog_json()['blocks']}
        for btype in V.VARIANTS:
            f = [x for x in cat[btype]['fields'] if x['key'] == 'variant']
            self.assertEqual(len(f), 1, btype)
            self.assertEqual(f[0]['options'][0]['value'], '')

    def test_variant_survives_ai_roundtrip(self):
        b = clean.new_block('features')
        b['props']['variant'] = 'bento'
        doc = clean.clean_doc(self.doc(b))
        ctx = self.ctx()
        out = R.render_doc(doc, ctx)
        new, report = importer.import_html(out.html, R.page_css(out.css), doc, ctx, 'page')
        self.assertEqual(new['blocks'][0]['type'], 'features')
        self.assertEqual(new['blocks'][0]['props']['variant'], 'bento')
        self.assertEqual(report['custom'], 0)


class ComponentTests(Base):
    def test_registry_size_and_categories(self):
        self.assertGreaterEqual(len(C.COMPONENTS), 30)
        self.assertLessEqual(len(C.COMPONENTS), 60)
        cats = {c['cat'] for c in C.COMPONENTS.values()}
        for need in ('hero', 'features', 'pricing', 'testimonials', 'cta', 'footer', 'navbar', 'cards', 'gallery'):
            self.assertIn(need, cats)
            self.assertGreaterEqual(sum(1 for c in C.COMPONENTS.values() if c['cat'] == need), 3, need)
        pub = C.public_json()
        self.assertEqual(len(pub['items']), len(C.COMPONENTS))
        self.assertEqual(sum(c['count'] for c in pub['categories']), len(C.COMPONENTS))

    def test_every_component_has_source_license_and_author(self):
        from apps.projects.builder.components import provenance as PV
        adapted = 0
        for key, comp in C.COMPONENTS.items():
            src = PV.src_of(comp)
            self.assertIn(src['origin'], ('adapted', 'original'), key)
            self.assertTrue(src['author'] and src['license'], key)
            if src['origin'] == 'adapted':
                adapted += 1
                self.assertIn(src['license'], PV.PERMISSIVE, key)
                self.assertTrue(src['source_url'].startswith('https://github.com/'), key)
                self.assertRegex(src['commit'], r'^[0-9a-f]{40}$', key)
                self.assertTrue(src['copyright'].startswith('Copyright'), key)
                if src['listing_url']:
                    self.assertTrue(src['listing_url'].startswith('https://21st.dev/@'), key)
                lic = open(os.path.join(HERE, 'builder', 'components', src['license_file']), encoding='utf-8').read()
                self.assertIn('MIT License', lic)
                self.assertIn(src['copyright'].replace('Copyright (c) ', ''), lic)
            else:
                self.assertEqual(src['source_url'], '', key)
        self.assertGreaterEqual(adapted, 7)
        meta = C.meta('testi_marquee')
        self.assertEqual(meta['src']['license'], 'MIT')
        self.assertTrue(meta['src']['source_url'])

    def test_checked_listing_data_matches_adapted_components(self):
        """گزارشِ import_sources (صفحهٔ عمومیِ .md ِ 21st.dev): هر قطعهٔ adapted که در 21st.dev هست، مجوزِ mit دارد."""
        path = os.path.join(HERE, 'builder', 'components', 'dataset', 'sources_checked.json')
        self.assertTrue(os.path.isfile(path))
        data = json.load(open(path, encoding='utf-8'))
        self.assertTrue(data['rows'])
        for row in data['rows']:
            self.assertEqual(row['license'].lower(), 'mit', row['listing'])
            self.assertTrue(row['listing'].startswith('https://21st.dev/@dillionverma/components/'))
        self.assertIn('registry', data)

    def test_every_component_renders_in_page_canvas_and_chrome_modes(self):
        eng = engine()
        for key, comp in C.COMPONENTS.items():
            target = comp['root'] if comp['root'] in ('header', 'footer') else 'page'
            b = clean.new_block(C.block_type(key))
            doc = clean.clean_doc(self.doc(b), target)
            for canvas_mode in (False, True):
                out = R.render_doc(doc, R.Ctx(canvas=canvas_mode, target=target))
                self.assertIn('b-' + b['id'], out.html, key)
                self.assertIn(C.class_of(key), out.html, key)
                self.assertNotRegex(out.html, r'data-(s|i|ic|links|lines|h|href|ifc|co|keep|req|alt)=|<!--(each|if)|\[\[|\{\{n\}\}', key)
                eng.from_string('{% load static %}' + out.html)
                self.assertIn('/* قطعه‌های آماده */', out.css, key)
                self.assertIn('.nbc', out.css, key)
            pub = R.render_doc(doc, R.Ctx(canvas=False, target=target))
            self.assertNotIn('data-nb', pub.html, key)
            self.assertNotIn('<script', pub.html, key)

    def test_components_render_right_to_left_safely(self):
        """CSSِ قطعه‌ها با ویژگی‌های منطقی (start/end، inline/block) نوشته شده؛ جهتِ فیزیکی فقط جایی که هندسه است (مثلثِ پخش)."""
        phys = re.compile(r'(?<![\w-])(margin|padding)-(left|right)|text-align:\s*(left|right)|float:\s*(left|right)|(?<![\w-])(left|right)\s*:|border-(left|right)|transform-origin:\s*(left|right)')
        allowed = {'hero_video_thumb': 3, 'feat_bento_showcase': 2}
        for key, comp in C.COMPONENTS.items():
            hits = phys.findall(comp['css'])
            self.assertLessEqual(len(hits), allowed.get(key, 0), '%s: %r' % (key, hits[:4]))
        self.assertNotRegex(C.BASE, r'(?<![\w-])(margin|padding)-(left|right)|text-align:\s*(left|right)')
        # نوارِ متحرک در راست‌به‌چپ جهتِ برعکس دارد و با reduced-motion می‌ایستد
        mq = C.css_for(['testi_marquee'])
        self.assertIn('[dir=rtl] .nbc-mq-track{animation-name:nbc-mq-r}', mq)
        self.assertIn('prefers-reduced-motion', mq)

    def test_component_css_is_scoped_to_nbc_classes(self):
        for key, comp in C.COMPONENTS.items():
            css = re.sub(r'/\*.*?\*/', '', comp['css'], flags=re.S)
            self.assertEqual(css.count('{'), css.count('}'), key)
            flat = re.sub(r'@media[^{]+\{', '', css)
            flat = re.sub(r'@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}', '', flat)
            for sel in re.findall(r'(?:^|\})\s*([^{}@]+)\{', flat):
                for part in sel.split(','):
                    part = part.strip()
                    if part:
                        self.assertRegex(part, r'^(\[dir=rtl\]\s+)?\.nbc', '%s: «%s» بیرون از نامِ‌فضای nbc است' % (key, part))
            self.assertNotIn('</style', css.lower())
            self.assertNotIn('@import', css)
            self.assertNotRegex(css, r'url\(\s*["\']?https?:', key)
        self.assertEqual(C.css_for([]), '')

    def test_hover_revealed_link_is_really_hidden_until_hover(self):
        """خطای دیده‌شده در مرورگر: قاعدهٔ `.nbc a.nbc-link{opacity:.86}` (ویژگیِ ۰،۲،۱) قاعدهٔ `.nbc .nbc-bs-l{opacity:0}` (۰،۲،۰) را می‌برد و
        پیوندِ پنهان از لبهٔ کارت بیرون می‌زد. حالتِ پنهان و حالتِ هاور باید با `a.nbc-link.nbc-bs-l` نوشته شوند."""
        css = C.COMPONENTS['feat_bento_showcase']['css']
        self.assertIn('.nbc a.nbc-link.nbc-bs-l{', css)
        self.assertRegex(css, r'\.nbc a\.nbc-link\.nbc-bs-l\{[^}]*opacity:0')
        self.assertRegex(css, r'a\.nbc-link\.nbc-bs-l\{transform:none;opacity:1\}')
        self.assertIn('.nbc a.nbc-link', C.BASE)       # قاعدهٔ پایه که باید برده شود

    def test_text_slots_are_escaped(self):
        evil = '<img src=x onerror=1>{{x}}{% load y %}'
        for key, comp in C.COMPONENTS.items():
            target = comp['root'] if comp['root'] in ('header', 'footer') else 'page'
            b = clean.new_block(C.block_type(key))
            for k, v in list(b['props'].items()):
                if isinstance(v, str) and v and not re.match(r'^(#|m:)', v):
                    b['props'][k] = evil
                elif isinstance(v, list):
                    for row in v:
                        for rk, rv in list(row.items()):
                            if isinstance(rv, str) and rv and not rv.startswith('#'):
                                row[rk] = evil
            doc = clean.clean_doc(self.doc(b), target)
            html = R.render_doc(doc, R.Ctx(target=target)).html
            self.assertNotIn('<img src=x', html, key)
            self.assertNotIn('{{x}}', html, key)
            self.assertNotIn('{% load y', html, key)

    def test_links_are_sanitized_in_components(self):
        b = clean.new_block(C.block_type('hero_center_glow'))
        b['props']['btn1_link'] = 'javascript:alert(1)'
        b['props']['btn2_link'] = 'page:999999'
        doc = clean.clean_doc(self.doc(b))
        html = R.render_doc(doc, self.ctx()).html
        self.assertNotIn('javascript:', html)

    def test_canvas_marks_text_for_inline_editing_and_publish_does_not(self):
        for key in ('hero_center_glow', 'feat_icon_grid', 'price_three_tier', 'cta_center_box', 'cards_blog', 'testi_cards_grid'):
            b = clean.new_block(C.block_type(key))
            doc = clean.clean_doc(self.doc(b))
            canvas_html = R.render_doc(doc, R.Ctx(canvas=True)).html
            self.assertIn('data-nb-edit="title"', canvas_html, key)
            self.assertIn('data-bid="%s"' % b['id'], canvas_html)
            self.assertNotIn('data-nb', R.render_doc(doc, R.Ctx(canvas=False)).html)
        # ردیف‌ها مسیرِ ویرایشِ درجا دارند
        b = clean.new_block(C.block_type('feat_icon_grid'))
        html = R.render_doc(clean.clean_doc(self.doc(b)), R.Ctx(canvas=True)).html
        self.assertIn('data-nb-edit="items.0.title"', html)
        # نسخهٔ دومِ نوارِ متحرک ویرایشِ درجا ندارد (وگرنه هر متن دو بار ویرایش می‌شد)
        m = clean.new_block(C.block_type('testi_marquee'))
        html = R.render_doc(clean.clean_doc(self.doc(m)), R.Ctx(canvas=True)).html
        twin = html.split('aria-hidden="true"', 1)[1]
        self.assertNotIn('data-nb-edit', twin)
        self.assertGreaterEqual(html.count('data-nb-edit="items.0.text"'), 1)

    def test_css_only_for_components_in_use(self):
        r0 = R.render_doc(clean.clean_doc(self.doc(clean.new_block('hero'))), self.ctx())
        self.assertNotIn('nbc', r0.css)
        doc = clean.clean_doc(self.doc(clean.new_block(C.block_type('hero_center_glow')), clean.new_block(C.block_type('hero_center_glow')),
                                       clean.new_block(C.block_type('faq_two_col'))))
        css = R.render_doc(doc, self.ctx()).css
        self.assertEqual(css.count('.nbc-hero-center-glow{'), 1)
        self.assertIn('.nbc-fq{', css)
        self.assertNotIn('.nbc-price-', css)
        self.assertEqual(css.count('/* قطعه‌های آماده */'), 1)
        # CSSِ مشترکِ نوار فقط وقتی قطعه‌ای از آن استفاده کند
        self.assertNotIn('nbc-mq-track{', css)
        css2 = R.render_doc(clean.clean_doc(self.doc(clean.new_block(C.block_type('logos_marquee')), clean.new_block(C.block_type('testi_marquee')))), self.ctx()).css
        self.assertEqual(css2.count('@keyframes nbc-mq-l'), 1)

    def test_scope_header_footer_and_page(self):
        nav = clean.new_block(C.block_type('nav_classic'))
        self.assertEqual(clean.clean_doc(self.doc(nav), 'header')['blocks'][0]['type'], 'c_nav_classic')
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(nav), 'page')
        foot = clean.new_block(C.block_type('footer_columns'))
        self.assertEqual(clean.clean_doc(self.doc(foot), 'footer')['blocks'][0]['type'], 'c_footer_columns')
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(foot), 'page')
        hero = clean.new_block(C.block_type('hero_split_media'))
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(hero), 'header')
        # قطعه باید مستقیم در صفحه بیاید، نه داخلِ بخش
        sec = clean.new_block('section', children=[clean.new_block(C.block_type('cta_strip'))])
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(sec))

    def test_catalog_lists_components_with_forms(self):
        cat = catalog_json()
        comps = [b for b in cat['blocks'] if b['group'] == 'components']
        self.assertEqual(len(comps), len(C.COMPONENTS))
        self.assertIn('components', [g['value'] for g in cat['groups']])
        self.assertEqual(len(cat['components']['items']), len(C.COMPONENTS))
        for b in comps:
            self.assertTrue(b['fields'] and b['defaults'], b['type'])
            self.assertEqual(b['root'], True)
            self.assertTrue(b['label'] and b['hint'])
            for f in b['fields']:
                self.assertIn(f['kind'], ('text', 'textarea', 'link', 'image', 'icon', 'toggle', 'select', 'items'), (b['type'], f['key']))
                self.assertTrue(f['label'] or f['kind'] == 'items', (b['type'], f['key']))

    def test_default_content_has_no_invented_facts(self):
        """متن‌های نمونه نباید قیمت، آمار یا نامِ واقعی بسازند: عددِ فارسی/لاتین فقط در جای‌نگهدارِ «۰۰»."""
        for key, comp in C.COMPONENTS.items():
            b = clean.new_block(C.block_type(key))
            texts = []
            for v in b['props'].values():
                if isinstance(v, str):
                    texts.append(v)
                elif isinstance(v, list):
                    for row in v:
                        texts += [x for x in row.values() if isinstance(x, str)]
            for t in texts:
                t2 = re.sub(r'۰۰', '', t)
                self.assertNotRegex(t2, r'[0-9۰-۹]', '%s: «%s» عدد دارد' % (key, t))
                self.assertNotRegex(t, r'(?i)adobe|photoshop|premiere', key)

    def test_roundtrip_with_ai_keeps_component_and_merges_text(self):
        for key in ('hero_center_glow', 'feat_icon_grid', 'cta_center_box', 'price_three_tier', 'testi_cards_grid', 'faq_two_col'):
            b = clean.new_block(C.block_type(key))
            doc = clean.clean_doc(self.doc(b))
            ctx = self.ctx()
            out = R.render_doc(doc, ctx)
            same, report = importer.import_html(out.html, R.page_css(out.css), doc, ctx, 'page')
            self.assertEqual(same['blocks'], doc['blocks'], key)
            self.assertEqual(report['custom'], 0, key)
            title = doc['blocks'][0]['props'].get('title') or ''
            if title:
                changed_html = out.html.replace('>%s<' % title, '>عنوانِ تازه<', 1)
                self.assertNotEqual(changed_html, out.html, key)
                new, rep = importer.import_html(changed_html, R.page_css(out.css), doc, ctx, 'page')
                self.assertEqual(new['blocks'][0]['type'], C.block_type(key), key)
                self.assertEqual(new['blocks'][0]['props']['title'], 'عنوانِ تازه', key)
                self.assertEqual(rep['custom'], 0, key)

    def test_component_preview_api(self):
        p = self.project('cp1')
        r = self.c.get(API % p.slug + 'components/hero_split_media/preview/')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertIn('nbc-hero-split-media', d['html'])
        self.assertIn('.nbc-hero-split-media', d['page_css'])
        self.assertEqual(d['src']['origin'], 'original')
        r = self.c.get(API % p.slug + 'components/nav_floating_pill/preview/', {'style': 'glassmorphism'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('nb-header', r.json()['html'])
        self.assertIn('--st-card-bg', r.json()['base_css'])
        self.assertEqual(self.c.get(API % p.slug + 'components/nope/preview/').status_code, 404)
        self.assertEqual(self.c.get(API % p.slug + 'components/cta_strip/preview/', {'style': 'nope'}).status_code, 200)

    def test_new_endpoints_need_staff(self):
        p = self.project('cp2')
        from rest_framework.test import APIClient
        anon, normal = APIClient(), APIClient()
        normal.force_authenticate(self.user)
        for method, sub in (('post', 'style/apply/'), ('get', 'components/cta_strip/preview/'), ('post', 'ai-context/')):
            url = API % p.slug + sub
            self.assertIn(getattr(anon, method)(url, {}, format='json').status_code, (401, 403), sub)
            self.assertEqual(getattr(normal, method)(url, {}, format='json').status_code, 403, sub)
        other = self.project('cp3')
        self.assertEqual(self.c.post(API % other.slug + 'style/apply/', {'style': 'swiss'}, format='json').status_code, 200)
        self.assertEqual(self.c.post('/api/v1/studio/projects/no-such-project/builder/style/apply/', {'style': 'swiss'}, format='json').status_code, 404)


class AiContextTests(Base):
    BRIEFS = ['فروشگاه آنلاین لباس ورزشی', 'اپ مربیگری ورزشی چغر برای مربی‌ها', 'کافهٔ دنج و قهوهٔ تخصصی', 'x' * 3000, '']

    def test_prompt_is_bounded_for_every_style_and_kind(self):
        biggest = 0
        for style in [''] + S.ORDER:
            for kind in ('home', 'about', 'contact', 'static', 'product_list', 'header', 'footer', 'zzz'):
                for brief in self.BRIEFS:
                    payload = ai_context.build(style, brief, kind)
                    size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
                    biggest = max(biggest, size)
                    self.assertLessEqual(size, ai_context.MAX_CHARS, (style, kind))
                    self.assertLessEqual(len(payload['components']), ai_context.MAX_COMPONENTS)
                    self.assertEqual(payload['stats']['chars'], size)
                    seen = [c['cat'] for c in payload['components']]
                    self.assertEqual(len(seen), len(set(seen)), 'از هر دسته یکی')
        self.assertLess(biggest, ai_context.MAX_CHARS)

    def test_whole_library_is_never_sent(self):
        payload = ai_context.build('glassmorphism', 'سایتِ شرکتی', 'home')
        text = json.dumps(payload, ensure_ascii=False)
        sent = {c['key'] for c in payload['components']}
        self.assertLessEqual(len(sent), 5)
        self.assertLess(len(sent), len(C.COMPONENTS) // 5)
        for key in C.COMPONENTS:
            if key not in sent:
                self.assertNotIn('"%s"' % key, text, key)
                self.assertNotIn(C.class_of(key) + ' ', text)
        self.assertNotIn('@media', text)           # CSSِ قطعه‌ها در پرامپت نیست؛ خودمان می‌چسبانیم
        self.assertNotIn('--st-hov', text)
        for c in payload['components']:
            self.assertIn(c['class'], c['html'])
            self.assertLessEqual(len(c['html']), ai_context.MAX_COMPONENT_HTML + 40)
        self.assertEqual(set(payload), {'howto', 'style', 'components', 'stats'})

    def test_pinned_components_come_first_and_are_capped(self):
        keys = ['price_three_tier', 'hero_video_thumb']
        got = [c['key'] for c in ai_context.build('', 'x', 'home', keys)['components']]
        self.assertEqual(got[:2], keys)
        many = ai_context.build('swiss', 'x', 'home', list(C.COMPONENTS)[:40] + ['not-real'])
        self.assertEqual(len(many['components']), ai_context.MAX_COMPONENTS)
        self.assertEqual(ai_context.build('', '', 'home', ['not-real'])['components'][0]['cat'], 'hero')

    def test_selection_follows_style_and_brief(self):
        lux = [c['key'] for c in ai_context.build('dark-luxury', 'برند لوکس', 'home')['components']]
        glass = [c['key'] for c in ai_context.build('glassmorphism', 'برند', 'home')['components']]
        self.assertNotEqual(lux, glass)
        self.assertTrue(any('dark-luxury' in C.COMPONENTS[k]['styles'] for k in lux))

    def test_attach_css_adds_used_components_once(self):
        b1 = clean.new_block(C.block_type('hero_center_glow'))
        b2 = clean.new_block(C.block_type('cta_strip'))
        html = R.render_doc(clean.clean_doc(self.doc(b1, b2)), self.ctx()).html
        css = ai_context.attach_css(html, '.mine{color:red}')
        self.assertIn('.mine{color:red}', css)
        self.assertIn('.nbc-hero-center-glow{', css)
        self.assertIn('.nbc-cta-strip{', css)
        self.assertNotIn('.nbc-price-', css)
        self.assertEqual(ai_context.attach_css(html, css), css)                    # بار دوم چیزی اضافه نمی‌کند
        self.assertEqual(ai_context.attach_css('<p class="x">سلام</p>', 'a{b:c}'), 'a{b:c}')

    def test_styled_base_applies_palette(self):
        base = ai_context.styled_base(':root{--brand:#111111}', 'dark-luxury')
        self.assertEqual(T.effective_colors(base)['primary'], '#d4af37')
        self.assertIn('--st-card-bg', base)
        self.assertEqual(ai_context.styled_base('a{b:c}', 'nope'), 'a{b:c}')

    def test_design_options_api(self):
        r = self.c.get('/api/v1/studio/ai/design-options/')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual([s['key'] for s in d['styles']], S.ORDER)
        self.assertEqual(d['max_components'], ai_context.MAX_COMPONENTS)
        self.assertTrue(all(x['key'] in C.COMPONENTS and x['cat_label'] for x in d['components']))
        self.assertFalse([x for x in d['components'] if C.COMPONENTS[x['key']]['root'] != 'section'])
        self.assertEqual(self.client.get('/api/v1/studio/ai/design-options/').status_code in (401, 403), True)

    def test_context_preview_api(self):
        p = self.project('ac1')
        r = self.c.post(API % p.slug + 'ai-context/', {'style': 'aurora', 'brief': 'اپ ورزشی', 'kind': 'home', 'components': ['cta_strip', 'bad']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        ctx = r.json()['context']
        self.assertEqual(ctx['style']['key'], 'aurora')
        self.assertEqual(ctx['components'][0]['key'], 'cta_strip')
        self.assertLessEqual(ctx['stats']['chars'], ai_context.MAX_CHARS)

    def setup_ai_project(self):
        p = self.project('aip%d' % Project.objects.count())
        pg = Page.objects.create(project=p, title='ص', slug='x', kind='static', body_html='<main><p>قدیمی</p></main>', css='.keep{a:b}')
        return p, pg

    def fake_ai(self, seen):
        hero = '<section class="nb-section nbc nbc-hero-center-glow"><div class="nb-wrap"><h1>تازه</h1></div></section>'

        def fn(payload):
            seen.append(payload)
            return {'summary': 'ok', 'body_html': hero, 'css': '.keep{a:b}', 'header': '', 'footer': '', 'theme_css': ':root{--x:1}'}
        return fn

    def test_ai_page_gets_style_and_small_component_set_and_css_attached(self):
        p, pg = self.setup_ai_project()
        seen = []
        systems = []

        class Rec(MockProvider):
            def complete(self, system, user, json_mode=True):
                systems.append(system)
                return super().complete(system, user, json_mode)

        with mock.patch('apps.ai_engine.services.get_provider', return_value=Rec(self.fake_ai(seen))):
            prop = ai.generate_frontend(p, 'یک سایت برای مربی ورزشی', include_shell=False, page_ids=[pg.pk], design={'style': 'aurora', 'components': ['hero_center_glow']})
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        page_calls = [s for s in seen if s.get('task') == 'page']
        self.assertEqual(len(page_calls), 1)
        d = page_calls[0]['design']
        self.assertEqual(d['style']['key'], 'aurora')
        self.assertLessEqual(len(d['components']), 5)
        self.assertLessEqual(len(json.dumps(d, ensure_ascii=False)), ai_context.MAX_CHARS)
        self.assertIn('design.components', systems[-1])
        ch = {c.target: c for c in prop.changes.all()}
        self.assertIn('page_css', ch)
        self.assertIn('.nbc-hero-center-glow{', ch['page_css'].new_content)
        self.assertIn('.keep{a:b}', ch['page_css'].new_content)

    def test_without_design_the_ai_request_is_unchanged(self):
        p, pg = self.setup_ai_project()
        seen = []
        with mock.patch('apps.ai_engine.services.get_provider', return_value=MockProvider(self.fake_ai(seen))):
            prop = ai.generate_frontend(p, 'سایت', include_shell=False, page_ids=[pg.pk])
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        self.assertNotIn('design', seen[0])
        self.assertFalse(prop.changes.filter(target='page_css').exists(), 'بی‌سبک CSSِ صفحه دست نمی‌خورد')

    def test_ai_shell_gets_style_tokens_only_and_palette_is_applied(self):
        p, pg = self.setup_ai_project()
        seen = []
        with mock.patch('apps.ai_engine.services.get_provider', return_value=MockProvider(self.fake_ai(seen))):
            prop = ai.generate_frontend(p, 'سایت', include_shell=True, page_ids=[], design={'style': 'dark-luxury', 'components': ['cta_strip']})
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        shell = [s for s in seen if s.get('task') == 'shell'][0]
        self.assertEqual(set(shell['design']), {'style'})
        css = prop.changes.get(target='shared_css').new_content
        self.assertIn('--brand: #d4af37', css)

    def test_edit_page_with_design_and_api_params(self):
        p, pg = self.setup_ai_project()
        seen = []
        with mock.patch('apps.ai_engine.services.get_provider', return_value=MockProvider(self.fake_ai(seen))), \
                mock.patch('apps.ai_engine.models.AiSettings.is_ready', new_callable=mock.PropertyMock, return_value=True):
            r = self.c.post('/api/v1/studio/projects/%s/ai/page/%d/' % (p.slug, pg.pk),
                            {'instruction': 'ظاهر را حرفه‌ای کن', 'style': 'swiss', 'components': ['cta_strip', 'nope']}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = seen[-1]['design']
        self.assertEqual(d['style']['key'], 'swiss')
        self.assertEqual(d['components'][0]['key'], 'cta_strip')
        self.assertTrue(all(c['key'] in C.COMPONENTS for c in d['components']))


class PublishStyledSiteTests(Base):
    """انتشارِ واقعی: سبک و قطعه‌ها تا فایل‌های سایتِ تولیدشده و اجرای آن می‌رسند."""

    def run_site(self, p, script):
        from apps.code_generation import services
        r = services._run(p, ['manage.py', 'shell', '-c', script], 120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout

    def test_styled_site_with_components_end_to_end(self):
        p = self.project('stz1')
        page = Page.objects.get(pk=self.c.post(API % p.slug + 'pages/', {'starter': 'home', 'title': 'خانه', 'setup_chrome': False}, format='json').json()['page']['id'])
        theme = S.apply_to_theme(T.default_theme(p), 'glassmorphism')
        self.assertEqual(self.c.put(API % p.slug + 'theme/', {'theme': theme}, format='json').status_code, 200)
        hero = clean.new_block(C.block_type('hero_center_glow'), title='تیترِ آزمون', btn1='دکمهٔ من')
        feat = clean.new_block('features', variant='bento')
        doc = self.doc(hero, feat, clean.new_block(C.block_type('price_three_tier')))
        r = self.c.post(API % p.slug + 'publish/', {'target': 'page', 'page': page.pk, 'doc': doc}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'], r.json().get('technical'))
        # سربرگ و پابرگِ قطعه‌ای
        nav = self.doc(clean.new_block(C.block_type('nav_floating_pill'), btn='تماس'))
        self.assertEqual(self.c.post(API % p.slug + 'publish/', {'target': 'header', 'doc': nav}, format='json').status_code, 200)
        foot = self.doc(clean.new_block(C.block_type('footer_columns'), about='معرفیِ آزمون'))
        self.assertEqual(self.c.post(API % p.slug + 'publish/', {'target': 'footer', 'doc': foot}, format='json').status_code, 200)
        root = str(p.path)
        blocks_css = open(os.path.join(root, 'static/css/blocks.css'), encoding='utf-8').read()
        self.assertIn('--st-card-bg:rgba(255,255,255,.55)', blocks_css)
        self.assertIn('font-family:"Cairo"', blocks_css)
        self.assertNotIn('http', blocks_css.split('.nb-wrap')[0])
        for f in ('cairo-arabic-wght-normal.woff2', 'vazirmatn-arabic-wght-normal.woff2'):
            self.assertTrue(os.path.isfile(os.path.join(root, 'static/fonts', f)), f)
        page.refresh_from_db()
        self.assertIn('nbc-hero-center-glow', page.body_html)
        self.assertIn('nbv-bento', page.body_html)
        self.assertIn('.nbc-hero-center-glow{', page.css)
        self.assertIn('.nb-features.nbv-bento .nb-grid', page.css)
        self.assertIn('nbc-nav-floating-pill', SharedPart.objects.get(project=p, kind='header').content)
        self.assertIn('nbc-footer-columns', SharedPart.objects.get(project=p, kind='footer').content)
        self.assertIn('.nbc-nav-floating-pill', open(os.path.join(root, 'static/css/blocks.css'), encoding='utf-8').read())
        out = self.run_site(p, '''
from django.test import Client
html = Client(HTTP_HOST='localhost').get('/').content.decode()
assert 'dir="rtl"' in html, html[:300]
assert 'تیترِ آزمون' in html and 'nbc-nav-floating-pill' in html and 'nbc-footer-columns' in html, html[:900]
assert 'nbc-price-three-tier' in html and 'معرفیِ آزمون' in html
print('SITE_OK')
''')
        self.assertIn('SITE_OK', out)
        # همان صفحه روی بوم با همان سبک
        cv = self.c.post(API % p.slug + 'render/', {'target': 'page', 'page': page.pk, 'doc': doc}, format='json').json()
        self.assertIn('--st-card-bg:rgba(255,255,255,.55)', cv['base_css'])
        self.assertIn('nbc-nav-floating-pill', cv['header'])
        self.assertIn('nbc-footer-columns', cv['footer'])
        self.assertIn('.nbc-hero-center-glow{', cv['page_css'])


class ChagherDraftTests(Base):
    """پیش‌نویسِ صفحهٔ فرودِ چغر: فقط از واقعیت‌های برند، با هر ۱۴ سبک بی‌خطا، و فقط پیش‌نویس."""

    def test_draft_renders_with_every_style_without_warnings(self):
        from apps.projects.builder import chagher_draft as D
        for style in S.ORDER:
            parts = D.build(style)
            self.assertEqual(parts['theme']['style'], style)
            self.assertEqual(parts['theme']['colors']['primary'], '#126f85', style)
            self.assertEqual(parts['theme']['font_head'], 'vazirmatn')
            for target in ('header', 'page', 'footer'):
                out = R.render_doc(parts[target], R.Ctx(target=target, theme=parts['theme']['colors']))
                self.assertTrue(out.html.strip(), (style, target))
                self.assertEqual([w['text'] for w in out.warnings if 'نشده' not in w['text']], [], (style, target))
            html = D.static_page(parts)
            self.assertIn('dir="rtl"', html)
            self.assertIn('--st-card-bg', html)
            self.assertNotIn('{%', html)
            self.assertNotIn('{{', html)
            self.assertNotIn('<script', html)
            self.assertEqual(html.count('<h1'), 1)

    def test_draft_uses_only_brand_facts(self):
        from apps.projects.builder import chagher_draft as D
        parts = D.build()
        texts = []

        def walk(v):
            if isinstance(v, str):
                texts.append(v)
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        for target in ('header', 'page', 'footer'):
            walk([b['props'] for b in parts[target]['blocks']])
        joined = ' '.join(texts)
        facts = open(os.path.join(HERE, '..', '..', '..', 'docs', 'chagher', 'brand-facts-fa.md'), encoding='utf-8').read()
        self.assertIn(D.BRAND['slogan'], facts)
        self.assertIn(D.BRAND['slogan'], joined)
        for banned in ('٪', '%', '۹۸', '+۵۰۰', '۲۴/۷', 'تومان', 'قیمت', 'تضمین', 'ضمانت', 'درمان', 'لاغری', 'رضایت', 'جایگزینِ مربی است'):
            self.assertNotIn(banned, joined.replace('جایگزینِ مربی است؟', ''), banned)
        digits = re.findall(r'[0-9۰-۹][0-9۰-۹٬,]*', joined.replace('https://panel.chagher.ir', '').replace('https://chagher.ir', ''))
        self.assertEqual(digits, ['۱٬۳۰۰'], 'تنها عددِ مجاز «بیش از ۱٬۳۰۰ حرکت» است (از واقعیت‌های برند)')
        for must in ('کمتر از یک دقیقه', 'تصمیمِ نهایی', 'پیش‌نویس', 'بدونِ کارتِ اعتباری', 'PDF'):
            self.assertIn(must, joined)
        self.assertNotRegex(joined, r'(?i)adobe|photoshop|premiere')
        self.assertEqual(parts['theme']['colors']['primary'], D.BRAND['primary'].lower())

    def test_create_draft_is_draft_only_and_idempotent(self):
        from apps.projects.builder import chagher_draft as D
        p, created = D.create_draft('chg-test')
        self.assertTrue(created)
        self.assertFalse(SiteTheme.objects.get(project=p).active)
        self.assertEqual(Design.objects.filter(project=p).count(), 3)
        for d in Design.objects.filter(project=p):
            self.assertTrue(d.draft['blocks'])
            self.assertFalse(d.published)
        page = p.pages.get()
        self.assertEqual(page.body_html, '')
        self.assertEqual(SharedPart.objects.filter(project=p).count(), 0)
        again, created2 = D.create_draft('chg-test')
        self.assertFalse(created2)
        self.assertEqual(again.pk, p.pk)
        # ویرایشگر همین را باز می‌کند
        pg = p.pages.get()
        d = self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': pg.pk}).json()
        self.assertEqual(d['theme']['style'], 'bento-grid')
        self.assertEqual(d['doc']['blocks'][0]['type'], 'c_hero_center_glow')
        cv = self.c.post(API % p.slug + 'render/', {'target': 'page', 'page': pg.pk, 'doc': d['doc'], 'theme': d['theme']}, format='json').json()
        self.assertIn('nbc-hero-center-glow', ''.join(x['html'] for x in cv['parts']))
        self.assertIn('nbc-nav-classic', cv['header'])
        self.assertIn('nbc-footer-columns', cv['footer'])

    def test_management_command_writes_preview_and_fonts(self):
        import tempfile
        from django.core.management import call_command
        out = os.path.join(tempfile.mkdtemp(prefix='chg-'), 'draft.html')
        self.addCleanup(__import__('shutil').rmtree, os.path.dirname(out), True)
        call_command('chagher_landing_draft', '--slug', 'chg-cmd', '--style', 'aurora', '--html', out, stdout=__import__('io').StringIO())
        html = open(out, encoding='utf-8').read()
        self.assertIn('برنامهٔ ورزشی و غذاییِ هر ورزشکار', html)
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(out), 'fonts', 'vazirmatn-arabic-wght-normal.woff2')))
        self.assertTrue(Project.objects.filter(slug='chg-cmd').exists())
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('chagher_landing_draft', '--style', 'nope', stdout=__import__('io').StringIO())


class SelfTestModuleTests(Base):
    """آزمونِ خودکارِ سرورِ پردازش برای ویژگی: ثبت‌شده، بسته‌اش کوچک، و سنجشش درست قضاوت می‌کند."""

    class FakeCtx:
        def __init__(self, response):
            self.response = response

        def installed_ollama(self):
            return ['qwen3:8b', 'qwq:32b']

        def read_json(self, job, name):
            return {'response': self.response} if self.response is not None else None

        def meta(self, job):
            return {'device': 'cuda'}

    class FakeJob:
        payload = {'model': 'qwen3:8b'}

    def test_registered_and_spec_is_small(self):
        from apps.compute import selftests as ST
        reg = ST.load_all(force=True)
        self.assertIn('site_styles_ai', reg)
        self.assertIn('site_styles_render', reg)
        t = reg['site_styles_ai']
        self.assertEqual(t.kind, 'ollama.generate')
        self.assertTrue(t.gpu_required)
        spec = t.build(self.FakeCtx(''))
        self.assertEqual(spec.kind, 'ollama.generate')
        self.assertEqual(spec.payload['model'], 'qwen3:8b')          # مدلِ خودِ مالک؛ چیزی عوض نمی‌شود
        self.assertLess(len(spec.payload['prompt']), ai_context.MAX_CHARS + 1500)
        self.assertIn('nbc-hero-center-glow', spec.payload['prompt'])
        self.assertNotIn('"key":"price_three_tier"', spec.payload['prompt'])

    def test_virtual_render_check_passes(self):
        from apps.compute import selftests as ST
        v = ST.load_all()['site_styles_render'].virtual(self.FakeCtx(''))
        self.assertTrue(v.ok, v.detail)

    def test_check_judges_the_model_answer(self):
        from apps.compute import selftests as ST
        t = ST.load_all()['site_styles_ai']
        good = ('<section class="nb-section nbc nbc-hero-center-glow"><div class="nb-wrap"><h1>با چغر چغرتر شو</h1>'
                '<p>دستیار هوش مصنوعیِ مربی‌ها؛ پیش‌نویسِ برنامه را می‌سازد و تصمیمِ نهایی با مربی است.</p></div></section>' + ' ' * 10)
        self.assertTrue(t.check(self.FakeCtx(good), self.FakeJob()).ok)
        for bad in ('', 'short', '<p>' + 'hello world ' * 20 + '</p>', good + '<script>1</script>', '<section class="x">' + 'متنِ فارسیِ بدونِ هیچ قطعه‌ای ' * 6 + '</section>'):
            self.assertFalse(t.check(self.FakeCtx(bad), self.FakeJob()).ok, bad[:30])
        self.assertFalse(t.check(self.FakeCtx(None), self.FakeJob()).ok)


class RepoLayoutTests(SimpleTestCase):
    """پوشه‌ای به نامِ data/ یا logs/ در بسته‌ها هم .gitignore ِ پروژه آن را نادیده می‌گیرد و هم git-autopush.sh آن را به مخزنِ عمومی نمی‌فرستد
    (مجوزها و دادهٔ سبک‌ها بی‌صدا گم می‌شدند). داده‌های سایت‌ساز در dataset/ هستند."""

    def test_builder_has_no_folder_the_repo_ignores(self):
        root = os.path.join(HERE, 'builder')
        bad = []
        for dirpath, dirnames, _files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            bad += [os.path.join(dirpath, d) for d in dirnames if d in ('data', 'logs', 'venv', 'node_modules')]
        self.assertEqual(bad, [], 'این پوشه‌ها به مخزن نمی‌روند؛ اسمشان را عوض کن')

    def test_license_and_data_files_exist_where_the_code_reads_them(self):
        for rel in ('styles/dataset/uiux_pro_max.json', 'styles/dataset/LICENSE-ui-ux-pro-max-skill.txt',
                    'components/dataset/sources_checked.json', 'components/dataset/LICENSE-magicui.txt'):
            self.assertTrue(os.path.isfile(os.path.join(HERE, 'builder', rel)), rel)

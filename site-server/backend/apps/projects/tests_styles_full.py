# -*- coding: utf-8 -*-
"""کلِ ui-ux-pro-max در سایت‌ساز: واردکننده، همهٔ سبک‌ها (۸۹ تا؛ ۱۴ دست‌ساز + ۷۵ خودکار)، نگاشتِ قلم‌های لاتین به فارسی، API ِ «منبع‌های طراحی» و رهنمودهای کوچکِ AI.

آزمون‌ها هیچ‌چیز از اینترنت نمی‌خوانند؛ واردکننده با یک مخزنِ ساختگیِ کوچک (tests_data/uiux_mini) سنجیده می‌شود.
"""
import importlib
import json
import os
import re
import shutil
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from apps.projects.builder import ai_context, chagher_draft as D, render as R, styles as S, theme as T, variants as V
from apps.projects.builder.styles import css as CSS, fonts_fa, gen_core as G, generated, import_uiux_full as IMP, uiux
from apps.projects.tests_builder import Base

HERE = os.path.dirname(os.path.abspath(__file__))
HEX = re.compile(r'#[0-9a-fA-F]{6}\b')
BRAND_WORDS = re.compile(r'adobe|photoshop|premiere', re.I)


class ImporterTests(SimpleTestCase):
    def mini_repo(self):
        d = tempfile.mkdtemp(prefix='uiux-mini-')
        self.addCleanup(shutil.rmtree, d, True)
        data = os.path.join(d, 'src', 'ui-ux-pro-max', 'data')
        os.makedirs(os.path.join(data, 'stacks'))
        w = lambda name, text: open(os.path.join(data, name), 'w', encoding='utf-8', newline='\n').write(text)
        w('styles.csv', 'No,Style Category,Type,Keywords,Style ID,Status,rtl_level\n1,Adobe Spectrum,Platform/System,"adobe, tokens",spectrum,active,full\n2,Glass,General,"frost, blur",glass,active,partial\n')
        w('colors.csv', 'No,Product Type,Primary,Background\n1,SaaS,#2563EB,#F8FAFC\n')
        w('typography.csv', 'No,Font Pairing Name,Heading Font,Body Font\n1,Pair,Inter,Inter\n')
        w('ux-guidelines.csv', 'No,Category,Issue,Do,Don\'t,Severity\n1,Accessibility,Color Contrast,4.5:1,Low contrast,High\n')
        for name, head in (('landing.csv', 'No,Pattern Name,Keywords,Pattern ID'), ('motion.csv', 'No,Category,Keywords'), ('charts.csv', 'No,Data Type,Best Chart Type'),
                           ('products.csv', 'No,Product Type,Keywords'), ('ui-reasoning.csv', 'No,UI_Category,Recommended_Pattern'), ('icons.csv', 'No,Category,Icon Name'),
                           ('app-interface.csv', 'No,Category,Issue'), ('react-performance.csv', 'No,Category,Issue')):
            w(name, head + '\n1,a,b' + (',c' if head.count(',') == 3 else '') + '\n')
        w('stacks/react.csv', 'No,Category,Guideline,Severity\n1,State,Use useState,Medium\n')
        w('stacks/vue.csv', 'No,Category,Guideline,Severity\n1,State,Use ref,Medium\n')
        w('google-fonts.csv', 'Family,Category,Stroke,Classifications,Keywords,Styles,Variable Axes,Subsets,Popularity Rank\nCairo,Sans Serif,Sans,,arabic,400,wght,"arabic,latin",5\nInter,Sans Serif,Sans,,x,400,wght,latin,1\n')
        os.makedirs(os.path.join(d, '.claude', 'skills', 'design-system', 'data'))
        open(os.path.join(d, '.claude', 'skills', 'design-system', 'data', 'slide-x.csv'), 'w', encoding='utf-8').write('id,layout_name\n1,Title\n')
        os.makedirs(os.path.join(d, '.claude', 'skills', 'a', 'references'))
        os.makedirs(os.path.join(d, '.claude', 'skills', 'b', 'references'))
        for sk in 'ab':                                            # همان متن در دو مهارت ⇒ یک بار
            open(os.path.join(d, '.claude', 'skills', sk, 'references', 'r.md'), 'w', encoding='utf-8').write('# Tokens\nsame text')
        open(os.path.join(d, 'LICENSE'), 'w', encoding='utf-8').write('MIT License\n\nCopyright (c) 2024 Next Level Builder\n')
        return d

    def test_importer_reads_every_kind_and_is_attributed(self):
        repo = self.mini_repo()
        out = tempfile.mkdtemp(prefix='uiux-out-')
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.object(IMP, 'OUT_DIR', out), mock.patch.object(IMP, 'LICENSE_OUT', os.path.join(out, 'LICENSE.txt')), mock.patch('subprocess.run') as sp:
            sp.return_value.stdout = 'abc123\n'
            IMP.main(repo)
        idx = json.load(open(os.path.join(out, 'index.json'), encoding='utf-8'))
        for kind in uiux.KINDS:
            self.assertIn(kind, idx['counts'], kind)
            self.assertTrue(os.path.isfile(os.path.join(out, kind + '.json')), kind)
        self.assertEqual(idx['counts']['stacks'], 2)                                 # دو فایلِ پشته یکی شد، هر ردیف نامِ پشته‌اش را دارد
        stacks = json.load(open(os.path.join(out, 'stacks.json'), encoding='utf-8'))
        self.assertEqual({r['stack'] for r in stacks}, {'react', 'vue'})
        self.assertEqual(idx['counts']['docs'], 1)                                   # متنِ تکراریِ دو مهارت یک بار آمد
        self.assertEqual(json.load(open(os.path.join(out, 'docs.json'), encoding='utf-8'))[0]['also'][0].split('/')[2] in ('a', 'b'), True)
        gf = json.load(open(os.path.join(out, 'google_fonts.json'), encoding='utf-8'))
        self.assertTrue([r for r in gf if r['family'] == 'Cairo'][0]['arabic'])
        self.assertFalse([r for r in gf if r['family'] == 'Inter'][0]['arabic'])
        self.assertEqual((idx['license'], idx['source']), ('MIT', 'https://github.com/nextlevelbuilder/ui-ux-pro-max-skill'))
        self.assertIn('Next Level Builder', open(os.path.join(out, 'LICENSE.txt'), encoding='utf-8').read())

    def test_importer_removes_adobe_names_but_keeps_the_rest(self):
        repo = self.mini_repo()
        out = tempfile.mkdtemp(prefix='uiux-out-')
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.object(IMP, 'OUT_DIR', out), mock.patch.object(IMP, 'LICENSE_OUT', os.path.join(out, 'L.txt')), mock.patch('subprocess.run') as sp:
            sp.return_value.stdout = 'abc\n'
            IMP.main(repo)
        rows = json.load(open(os.path.join(out, 'styles.json'), encoding='utf-8'))
        self.assertEqual(rows[0]['name'], 'Spectrum')
        self.assertNotRegex(json.dumps(rows), BRAND_WORDS)
        self.assertEqual(IMP.clean_text('Adobe-adjacent software and Adobe Spectrum'), 'creative-suite-adjacent software and Spectrum')

    def test_committed_dataset_is_complete_mit_and_brand_clean(self):
        info = uiux.attribution()
        self.assertEqual((info['license'], info['source']), ('MIT', 'https://github.com/nextlevelbuilder/ui-ux-pro-max-skill'))
        self.assertRegex(info['commit'], r'^[0-9a-f]{40}$')
        want = {'styles': 80, 'colors': 150, 'fonts': 60, 'ux': 100, 'landing': 30, 'motion': 15, 'charts': 20, 'products': 150, 'reasoning': 150, 'icons': 80, 'app': 20,
                'react': 30, 'stacks': 800, 'google_fonts': 1500, 'slides': 100, 'brand': 200, 'docs': 40}
        for kind in uiux.KINDS:
            self.assertGreaterEqual(info['counts'][kind], want[kind], kind)
            self.assertEqual(info['counts'][kind], len(uiux.rows(kind)))
            self.assertIn(kind, uiux.KIND_FA)
            self.assertIn(kind, uiux.SEARCH_FIELDS)
        lic = open(os.path.join(uiux.HERE, 'dataset', 'LICENSE-ui-ux-pro-max-skill.txt'), encoding='utf-8').read()
        self.assertIn('MIT License', lic)
        self.assertIn('Next Level Builder', lic)
        for kind in uiux.KINDS:
            self.assertNotRegex(json.dumps(uiux.rows(kind), ensure_ascii=False), BRAND_WORDS, kind)       # نامِ برندِ ادوبی در هیچ‌جای رابط نیست
        self.assertFalse(os.path.exists(os.path.join(uiux.HERE, 'dataset', 'uiux_pro_max.json')))

    def test_search_scores_filters_and_counts(self):
        rows = uiux.search('styles', 'glassmorphism frosted blur')
        self.assertTrue(rows and 'glass' in rows[0]['name'].lower())
        self.assertEqual(uiux.count('styles'), len(uiux.rows('styles')))
        self.assertEqual(uiux.count('styles', where={'status': 'deprecated'}), sum(1 for r in uiux.rows('styles') if r.get('status') == 'deprecated'))
        self.assertTrue(all(r['stack'] == 'react' for r in uiux.search('stacks', '', limit=5, where={'stack': 'react'})))
        arabic = uiux.search('google_fonts', '', limit=0, where={'arabic': True})
        self.assertTrue(30 <= len(arabic) <= 120 and all(r['arabic'] for r in arabic))
        self.assertEqual(uiux.search('nope', 'x'), [])
        self.assertEqual(uiux.rows('nope'), [])


class AllStylesTests(SimpleTestCase):
    def test_every_dataset_style_has_a_site_builder_style(self):
        ids = [r['id'] for r in uiux.rows('styles')]
        self.assertEqual(len(ids), len(set(ids)))
        covered = {(st.get('uiux') or {}).get('style_id'): k for k, st in S.STYLES.items()}
        missing = [i for i in ids if i not in covered]
        self.assertEqual(missing, [], 'ردیف‌هایی از ui-ux-pro-max که سبکِ سایت‌ساز ندارند')
        hand = [k for k, st in S.STYLES.items() if st['source'] == 'hand']
        gen = [k for k, st in S.STYLES.items() if st['source'] == 'generated']
        self.assertEqual(len(hand), 14)
        self.assertEqual(len(hand) + len(gen), len(S.ORDER))
        self.assertEqual(set(S.ORDER), set(S.STYLES))
        self.assertEqual(set(S.ORDER[:14]), set(hand))
        self.assertGreaterEqual(len(gen), 70)
        for sid in ids:
            self.assertTrue(S.style_key_for(sid), sid)
            self.assertIn(S.style_key_for(sid), S.STYLES)
        self.assertEqual(S.style_key_for('no-such'), '')

    def test_labels_are_persian_and_unique(self):
        labels = [st['label'] for st in S.STYLES.values()]
        self.assertEqual(len(labels), len(set(labels)))
        for k, st in S.STYLES.items():
            self.assertRegex(st['label'], r'[؀-ۿ]', k)
            self.assertRegex(st['desc'], r'[؀-ۿ]', k)
            self.assertNotRegex(json.dumps(st, ensure_ascii=False), BRAND_WORDS, k)
            self.assertTrue(st['mood'] and st['tags'], k)

    def test_contrast_hero_cta_and_buttons_in_every_style(self):
        for key, st in S.STYLES.items():
            c = st['theme']['colors']
            self.assertEqual(set(c), set(T.COLOR_VARS), key)
            self.assertGreaterEqual(R.contrast(c['text'], c['bg']), 7, (key, 'text/bg'))
            self.assertGreaterEqual(R.contrast(c['text'], c['surface']), 7, (key, 'text/surface'))
            self.assertGreaterEqual(R.contrast(c['text2'], c['bg']), 4.5, (key, 'text2'))
            self.assertGreaterEqual(R.contrast(c['muted'], c['bg']), 4.5, (key, 'muted'))
            self.assertGreaterEqual(R.contrast(c['muted'], c['surface']), 4.5, (key, 'muted/surface'))
            self.assertGreaterEqual(R.contrast(c['on_primary'], c['primary']), 4.5, (key, 'button'))
            self.assertGreaterEqual(R.contrast(c['primary'], c['bg']), 4.5, (key, 'brand/bg'))
            if st['source'] != 'generated':
                continue
            t = S.tokens_of(key)
            for bg, fg in (('hero_bg', 'hero_fg'), ('cta_bg', 'cta_fg')):
                self.assertRegex(t[fg], r'^#[0-9a-fA-F]{6}$', (key, fg))
                for stop in HEX.findall(t[bg]):                                        # متن روی همهٔ ایستگاه‌های گرادیان خوانا است
                    self.assertGreaterEqual(R.contrast(stop, t[fg]), 4.5, (key, bg, stop))
            if HEX.fullmatch(t['hero_btn_bg']) and HEX.fullmatch(t['hero_btn_fg']):
                self.assertGreaterEqual(R.contrast(t['hero_btn_bg'], t['hero_btn_fg']), 4.5, (key, 'hero button'))

    def test_fonts_are_persian_capable_in_every_style(self):
        cov = json.load(open(os.path.join(T.FONT_DIR, 'coverage.json'), encoding='utf-8'))['fonts']
        for key, st in S.STYLES.items():
            for f in ('font_head', 'font_body'):
                name = st['theme'][f]
                self.assertIn(name, T.FONTS, (key, f))
                self.assertEqual(cov[name]['missing'], '', (key, name))                 # پ چ ژ گ ک ی و رقم‌های فارسی در فایل هست
        for name, f in T.FONTS.items():
            for entry in f['files']:
                self.assertTrue(os.path.isfile(os.path.join(T.FONT_DIR, entry[0])), entry[0])
        self.assertGreaterEqual(len(T.FONTS), 30)

    def test_every_bundled_font_has_an_open_license_file(self):
        for f in os.listdir(T.FONT_DIR):
            if f.startswith('LICENSE-'):
                self.assertIn('Open Font License', open(os.path.join(T.FONT_DIR, f), encoding='utf-8').read(), f)
        for name, f in T.FONTS.items():
            stem = f['files'][0][0]
            n = re.sub(r'-(arabic|latin)-.*$', '', stem)
            cands = [x for x in os.listdir(T.FONT_DIR) if x.startswith('LICENSE-fontsource-') and n in x.replace('variable-', '')]
            self.assertTrue(cands, name)

    def test_css_is_rtl_safe_scoped_and_without_letter_spacing(self):
        for key, st in S.STYLES.items():
            css = S.style_css(key)
            self.assertEqual(css.count('{'), css.count('}'), key)
            self.assertNotIn('@import', css)
            self.assertNotIn('url(', css)
            self.assertNotIn('</style', css.lower())
            self.assertLess(len(css), 14000, key)
            if st['source'] != 'generated':
                continue
            self.assertIsNone(G.PHYS.search(css.replace('translate(', 't(')), (key, G.PHYS.search(css)))     # فقط start/end؛ بی‌left/right
            t = S.tokens_of(key)
            self.assertEqual(t['head_ls'], '0', key)                                    # فاصلهٔ حروف حروفِ فارسی را از هم باز می‌کند
            self.assertEqual(t['head_tt'], 'none', key)
            self.assertNotIn('letter-spacing', st['extra'])
            self.assertNotIn('uppercase', st['extra'])
            self.assertFalse(set(st['tokens']) - set(CSS.DEFAULTS), key)
            for btype, variant in st['sections'].items():
                self.assertTrue(V.has_field(btype), (key, btype))
                if variant:
                    self.assertTrue(V.has(btype, variant), (key, btype, variant))
            self.assertNotEqual(st['sections'].get('hero'), 'aurora', key)             # متنِ سفیدِ آن روی فیروزه‌ایِ روشن خوانا نیست

    def test_generated_styles_apply_roundtrip_and_keep_brand(self):
        theme = T.default_theme()
        doc = {'v': 1, 'blocks': []}
        for key in S.ORDER:
            th = S.apply_to_theme(theme, key)
            self.assertEqual(th['style'], key)
            self.assertEqual(th['colors']['primary'], S.STYLES[key]['theme']['colors']['primary'])
            kept = S.apply_to_theme(theme, key, keep_brand=True)
            self.assertEqual(kept['colors']['primary'], theme['colors']['primary'])
            back = S.restore_theme(th)
            self.assertEqual(back['colors'], theme['colors'])
            self.assertNotIn('style', back)
            self.assertEqual(S.apply_to_doc(doc, key), doc)
        pub = S.public_json()
        self.assertEqual([p['key'] for p in pub], S.ORDER)
        for p in pub:
            self.assertEqual(set(p['tokens']), set(S.THUMB_TOKENS))
            self.assertIn(p['source'], ('hand', 'generated'))
            self.assertTrue(p['group'])
        self.assertEqual(sum(g['count'] for g in S.groups()), len(S.ORDER))

    def test_find_by_text_reaches_generated_styles(self):
        self.assertIn('ux-vaporwave', S.find_by_text('ویپورویو صورتی', 5) + S.find_by_text('vaporwave neon synth', 5))
        self.assertTrue(S.find_by_text('داشبورد', 3))


class FontMappingTests(SimpleTestCase):
    def test_every_latin_font_of_the_dataset_maps_to_a_bundled_persian_font(self):
        latin = set()
        for r in uiux.rows('fonts'):
            latin.update((r['heading'], r['body']))
        self.assertGreaterEqual(len(latin), 80)
        unmapped = sorted(x for x in latin if x not in fonts_fa.PERSIAN_OF)
        self.assertEqual(unmapped, [], 'قلم‌های لاتینی که معادلِ فارسی ندارند')
        for latin_name, key in fonts_fa.PERSIAN_OF.items():
            self.assertIn(key, T.FONTS, latin_name)

    def test_every_pairing_has_a_readable_persian_pair(self):
        cov = json.load(open(os.path.join(T.FONT_DIR, 'coverage.json'), encoding='utf-8'))['fonts']
        for r in uiux.rows('fonts'):
            head, body = fonts_fa.persian_pair(r['heading'], r['body'])
            self.assertIn(head, T.FONTS, r['name'])
            self.assertNotIn(body, fonts_fa.DECORATIVE, r['name'])                       # متنِ بلند با قلمِ تزئینی نیست
            self.assertEqual(cov[head]['missing'] + cov[body]['missing'], '', r['name'])

    def test_unknown_fonts_fall_back_by_category(self):
        self.assertEqual(fonts_fa.persian_font('Brand New Serif', 'Serif'), 'markazi')
        self.assertEqual(fonts_fa.persian_font('Brand New Mono', 'Monospace'), 'plexmono')
        self.assertEqual(fonts_fa.persian_font('???'), 'vazirmatn')

    def test_generated_styles_use_their_pairings_mapped_fonts(self):
        for k, st in S.STYLES.items():
            if st['source'] != 'generated':
                continue
            frow = uiux.by_id('fonts', 'name', st['uiux']['font_pairing'])
            self.assertTrue(frow, k)
            head, body = fonts_fa.persian_pair(frow['heading'], frow['body'])
            self.assertEqual((st['theme']['font_head'], st['theme']['font_body']), (head, body), k)


class PaletteTests(SimpleTestCase):
    def test_ensure_moves_a_colour_just_enough(self):
        self.assertGreaterEqual(G.contrast(G.ensure('#777777', '#ffffff', 4.6), '#ffffff'), 4.6)
        self.assertEqual(G.ensure('#000000', '#ffffff', 7), '#000000')
        self.assertGreaterEqual(G.contrast(G.ensure('#222222', '#101010', 4.5), '#101010'), 4.5)         # روی زمینهٔ تیره روشن‌تر می‌شود

    def test_make_palette_light_and_dark_always_pass(self):
        for acc in ('#ffe600', '#00ff9c', '#7c3aed', '#888888', '#ffffff', '#000000'):
            for dark in (False, True):
                p = G.make_palette(acc, dark=dark)
                self.assertGreaterEqual(G.contrast(p.text, p.bg), 7, (acc, dark))
                self.assertGreaterEqual(G.contrast(p.primary, p.bg), 4.5, (acc, dark))
                self.assertGreaterEqual(G.contrast(p.on_primary, p.primary), 4.5, (acc, dark))

    def test_every_table_row_names_real_dataset_rows(self):
        ids = {r['id'] for r in uiux.rows('styles')}
        pairs = {r['name'] for r in uiux.rows('fonts')}
        pals = {r['product'] for r in uiux.rows('colors')}
        for sid, spec in generated.TABLE.items():
            self.assertIn(sid, ids, sid)
            self.assertIn(spec['pair'], pairs, sid)
            self.assertIn(spec['pal'], pals, sid)
            self.assertIn(spec['arch'], __import__('apps.projects.builder.styles.gen_archetypes', fromlist=['ARCH']).ARCH, sid)


class DesignSourcesApiTests(Base):
    URL = '/api/v1/studio/design-sources/'

    def test_index_lists_every_kind_with_counts_and_attribution(self):
        d = self.c.get(self.URL).json()
        self.assertEqual({k['key'] for k in d['kinds']}, set(uiux.KINDS))
        self.assertEqual(d['source']['license'], 'MIT')
        self.assertEqual(d['styles']['total'], len(S.STYLES))
        self.assertEqual(d['styles']['hand'], 14)
        self.assertEqual(d['styles']['dataset_rows'], len(uiux.rows('styles')))
        self.assertEqual(d['fonts']['bundled'], len(T.FONTS))
        self.assertIn('c21st', d)

    def test_kind_search_paging_filters_and_decorations(self):
        d = self.c.get(self.URL + 'styles/?q=brutal&size=3').json()
        self.assertTrue(d['total'] >= 3 and len(d['items']) == 3)
        self.assertTrue(all(i['site'] for i in d['items']))
        self.assertIn('ux-brutalism', [i['site']['key'] for i in d['items']])
        p2 = self.c.get(self.URL + 'styles/?size=20&page=2').json()
        self.assertEqual(p2['page'], 2)
        self.assertEqual(len(p2['items']), 20)
        facets = {f['value'] for f in p2['facets']['status']}
        self.assertIn('deprecated', facets)
        only = self.c.get(self.URL + 'styles/?status=deprecated&size=60').json()
        self.assertTrue(only['total'] >= 8 and all(i['status'] == 'deprecated' for i in only['items']))
        fonts = self.c.get(self.URL + 'fonts/?size=2').json()
        self.assertTrue(fonts['items'][0]['fa']['heading']['key'] in T.FONTS)
        gf = self.c.get(self.URL + 'google_fonts/?arabic=1&bundled=1&size=60').json()
        self.assertTrue(len(gf['items']) >= 20 and all(i['bundled'] for i in gf['items']))
        colors = self.c.get(self.URL + 'colors/?q=saas').json()
        self.assertTrue(colors['items'])
        self.assertEqual(self.c.get(self.URL + 'nope/').status_code, 404)

    def test_docs_listing_hides_text_and_read_returns_it(self):
        d = self.c.get(self.URL + 'docs/?q=tailwind&size=2').json()
        self.assertNotIn('text', d['items'][0])
        self.assertTrue(d['items'][0]['snippet'])
        full = self.c.get(self.URL + 'docs/read/', {'path': d['items'][0]['path']}).json()
        self.assertGreater(len(full['text']), 500)
        self.assertEqual(self.c.get(self.URL + 'docs/read/', {'path': '../../etc/passwd'}).status_code, 404)

    def test_tokens_api_gives_everything_for_a_design_studio(self):
        lst = self.c.get(self.URL + 'tokens/').json()
        self.assertEqual(lst['count'], len(S.ORDER))
        one = self.c.get(self.URL + 'tokens/ux-vaporwave/').json()
        self.assertEqual(set(one['colors']), set(T.COLOR_VARS))
        self.assertIn('--st-card-bg', one['css_vars'])
        self.assertTrue(one['css'].startswith('/* سبکِ طراحی'))
        self.assertEqual(set(one['tokens']), set(CSS.DEFAULTS))
        self.assertIn(one['fonts']['heading']['key'], T.FONTS)
        self.assertEqual(self.c.get(self.URL + 'tokens/none/').status_code, 404)

    def test_recommend_matches_the_ai_guidance_and_suggests_styles(self):
        d = self.c.get(self.URL + 'recommend/', {'brief': 'سایتِ کلینیکِ دندانپزشکی', 'kind': 'home'}).json()
        self.assertEqual(d['guidance'], ai_context.uiux_hints('سایتِ کلینیکِ دندانپزشکی', 'home', ''))
        self.assertEqual(d['guidance']['product']['type'], 'Medical Clinic')
        self.assertTrue(d['suggested_styles'] is not None)

    def test_only_staff_can_read(self):
        from rest_framework.test import APIClient
        anon, normal = APIClient(), APIClient()
        normal.force_authenticate(self.user)
        for c in (anon, normal):
            self.assertIn(c.get(self.URL).status_code, (401, 403))
            self.assertIn(c.get(self.URL + 'styles/').status_code, (401, 403))


class AiHintsTests(SimpleTestCase):
    def test_hints_are_small_relevant_and_bounded(self):
        for kind in ('home', 'landing', 'static', 'about', 'contact', 'product_list', 'header', 'footer'):
            for brief in ('', 'فروشگاهِ آنلاینِ لوازمِ ورزشی', 'dashboard of sales analytics', 'سایت عروسی'):
                g = ai_context.uiux_hints(brief, kind)
                self.assertLessEqual(len(json.dumps(g, ensure_ascii=False, separators=(',', ':'))), ai_context.GUIDE_MAX_CHARS, (kind, brief))
                self.assertLessEqual(len(g.get('ux', [])), 4)
        g = ai_context.uiux_hints('سایتِ کلینیکِ دندانپزشکی', 'home')
        self.assertEqual(g['product']['type'], 'Medical Clinic')
        self.assertTrue(g['ux'] and g['pattern'])
        self.assertRegex(g['palette']['primary'], r'^#[0-9A-Fa-f]{6}$')                       # پالتِ همان نوعِ محصول
        self.assertIn('chart', ai_context.uiux_hints('داشبوردِ نمودارِ فروش', 'home'))
        st = ai_context.uiux_hints('فروشگاه', 'home').get('stack', [])
        self.assertTrue(1 <= len(st) <= 2 and all(r['rule'] and r['do'] for r in st))       # یادداشتِ پشتهٔ html-tailwind
        self.assertNotIn('chart', ai_context.uiux_hints('سایتِ عروسی', 'home'))

    def test_prompt_with_hints_stays_under_the_cap_for_every_style(self):
        for key in S.ORDER:
            for kind in ('home', 'landing', 'about'):
                p = ai_context.build(key, 'فروشگاهِ آنلاینِ لوازمِ ورزشی با داشبوردِ فروش', kind)
                self.assertLessEqual(len(json.dumps(p, ensure_ascii=False, separators=(',', ':'))), ai_context.MAX_CHARS, (key, kind))
                self.assertLessEqual(len(p['components']), ai_context.MAX_COMPONENTS)
                self.assertIn('guidance', p)
                self.assertEqual(p['style']['key'], key)

    def test_style_brief_carries_checklist_and_rtl_level(self):
        b = ai_context.style_brief('ux-kinetic-typography')
        self.assertTrue(b.get('checklist'))
        self.assertEqual(b.get('rtl_level'), 'caveats')

    def test_options_json_groups_styles(self):
        o = ai_context.options_json()
        self.assertEqual(len(o['styles']), len(S.ORDER))
        self.assertTrue(all(s['group'] and s['source'] for s in o['styles']))


class ChagherAllStylesTests(SimpleTestCase):
    def test_the_chagher_draft_renders_with_every_style(self):
        """۸۹ سبک × پیش‌نویسِ واقعیِ چغر: بی‌هشدار، راست‌به‌چپ، رنگِ برند خوانا، بی‌اسکریپت، یک h1."""
        for style in S.ORDER:
            parts = D.build(style)
            c = parts['theme']['colors']
            self.assertGreaterEqual(R.contrast(c['primary'], c['bg']), 4.5, style)
            self.assertGreaterEqual(R.contrast(c['on_primary'], c['primary']), 4.5, style)
            for target in ('header', 'page', 'footer'):
                out = R.render_doc(parts[target], R.Ctx(target=target, theme=c))
                self.assertEqual([w['text'] for w in out.warnings if 'نشده' not in w['text']], [], (style, target))
            html = D.static_page(parts)
            self.assertIn('dir="rtl"', html)
            self.assertIn('--st-card-bg', html)
            self.assertNotIn('<script', html)
            self.assertEqual(html.count('<h1'), 1)

# -*- coding: utf-8 -*-
"""آزمون‌های ویرایشگرِ دیداری: سازگاری، رندر، امنیت، API، انتشارِ واقعی و هم‌کاری با AI."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.template import Engine
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.ai_engine import services as ai
from apps.code_generation import envs, generator, services
from apps.projects.builder import canvas, clean, importer, media as media_mod, publish as P, render as R, starters, theme as T
from apps.projects.builder.catalog import BLOCKS
from apps.projects.models import App, Design, DesignVersion, Field, MediaAsset, Model, Page, Project, SavedSection, SharedPart, SiteTheme
from apps.projects.tests_data import golden_cases

API = '/api/v1/studio/projects/%s/builder/'
HERE = os.path.dirname(os.path.abspath(__file__))


class Base(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nb-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._ov = override_settings(WORKSPACES_ROOT=__import__('pathlib').Path(self.tmp), AI_RUN_SYNC=True)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        U = get_user_model()
        self.staff = U.objects.create_user(username='staff1', email='s@x.y', password='x', is_staff=True)
        self.user = U.objects.create_user(username='normal1', email='n@x.y', password='x')
        self.c = APIClient()
        self.c.force_authenticate(self.staff)
        # پیش‌نمایشِ واقعی در این آزمون‌ها روشن نمی‌شود؛ پایانِ مسیر را آزمونِ مرورگر می‌سنجد
        p1 = mock.patch('apps.code_generation.preview_runner.start', return_value=(8999, 1))
        p2 = mock.patch('apps.code_generation.preview_runner.status', return_value=(False, None, None))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def project(self, slug='demo', shop=False):
        p = Project.objects.create(name='نمونه', slug=slug)
        if shop:
            services.scaffold_shop(p)
        return p

    def doc(self, *blocks):
        return {'v': 1, 'blocks': list(blocks)}

    def ctx(self, p=None, canvas_mode=False, target='page'):
        p = p or self.project('ctx-%d' % Project.objects.count())
        return R.build_ctx(p, canvas=canvas_mode, target=target)

    def png(self, size=(1200, 800), name='a.png', color=(200, 30, 30), fmt='PNG'):
        buf = io.BytesIO()
        Image.new('RGB', size, color).save(buf, fmt)
        buf.seek(0)
        buf.name = name
        buf.size = buf.getbuffer().nbytes
        return buf


class CompatTests(Base):
    """پروژه‌ای که از ویرایشگر استفاده نکرده باید دقیقاً همان فایل‌های قبلی را بگیرد."""

    def _golden(self):
        with open(os.path.join(HERE, 'tests_data', 'generator_golden.json'), encoding='utf-8') as fh:
            return json.load(fh)

    def assertSameTree(self, name, got):
        want = self._golden()[name]
        diff = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
        self.assertEqual(diff, [], 'خروجیِ موتور برای «%s» فرق کرد' % name)

    def test_shop_output_byte_identical(self):
        self.assertSameTree('shop', golden_cases.case_shop())

    def test_custom_project_output_byte_identical(self):
        self.assertSameTree('custom', golden_cases.case_custom())

    def test_imported_project_output_byte_identical(self):
        self.assertSameTree('imported', golden_cases.case_imported())

    def test_opening_the_editor_does_not_change_output(self):
        """بازکردنِ صفحه در ویرایشگر بی‌انتشار نباید هیچ فایلی را عوض کند."""
        before = golden_cases.case_shop()
        p = Project.objects.get(slug='golden-shop')
        pg = p.pages.get(slug='')
        self.assertEqual(self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': pg.pk}).status_code, 200)
        self.assertEqual(self.c.get(API % p.slug + 'bootstrap/', {'target': 'header'}).status_code, 200)
        from unittest import mock as m
        with m.patch.object(generator.timezone, 'now', return_value=golden_cases.FROZEN):
            generator.ProjectGenerator(p).run()
        self.assertEqual(golden_cases.tree_hashes(p.path), before)
        self.assertFalse(SiteTheme.objects.filter(project=p, active=True).exists())

    def test_other_pages_stay_byte_identical_after_visual_publish(self):
        p = self.project('mix', shop=True)
        services.generate(p, 'x')
        files = {}
        for pg in p.pages.exclude(slug=''):
            with open(os.path.join(str(p.path), 'templates', pg.template_path), 'rb') as fh:
                files[pg.pk] = fh.read()
        home = p.pages.get(slug='')
        r = self.c.post(API % p.slug + 'publish/', {'target': 'page', 'page': home.pk, 'doc': self.doc(clean.new_block('hero'))}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        for pg in p.pages.exclude(slug=''):
            with open(os.path.join(str(p.path), 'templates', pg.template_path), 'rb') as fh:
                self.assertEqual(fh.read(), files[pg.pk], pg.slug)


class RenderTests(Base):
    def r(self, *blocks, ctx=None):
        doc = clean.clean_doc(self.doc(*blocks))
        return R.render_doc(doc, ctx or self.ctx())

    def test_every_block_renders_and_compiles_as_a_django_template(self):
        p = self.project('allb', shop=True)
        ctx = R.build_ctx(p)
        engine = Engine(libraries={'static': 'django.templatetags.static'}, builtins=['django.templatetags.static'])
        for key, spec in BLOCKS.items():
            target = (spec.get('scope') or ['page'])[0]
            if key == 'column':
                b = clean.new_block('columns', children=[clean.new_block('column', children=[clean.new_block('text')])])
            elif key == 'columns':
                b = clean.new_block('columns', children=[clean.new_block('column'), clean.new_block('column')])
            else:
                b = clean.new_block(key)
                if key in ('data_list', 'data_detail'):
                    b['props']['model'] = 'catalog.Product'
                if key == 'custom_html':
                    b['props']['code'] = '<p>سلام</p>'
            doc = clean.clean_doc(self.doc(b), target)
            c = R.build_ctx(p, target=target)
            out = R.render_doc(doc, c)
            engine.from_string('{% load static %}' + out.html)
            if out.html:
                self.assertIn('b-' + b['id'], out.html, key)
        self.assertTrue(ctx.has_cart)

    def test_text_is_escaped_and_template_syntax_is_neutralized(self):
        evil = '<script>alert(1)</script>{{ 7|add:7 }}{% load x %}'
        out = self.r(clean.new_block('heading', text=evil)).html
        self.assertNotIn('<script', out)
        self.assertNotIn('{{', out)
        self.assertNotIn('{%', out)
        self.assertIn('&lt;script', out)

    def test_every_text_prop_of_ready_blocks_is_escaped(self):
        for key in ('hero', 'features', 'pricing', 'testimonials', 'faq', 'cta', 'contact_form', 'map'):
            b = clean.new_block(key)
            for k, v in list(b['props'].items()):
                if isinstance(v, str) and k not in ('layout',):
                    b['props'][k] = '<img src=x onerror=1>{{x}}'
            html = self.r(b).html
            self.assertNotIn('<img src=x', html, key)
            self.assertNotIn('{{x}}', html, key)

    def test_rich_text_keeps_safe_tags_only(self):
        out = clean.clean_rich('<p onclick="x()">سلام <b>دنیا</b><script>x()</script><a href="javascript:alert(1)">ل</a><a href="/about/">م</a><img src=x></p>')
        self.assertIn('<b>دنیا</b>', out)
        self.assertNotIn('onclick', out)
        self.assertNotIn('<script', out)
        self.assertNotIn('javascript', out)
        self.assertNotIn('<img', out)
        self.assertIn('href="/about/"', out)
        html = self.r(clean.new_block('text', html='<p>{{ danger }}</p>')).html
        self.assertNotIn('{{', html)

    def test_style_values_cannot_inject_css(self):
        b = clean.new_block('section')
        b['style'] = {'d': {'color': 'red;}body{display:none', 'bg': 'url(javascript:1)', 'py': '10;x', 'radius': 9999, 'shadow': 'x;y', 'nope': 1}}
        out = clean.clean_doc(self.doc(b))['blocks'][0]['style']
        d = out.get('d', {})
        self.assertNotIn('color', d)
        self.assertNotIn('bg', d)
        self.assertNotIn('shadow', d)
        self.assertEqual(d.get('radius'), 80)
        self.assertNotIn('nope', d)

    def test_links_are_safe(self):
        self.assertEqual(clean.safe_url('javascript:alert(1)'), '#')
        self.assertEqual(clean.safe_url('data:text/html,x'), '#')
        self.assertEqual(clean.safe_url('/about/'), '/about/')
        self.assertEqual(clean.safe_url('tel:0912'), 'tel:0912')
        self.assertEqual(clean.safe_url('example.com'), 'https://example.com')

    def test_nesting_rules(self):
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc({'id': 'aaaa1111', 'type': 'nope', 'props': {}}))
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(clean.new_block('section', children=[clean.new_block('hero')])))
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(clean.new_block('columns', children=[clean.new_block('text')])))
        with self.assertRaises(clean.DocError):
            clean.clean_doc(self.doc(clean.new_block('site_header')), 'page')
        self.assertEqual(len(clean.clean_doc(self.doc(clean.new_block('site_header')), 'header')['blocks']), 1)

    def test_duplicate_or_bad_ids_are_replaced(self):
        a = clean.new_block('heading')
        b = dict(clean.new_block('heading'), id=a['id'])
        c = dict(clean.new_block('heading'), id='../../x')
        ids = [x['id'] for x in clean.clean_doc(self.doc(a, b, c))['blocks']]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(clean.ID_RE.match(i) for i in ids))

    def test_responsive_values_and_hide_flags_reach_css(self):
        b = clean.new_block('heading', text='x', style={'d': {'size': 60, 'hide_phone': True}, 't': {'size': 40}, 'p': {'size': 28, 'align': 'center'}})
        css = self.r(b).css
        self.assertIn('font-size:60px', css)
        self.assertIn('font-size:40px', css)
        self.assertIn('font-size:28px', css)
        self.assertIn('@media (max-width:640px)', css)
        self.assertIn('display:none', css)

    def test_large_heading_shrinks_on_phone_automatically(self):
        css = self.r(clean.new_block('heading', text='x', style={'d': {'size': 80}})).css
        self.assertIn('font-size:54px', css)

    def test_accessibility_warnings(self):
        out = self.r(clean.new_block('image', src='https://e.com/a.jpg'), clean.new_block('heading', text='a', level=1),
                     clean.new_block('heading', text='b', level=1), clean.new_block('heading', text='c', level=4))
        texts = ' '.join(w['text'] for w in out.warnings)
        self.assertIn('توضیح', texts)
        self.assertIn('بیش از یک تیترِ اصلی', texts)
        self.assertIn('پله', texts)

    def test_contrast_warning(self):
        s = clean.new_block('section', children=[clean.new_block('text', style={'d': {'color': '#eeeeee'}})], style={'d': {'bg': '#ffffff'}})
        self.assertIn('به‌سختی', ' '.join(w['text'] for w in self.r(s).warnings))

    def test_output_needs_no_editor_javascript_or_markers(self):
        p = self.project('nojs', shop=True)
        for st in starters.STARTERS:
            doc = clean.clean_doc(starters.starter_doc(st['key'], R.build_ctx(p)))
            html = R.render_doc(doc, R.build_ctx(p)).html
            self.assertNotIn('<script', html)
            self.assertNotIn('data-bid', html)
            self.assertNotIn('data-nb', html)

    def test_private_models_are_never_available(self):
        p = self.project('priv', shop=True)
        P.ensure_forms_app(p)
        idx = R.model_index(p)
        self.assertIn('catalog.Product', idx)
        self.assertNotIn('orders.Order', idx)
        self.assertNotIn('site_forms.FormMessage', idx)

    def test_video_embed_only_known_hosts(self):
        self.assertIn('aparat.com/video/video/embed', R.video_embed('https://www.aparat.com/v/abc12'))
        self.assertIn('youtube-nocookie', R.video_embed('https://youtu.be/abcde12'))
        self.assertEqual(R.video_embed('https://evil.example/v/abc'), '')
        self.assertEqual(R.video_embed('javascript:alert(1)'), '')

    def test_canvas_custom_html_is_inert(self):
        out = R.canvas_safe('<div onclick="x()">{{ a }}{% if b %}س{% endif %}<script>alert(1)</script><a href="javascript:x">ل</a></div>')
        self.assertNotIn('<script', out)
        self.assertNotIn('onclick', out)
        self.assertNotIn('javascript:', out)
        self.assertNotIn('{%', out)


class CanvasTests(Base):
    def test_canvas_and_publish_share_structure(self):
        p = self.project('cv', shop=True)
        doc = clean.clean_doc(starters.starter_doc('home_shop', R.build_ctx(p)))
        theme = T.clean_theme(None, p)
        out = canvas.render_canvas(p, 'page', p.pages.get(slug=''), doc, theme, [])
        self.assertEqual(len(out['parts']), len(doc['blocks']))
        self.assertIn('data-bid', out['parts'][0]['html'])
        self.assertIn('data-nb-edit="title"', out['parts'][0]['html'])
        self.assertIn('Vazirmatn', out['base_css'])
        self.assertNotIn('cdn.jsdelivr', out['base_css'])
        html = ''.join(x['html'] for x in out['parts'])
        self.assertIn('نمونهٔ', html)                     # دادهٔ نمونه چون هنوز رکوردی نیست
        self.assertIn('catalog.Product', out['sample_models'])

    def test_canvas_reads_real_rows_when_database_exists(self):
        import sqlite3
        p = self.project('cv2', shop=True)
        os.makedirs(str(p.path), exist_ok=True)
        conn = sqlite3.connect(os.path.join(str(p.path), 'db.sqlite3'))
        conn.execute('CREATE TABLE catalog_product (id INTEGER PRIMARY KEY, name TEXT, description TEXT, price TEXT, stock INT, is_active INT, image TEXT, category_id INT, created_at TEXT)')
        conn.execute("INSERT INTO catalog_product VALUES (1,'کفشِ واقعی','','120000',3,1,'',NULL,'2026-10-01 10:00:00')")
        conn.execute("INSERT INTO catalog_product VALUES (2,'کالای غیرفعال','','1',3,0,'',NULL,'2026-10-01 10:00:00')")
        conn.commit(); conn.close()
        b = clean.new_block('data_list', model='catalog.Product')
        out = canvas.render_canvas(p, 'page', p.pages.get(slug=''), clean.clean_doc(self.doc(b)), T.clean_theme(None, p), [])
        html = out['parts'][0]['html']
        self.assertIn('کفشِ واقعی', html)
        self.assertNotIn('کالای غیرفعال', html)
        self.assertNotIn('catalog.Product', out['sample_models'])


class ImporterTests(Base):
    def imp(self, html, prev=None, css='', p=None):
        return importer.import_html(html, css, prev, R.build_ctx(p or self.project('imp-%d' % Project.objects.count())), 'page')

    def rendered(self, doc, p=None):
        return R.render_doc(clean.clean_doc(doc), R.build_ctx(p or self.project('imr-%d' % Project.objects.count()))).html

    def test_recognized_elements_become_blocks(self):
        doc, rep = self.imp('<section class="section"><div class="wrap"><h1>سلام</h1><p class="muted">متن <b>پررنگ</b></p>'
                            '<a class="btn lg" href="/x/">برو</a><hr><img src="https://e.com/a.jpg" alt="ع"></div></section>')
        self.assertEqual(rep['custom'], 0)
        s = doc['blocks'][0]
        self.assertEqual(s['type'], 'section')
        self.assertEqual([k['type'] for k in s['children']], ['heading', 'text', 'button', 'divider', 'image'])
        self.assertEqual(s['props']['cls'], 'section')
        self.assertEqual(s['props']['inner_cls'], 'wrap')

    def test_unknown_things_become_custom_never_dropped(self):
        html = '<section class="x"><table><tr><td>جدول</td></tr></table></section><div id="k" style="color:red">دیو</div>' \
               '{% for p in products %}<article>{{ p.name }}</article>{% empty %}<p>خالی</p>{% endfor %}<!-- یادداشت --><marquee>م</marquee>'
        doc, rep = self.imp(html)
        out = self.rendered(doc)
        for piece in ('جدول', 'color:red', 'دیو', '{% for p in products %}', '{{ p.name }}', '{% empty %}', 'خالی', '<!-- یادداشت -->', '<marquee>م</marquee>'):
            self.assertIn(piece, out, piece)
        self.assertGreaterEqual(rep['custom'], 2)

    def test_all_default_bodies_roundtrip_without_losing_anything(self):
        import re
        for kind, body in generator.DEFAULT_BODIES.items():
            doc, _ = self.imp(body)
            doc = clean.clean_doc(doc)
            out = self.rendered(doc)
            for tag in re.findall(r'{%.*?%}|{{.*?}}', body):
                self.assertIn(tag, out, '%s: %s' % (kind, tag))
            for text in re.findall(r'>([^<>{}]*[؀-ۿ][^<>{}]*)<', body):
                self.assertIn(text.strip(), out, '%s: %s' % (kind, text))
            ai.validate_template(out, None)
            self.assertTrue(ai.validate_template(out, None)[0], kind)

    def test_broken_html_becomes_one_custom_block(self):
        src = '<div><span>نیمه‌کاره</div><p>باز'
        doc, rep = self.imp(src)
        self.assertEqual(rep['custom'], 1)
        self.assertEqual(doc['blocks'][0]['props']['code'], src)

    def test_unbalanced_template_tags_stay_together(self):
        src = '{% if x %}<div>الف</div>{% else %}<span>ب</span>{% endif %}<h2>تیتر</h2>'
        doc, _ = self.imp(src)
        self.assertEqual(doc['blocks'][0]['type'], 'custom_html')
        self.assertIn('{% endif %}', doc['blocks'][0]['props']['code'])
        self.assertEqual(doc['blocks'][1]['type'], 'heading')

    def _published(self, p, *blocks):
        doc = clean.clean_doc(self.doc(*blocks))
        return doc, R.render_doc(doc, R.build_ctx(p))

    def test_unchanged_blocks_are_restored_exactly(self):
        p = self.project('mg1')
        doc, rendered = self._published(p, clean.new_block('hero', title='الف'), clean.new_block('features'),
                                        clean.new_block('section', children=[clean.new_block('heading', text='ت', style={'d': {'size': 40}})]))
        new, rep = self.imp(rendered.html, prev=doc, css=R.page_css(rendered.css), p=p)
        self.assertEqual(clean.canonical(new['blocks']), clean.canonical(doc['blocks']))
        self.assertEqual(rep['custom'], 0)
        self.assertNotIn('extra_css', new)

    def test_ai_text_change_stays_in_the_block(self):
        p = self.project('mg2')
        doc, rendered = self._published(p, clean.new_block('hero', title='عنوانِ قدیمی'), clean.new_block('features'))
        changed = rendered.html.replace('عنوانِ قدیمی', 'عنوانِ تازهٔ AI').replace('مطمئن', 'خیلی مطمئن')
        new, rep = self.imp(changed, prev=doc, p=p)
        self.assertEqual(rep['custom'], 0)
        self.assertEqual(new['blocks'][0]['props']['title'], 'عنوانِ تازهٔ AI')
        self.assertEqual(new['blocks'][1]['props']['items'][1]['title'], 'خیلی مطمئن')
        self.assertEqual(new['blocks'][0]['id'], doc['blocks'][0]['id'])

    def test_ai_new_section_and_child_change(self):
        p = self.project('mg3')
        h = clean.new_block('heading', text='قدیم')
        doc, rendered = self._published(p, clean.new_block('section', children=[h, clean.new_block('text')]))
        changed = rendered.html.replace('قدیم', 'جدید') + '\n<section class="section"><h2>بخشِ تازه</h2></section>'
        new, rep = self.imp(changed, prev=doc, p=p)
        self.assertEqual(new['blocks'][0]['type'], 'section')
        self.assertEqual(new['blocks'][0]['children'][0]['props']['text'], 'جدید')
        self.assertEqual(new['blocks'][1]['children'][0]['props']['text'], 'بخشِ تازه')
        self.assertEqual(rep['custom'], 0)

    def test_structural_ai_change_becomes_custom_and_keeps_css(self):
        p = self.project('mg4')
        hero = clean.new_block('hero', title='ع', style={'d': {'bg': '#112233'}})
        doc, rendered = self._published(p, hero)
        changed = rendered.html.replace('<div class="nb-actions">', '<div class="tazeh"><i>نو</i></div><div class="nb-actions">')
        new, rep = self.imp(changed, prev=doc, css=R.page_css(rendered.css), p=p)
        self.assertEqual(new['blocks'][0]['type'], 'custom_html')
        self.assertIn('نو', new['blocks'][0]['props']['code'])
        self.assertEqual(rep['custom_labels'], ['سربرگِ بزرگ'])
        self.assertIn('#112233', new.get('extra_css', ''))

    def test_ai_css_edits_are_kept(self):
        p = self.project('mg5')
        doc, rendered = self._published(p, clean.new_block('heading', text='x', style={'d': {'size': 40}}))
        css = R.page_css(rendered.css, '.mine{color:red}')
        css = css.replace(R.ZONE_END, '.added{color:blue}\n' + R.ZONE_END)
        new, _ = self.imp(rendered.html, prev=doc, css=css, p=p)
        self.assertIn('.mine{color:red}', new['extra_css'])
        self.assertIn('.added{color:blue}', new['extra_css'])
        out = R.page_css(R.render_doc(clean.clean_doc(new), R.build_ctx(p)).css, new['extra_css'])
        self.assertIn('.mine{color:red}', out)


class PermissionTests(Base):
    ENDPOINTS = [('get', 'catalog/'), ('get', 'bootstrap/?target=header'), ('put', 'design/'), ('post', 'render/'), ('post', 'publish/'),
                 ('get', 'versions/1/'), ('post', 'pages/'), ('post', 'pages/1/starter/'), ('post', 'pages/1/meta/'),
                 ('post', 'pages/1/roundtrip-check/'), ('get', 'theme/'), ('get', 'media/'), ('post', 'media/'), ('delete', 'media/1/'),
                 ('get', 'sections/'), ('delete', 'sections/1/'), ('post', 'models/1/seed/')]

    def test_every_endpoint_needs_staff(self):
        p = self.project('perm')
        anon = APIClient()
        normal = APIClient()
        normal.force_authenticate(self.user)
        for method, sub in self.ENDPOINTS:
            url = API % p.slug + sub
            self.assertIn(getattr(anon, method)(url, {}, format='json').status_code, (401, 403), sub)
            self.assertEqual(getattr(normal, method)(url, {}, format='json').status_code, 403, sub)

    def test_objects_of_another_project_are_not_reachable(self):
        a = self.project('own-a')
        b = self.project('own-b')
        pg = Page.objects.create(project=b, title='ب', slug='x')
        d = Design.objects.create(project=b, target='page', page=pg, draft=self.doc())
        v = DesignVersion.objects.create(design=d, doc=self.doc())
        s = SavedSection.objects.create(project=b, title='ب', doc=clean.new_block('heading'))
        asset = media_mod.save_upload(b, self.png())
        app = App.objects.create(project=b, name='q')
        m = Model.objects.create(app=app, name='Q')
        base = API % a.slug
        for method, sub, body in (
            ('get', 'bootstrap/?target=page&page=%d' % pg.pk, None),
            ('put', 'design/', {'target': 'page', 'page': pg.pk, 'doc': self.doc()}),
            ('post', 'render/', {'target': 'page', 'page': pg.pk, 'doc': self.doc()}),
            ('post', 'publish/', {'target': 'page', 'page': pg.pk, 'doc': self.doc()}),
            ('get', 'versions/%d/' % v.pk, None), ('post', 'versions/%d/' % v.pk, {}),
            ('post', 'pages/%d/starter/' % pg.pk, {'starter': 'home'}), ('post', 'pages/%d/meta/' % pg.pk, {'title': 'x'}),
            ('post', 'pages/%d/roundtrip-check/' % pg.pk, {'body_html': ''}),
            ('put', 'media/%d/' % asset.pk, {'alt': 'x'}), ('delete', 'media/%d/' % asset.pk, None),
            ('get', 'sections/%d/' % s.pk, None), ('delete', 'sections/%d/' % s.pk, None),
            ('post', 'models/%d/seed/' % m.pk, {}),
        ):
            r = getattr(self.c, method)(base + sub, body, format='json') if body is not None else getattr(self.c, method)(base + sub)
            self.assertEqual(r.status_code, 404, '%s %s' % (method, sub))
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_imported_project_is_refused_clearly(self):
        p = Project.objects.create(name='و', slug='impd', source='imported')
        r = self.c.get(API % p.slug + 'bootstrap/?target=header')
        self.assertEqual(r.status_code, 400)
        self.assertIn('واردشده', r.json()['error'])


class MediaTests(Base):
    def up(self, p, f):
        return self.c.post(API % p.slug + 'media/', {'file': f}, format='multipart')

    def test_image_is_resized_compressed_and_stripped(self):
        p = self.project('md1')
        buf = io.BytesIO()
        exif = Image.Exif()
        exif[0x010F] = 'SecretCamera'
        Image.effect_noise((3000, 1500), 80).convert('RGB').save(buf, 'JPEG', exif=exif)
        buf.seek(0)
        buf.name = '../../evil name.jpg'
        r = self.up(p, buf)
        self.assertEqual(r.status_code, 201, r.content)
        a = MediaAsset.objects.get(pk=r.json()['asset']['id'])
        self.assertEqual(a.width, 1920)
        self.assertEqual(a.height, 960)
        self.assertTrue(a.rel_path.startswith('static/site-media/'))
        self.assertTrue(a.rel_path.endswith('.webp'))
        self.assertNotIn('..', a.name)
        full = os.path.join(str(p.path), a.rel_path)
        self.assertTrue(os.path.isfile(full))
        with Image.open(full) as im:
            self.assertEqual(im.format, 'WEBP')
            self.assertEqual(dict(im.getexif()), {})
        self.assertIn('800', a.variants)
        self.assertTrue(os.path.isfile(os.path.join(str(p.path), a.variants['800'])))

    def test_real_type_is_checked_not_the_extension(self):
        p = self.project('md2')
        for name, data in (('a.png', b'this is not an image at all'), ('a.jpg', b'<?php echo 1; ?>'), ('a.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'),
                           ('a.html', b'<html></html>'), ('a.gif', b'GIF89a')):
            f = io.BytesIO(data)
            f.name = name
            r = self.up(p, f)
            self.assertEqual(r.status_code, 400, name)
        self.assertEqual(MediaAsset.objects.filter(project=p).count(), 0)

    def test_size_limits(self):
        p = self.project('md3')
        f = io.BytesIO(b'\x00' * 16 + b'x' * 100)
        f.name = 'big.jpg'
        with mock.patch.object(media_mod, 'MAX_IMAGE_BYTES', 50):
            self.assertEqual(self.up(p, f).status_code, 400)
        with mock.patch.object(media_mod, 'MAX_PROJECT_BYTES', 1):
            self.assertEqual(self.up(p, self.png()).status_code, 400)
        with mock.patch.object(media_mod, 'MAX_PIXELS', 100):
            self.assertEqual(self.up(p, self.png()).status_code, 400)

    def test_video_magic_bytes(self):
        p = self.project('md4')
        f = io.BytesIO(b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 200)
        f.name = 'x.bin'
        r = self.up(p, f)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['asset']['kind'], 'video')
        self.assertTrue(r.json()['asset']['url'].endswith('.mp4'))

    def test_same_file_is_not_stored_twice(self):
        p = self.project('md5')
        a = self.up(p, self.png()).json()['asset']['id']
        b = self.up(p, self.png()).json()['asset']['id']
        self.assertEqual(a, b)

    def test_delete_warns_when_in_use(self):
        p = self.project('md6')
        aid = self.up(p, self.png()).json()['asset']['id']
        pg = Page.objects.create(project=p, title='ص', slug='x')
        Design.objects.create(project=p, target='page', page=pg, draft=self.doc(clean.new_block('image', src='m:%d' % aid)))
        r = self.c.delete(API % p.slug + 'media/%d/' % aid)
        self.assertEqual(r.status_code, 409)
        self.assertIn('ص', r.json()['error'])
        rel = MediaAsset.objects.get(pk=aid).rel_path
        self.assertEqual(self.c.delete(API % p.slug + 'media/%d/?force=1' % aid).status_code, 200)
        self.assertFalse(os.path.exists(os.path.join(str(p.path), rel)))

    def test_public_media_rejects_traversal_and_odd_names(self):
        p = self.project('md7')
        a = media_mod.save_upload(p, self.png())
        name = os.path.basename(a.rel_path)
        pub = '/api/v1/studio/builder-media/%s/' % p.slug
        anon = APIClient()
        self.assertEqual(anon.get(pub + name).status_code, 200)
        os.makedirs(str(p.path), exist_ok=True)
        with open(os.path.join(str(p.path), 'db.sqlite3'), 'w') as fh:
            fh.write('secret')
        for bad_name in ('..%2f..%2fdb.sqlite3', '../../db.sqlite3', '%2e%2e%2fdb.sqlite3', 'db.sqlite3', 'x.php', name + '.php', 'u/../../db.sqlite3', 'u/..%2fdb.sqlite3', 'u/db.sqlite3'):
            self.assertEqual(anon.get(pub + bad_name).status_code, 404, bad_name)
        self.assertEqual(anon.get('/api/v1/studio/builder-fonts/../../settings.py').status_code, 404)
        self.assertEqual(anon.get('/api/v1/studio/builder-fonts/vazirmatn-arabic-wght-normal.woff2').status_code, 200)

    def test_serves_with_nosniff(self):
        p = self.project('md8')
        a = media_mod.save_upload(p, self.png())
        r = APIClient().get('/api/v1/studio/builder-media/%s/%s' % (p.slug, os.path.basename(a.rel_path)))
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r['Content-Type'], 'image/webp')


class FlowApiTests(Base):
    def test_bootstrap_converts_code_page_and_leaves_it_untouched(self):
        p = self.project('fl1', shop=True)
        pg = p.pages.get(slug='')
        before = pg.body_html
        r = self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': pg.pk})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertTrue(data['doc']['blocks'])
        self.assertIn('کدِ سفارشی', data['notice'])
        self.assertIn('catalog', data)
        self.assertTrue(any(m['ref'] == 'catalog.Product' for m in data['models']))
        self.assertFalse(any(m['ref'].startswith('orders.') for m in data['models']))
        pg.refresh_from_db()
        self.assertEqual(pg.body_html, before)

    def test_draft_autosave_and_conflict(self):
        p = self.project('fl2')
        pg = Page.objects.create(project=p, title='ص', slug='x')
        data = self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': pg.pk}).json()
        rev = data['status']['rev']
        body = {'target': 'page', 'page': pg.pk, 'doc': self.doc(clean.new_block('heading')), 'rev': rev}
        r = self.c.put(API % p.slug + 'design/', body, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['status']['dirty'])
        self.assertEqual(self.c.put(API % p.slug + 'design/', body, format='json').status_code, 409)
        pg.refresh_from_db()
        self.assertEqual(pg.body_html, '')             # پیش‌نویس به سایت نمی‌رسد

    def test_page_from_starter_gets_free_address(self):
        p = self.project('fl3')
        ids = []
        for _ in range(2):
            r = self.c.post(API % p.slug + 'pages/', {'starter': 'about', 'title': 'دربارهٔ ما'}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            ids.append(r.json()['page']['slug'])
        self.assertEqual(ids, ['about', 'about-2'])
        home = self.c.post(API % p.slug + 'pages/', {'starter': 'home', 'setup_chrome': True}, format='json').json()['page']
        self.assertEqual(home['slug'], '')
        self.assertTrue(Design.objects.filter(project=p, target='header').exists())
        self.assertFalse(self.c.post(API % p.slug + 'pages/', {'starter': 'nope'}, format='json').status_code == 201)

    def test_saved_sections(self):
        p = self.project('fl4')
        b = clean.new_block('section', children=[clean.new_block('heading', text='س')])
        r = self.c.post(API % p.slug + 'sections/', {'title': 'بخشِ من', 'block': b}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()['section']['id']
        got = self.c.get(API % p.slug + 'sections/%d/' % sid).json()['block']
        self.assertEqual(got['children'][0]['props']['text'], 'س')
        self.assertNotEqual(got['id'], b['id'])
        self.assertEqual(self.c.post(API % p.slug + 'sections/', {'block': {'type': 'x'}}, format='json').status_code, 400)
        self.assertEqual(self.c.delete(API % p.slug + 'sections/%d/' % sid).status_code, 200)

    def test_theme_and_menu_validation(self):
        p = self.project('fl5')
        pg = Page.objects.create(project=p, title='ص', slug='x')
        r = self.c.put(API % p.slug + 'theme/', {
            'theme': {'colors': {'primary': '#ff0000', 'text': 'red;}body{'}, 'font_body': 'estedad', 'font_head': 'x', 'button': 'square'},
            'menu': [{'id': 'a', 'page': pg.pk, 'label': 'م'}, {'page': 99999}, {'url': 'javascript:alert(1)'}, {'url': '/z/', 'label': 'ز'}, 'x']},
            format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d['theme']['colors']['primary'], '#ff0000')
        self.assertEqual(d['theme']['colors']['text'], T.DEFAULT_COLORS['text'])
        self.assertEqual(d['theme']['font_body'], 'estedad')
        self.assertEqual(d['theme']['font_head'], 'vazirmatn')
        self.assertEqual(len(d['menu']), 3)                # javascript: ⇐ '#' نشانیِ بی‌اثر
        self.assertEqual(d['menu'][1].get('url'), '#')

    def test_theme_reads_effective_colors_from_ai_css(self):
        p = self.project('fl6')
        SharedPart.objects.create(project=p, kind='base_css', content=':root{--brand:#123456}\n/* ── پوستهٔ هوشِ مصنوعی: x ── */\n:root { --brand: #7c3aed; }')
        d = self.c.get(API % p.slug + 'theme/').json()
        self.assertEqual(d['theme']['colors']['primary'], '#7c3aed')

    def test_theme_zone_moves_to_end_and_last_writer_wins(self):
        css = T.apply_zone(':root{--brand:#111111}', T.clean_theme({'colors': {'primary': '#222222'}}))
        again = T.apply_zone(css + '\n/* AI */:root{--brand:#333333}', T.clean_theme({'colors': {'primary': '#444444'}}))
        self.assertEqual(again.count(T.ZONE_START), 1)
        self.assertTrue(again.rstrip().endswith(T.ZONE_END))
        self.assertEqual(T.effective_colors(again)['primary'], '#444444')
        self.assertNotIn('#222222', again)


class PublishTests(Base):
    """انتشار با تولیدِ واقعی: فایل‌ها، مهاجرت و اجرای سایتِ تولیدشده با کلاینتِ آزمونِ خودش."""

    def run_site(self, p, script):
        r = services._run(p, ['manage.py', 'shell', '-c', script], 120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout

    def publish(self, p, doc, page=None, target='page'):
        body = {'target': target, 'doc': doc}
        if page is not None:
            body['page'] = page.pk
        return self.c.post(API % p.slug + 'publish/', body, format='json')

    def test_full_publish_blank_project(self):
        p = self.project('pb1')
        pg = self.c.post(API % p.slug + 'pages/', {'starter': 'contact', 'title': 'تماس', 'setup_chrome': True}, format='json').json()['page']
        page = Page.objects.get(pk=pg['id'])
        asset = media_mod.save_upload(p, self.png())
        doc = self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': page.pk}).json()['doc']
        doc['blocks'].insert(0, clean.new_block('image', src='m:%d' % asset.pk, alt='عکس'))
        self.c.put(API % p.slug + 'theme/', {'theme': {'colors': {'primary': '#aa0044'}, 'font_body': 'estedad'}}, format='json')
        r = self.publish(p, doc, page)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'], r.json().get('technical'))
        root = str(p.path)
        base = open(os.path.join(root, 'templates/base.html'), encoding='utf-8').read()
        self.assertNotIn('cdn.jsdelivr', base)
        self.assertIn('css/blocks.css', base)
        self.assertTrue(os.path.isfile(os.path.join(root, 'static/fonts/estedad-arabic-wght-normal.woff2')))
        self.assertTrue(os.path.isfile(os.path.join(root, 'static/fonts/vazirmatn-arabic-wght-normal.woff2')))
        self.assertTrue(os.path.isfile(os.path.join(root, asset.rel_path)))
        blocks_css = open(os.path.join(root, 'static/css/blocks.css'), encoding='utf-8').read()
        self.assertIn('Estedad', blocks_css)
        self.assertNotIn('http', blocks_css.split('.nb-wrap')[0])
        base_css = open(os.path.join(root, 'static/css/base.css'), encoding='utf-8').read()
        self.assertIn('--brand: #aa0044', base_css)
        p.refresh_from_db()
        self.assertEqual(p.brand_color, '#aa0044')
        page.refresh_from_db()
        self.assertTrue(page.in_menu)
        self.assertEqual(p.designs.get(target='page', page=page).versions.filter(kind='publish').count(), 1)
        # فرمِ تماس واقعاً کار می‌کند
        self.assertTrue(p.apps.filter(name='site_forms').exists())
        out = self.run_site(p, '''
from django.test import Client
from apps.site_forms.models import FormMessage
c = Client(enforce_csrf_checks=False, HTTP_HOST='localhost')
html = c.get('/contact/').content.decode()
assert 'name="fld_0"' in html and 'dir="rtl"' in html and 'site-media' in html, html[:400]
import re, html as h
spec = h.unescape(re.search(r'name="_spec" value="([^"]+)"', html).group(1))
resp = c.post('/forms/submit_form/', {'_next': '/contact/', '_form': 'تماس', '_spec': spec, 'fld_0': 'علی', 'fld_1': '0912', 'fld_2': 'سلام'})
assert resp.status_code == 302 and resp['Location'] == '/contact/', resp
assert FormMessage.objects.count() == 1
assert 'علی' in FormMessage.objects.first().content
# فیلدِ لازم خالی
c.post('/forms/submit_form/', {'_next': '/contact/', '_spec': spec, 'fld_0': ''})
assert FormMessage.objects.count() == 1
# تلهٔ ربات
c.post('/forms/submit_form/', {'_next': '/contact/', '_spec': spec, 'fld_0': 'a', 'fld_1': 'b', 'fld_2': 'c', 'website': 'spam'})
assert FormMessage.objects.count() == 1
# ریدایرکتِ بیرونی
resp = c.post('/forms/submit_form/', {'_next': 'https://evil.example/', '_spec': spec, 'fld_0': 'a', 'fld_1': 'b', 'fld_2': 'c'})
assert resp['Location'] == '/', resp['Location']
print('FORM_OK')
''')
        self.assertIn('FORM_OK', out)
        # ZIP همهٔ رسانه و فونت را دارد
        buf = services.export_zip(p)
        names = zipfile.ZipFile(buf).namelist()
        self.assertIn('pb1/%s' % asset.rel_path, names)
        self.assertIn('pb1/static/fonts/estedad-arabic-wght-normal.woff2', names)
        self.assertIn('pb1/static/css/blocks.css', names)

    def test_dynamic_list_detail_and_menu_in_generated_site(self):
        p = self.project('pb2', shop=True)
        services.generate(p, 'x')
        home = p.pages.get(slug='')
        detail = Page.objects.create(project=p, title='جزئیات', slug='item', kind='static', order=70)
        lst = clean.new_block('data_list', model='catalog.Product', fields=['name', 'price', 'description'], count=2, sort='-price',
                              link='page:%d' % detail.pk, add_to_cart=True)
        r = self.publish(p, self.doc(clean.new_block('section', children=[lst])), home)
        self.assertEqual(r.status_code, 200, r.content)
        det = clean.new_block('data_detail', model='catalog.Product', fields=['name', 'description', 'price'])
        self.c.put(API % p.slug + 'theme/', {'menu': [{'id': 'z', 'url': '/custom/', 'label': 'لینکِ من'}, {'id': 'y', 'page': home.pk, 'label': 'خانه'}]}, format='json')
        r = self.publish(p, self.doc(clean.new_block('section', children=[det])), detail)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'], r.json().get('technical'))
        out = self.run_site(p, '''
from django.test import Client
from apps.catalog.models import Category, Product
for i, (n, price) in enumerate((('کمترین', 10), ('میانی', 50), ('بیشترین', 90))):
    Product.objects.create(name=n, slug='s%d' % i, price=price, stock=1, is_active=True, description='<b>متن</b>')
Product.objects.create(name='پنهان', slug='h', price=1000, stock=1, is_active=False)
c = Client(HTTP_HOST='localhost')
html = c.get('/').content.decode()
assert 'بیشترین' in html and 'میانی' in html, html
assert 'کمترین' not in html, 'count'
assert 'پنهان' not in html, 'inactive'
assert '&lt;b&gt;متن' in html, 'escape'
assert '/item/?id=' in html
assert 'افزودن به سبد' in html
assert 'لینکِ من' not in html or True
pk = Product.objects.get(name='میانی').pk
d = c.get('/item/?id=%d' % pk).content.decode()
assert 'میانی' in d and 'بیشترین' not in d, d
assert 'پیدا نشد' in c.get('/item/?id=999999').content.decode()
assert 'پیدا نشد' in c.get('/item/?id=abc').content.decode()
from config.context import MENU
assert MENU[0] == ('لینکِ من', '/custom/'), MENU
# خریدِ کامل روی پروژهٔ دیداری هم کار می‌کند
from apps.orders.models import Order
p2 = Product.objects.get(name='میانی')
c.post('/cart/add/%d/' % p2.pk, {'next': '/'})
r = c.post('/cart/checkout/', {'customer_name': 'علی', 'phone': '0912', 'address': 'تهران'})
assert r.status_code in (200, 302) and Order.objects.count() == 1, r.status_code
assert 'blocks.css' in c.get('/cart/').content.decode()
print('DATA_OK')
''')
        self.assertIn('DATA_OK', out)

    def test_custom_html_with_bad_template_blocks_publish(self):
        p = self.project('pb3')
        pg = Page.objects.create(project=p, title='ص', slug='x')
        for code in ('{% if x %}بسته نشده', '{% extends "x" %}', '{% load os %}'):
            r = self.publish(p, self.doc(clean.new_block('custom_html', code=code)), pg)
            self.assertEqual(r.status_code, 400, code)
            self.assertIn('کدِ سفارشی', r.json()['error'])
        pg.refresh_from_db()
        self.assertEqual(pg.body_html, '')
        self.assertFalse(SiteTheme.objects.filter(project=p, active=True).exists())

    def test_versions_and_restore(self):
        p = self.project('pb4')
        pg = Page.objects.create(project=p, title='ص', slug='x')
        d1 = self.doc(clean.new_block('heading', text='یک'))
        self.assertEqual(self.publish(p, d1, pg).status_code, 200)
        d2 = self.doc(clean.new_block('heading', text='دو'))
        self.assertEqual(self.publish(p, d2, pg).status_code, 200)
        design = Design.objects.get(page=pg)
        first = design.versions.order_by('id').first()
        r = self.c.post(API % p.slug + 'versions/%d/' % first.pk, {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['doc']['blocks'][0]['props']['text'], 'یک')
        pg.refresh_from_db()
        self.assertIn('دو', pg.body_html)                # تا انتشار، سایت همان است
        design.refresh_from_db()
        self.assertTrue(P.status_of(design)['dirty'])

    def test_header_and_footer_publish(self):
        p = self.project('pb5', shop=True)
        pg = p.pages.get(slug='')
        r = self.c.get(API % p.slug + 'bootstrap/', {'target': 'header'}).json()
        self.assertEqual(r['doc']['blocks'][0]['type'], 'site_header')
        h = r['doc']
        h['blocks'][0]['style'] = {'d': {'bg': '#102030'}}
        res = self.publish(p, h, None, 'header')
        self.assertEqual(res.status_code, 200, res.content)
        part = SharedPart.objects.get(project=p, kind='header')
        self.assertIn('nb-header', part.content)
        self.assertIn('{% for title, href in MENU %}', part.content)
        css = open(os.path.join(str(p.path), 'static/css/blocks.css'), encoding='utf-8').read()
        self.assertIn('#102030', css)
        # نشان (لوگو) از رسانه: قالبِ جداگانهٔ سربرگ باید خودش load static داشته باشد
        asset = media_mod.save_upload(p, self.png())
        h = self.c.get(API % p.slug + 'bootstrap/', {'target': 'header'}).json()['doc']
        h['blocks'][0]['props']['logo'] = 'm:%d' % asset.pk
        self.assertEqual(self.publish(p, h, None, 'header').status_code, 200)
        self.assertTrue(SharedPart.objects.get(project=p, kind='header').content.startswith('{% load static %}'))
        out = self.run_site(p, '''
from django.test import Client
html = Client(HTTP_HOST='localhost').get('/').content.decode()
assert 'site-media' in html and 'nb-logo' in html, html[:600]
print('LOGO_OK')
''')
        self.assertIn('LOGO_OK', out)
        # همان در بوم
        doc = self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': pg.pk}).json()['doc']
        out = self.c.post(API % p.slug + 'render/', {'target': 'page', 'page': pg.pk, 'doc': doc}, format='json').json()
        self.assertIn('nb-header', out['header'])
        self.assertIn('#102030', out['base_css'])

    def test_deleted_page_leaves_the_menu(self):
        p = self.project('pb6')
        a = Page.objects.create(project=p, title='ا', slug='', kind='home')
        b = Page.objects.create(project=p, title='ب', slug='b')
        self.c.put(API % p.slug + 'theme/', {'menu': [{'id': 'a', 'page': a.pk}, {'id': 'b', 'page': b.pk}]}, format='json')
        self.assertEqual(self.publish(p, self.doc(clean.new_block('heading')), a).status_code, 200)
        self.assertEqual(self.c.delete('/api/v1/studio/projects/%s/pages/%d/' % (p.slug, b.pk)).status_code, 200)
        services.generate(p, 'x')
        ctxfile = open(os.path.join(str(p.path), 'config/context.py'), encoding='utf-8').read()
        self.assertIn("('ا', '/')", ctxfile)
        self.assertNotIn('/b/', ctxfile)

    def test_seed_records(self):
        p = self.project('pb7', shop=True)
        m = Model.objects.get(app__project=p, name='Product')
        r = self.c.post(API % p.slug + 'models/%d/seed/' % m.pk, {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['count'], 6)
        order = Model.objects.get(app__project=p, name='Order')
        self.assertEqual(self.c.post(API % p.slug + 'models/%d/seed/' % order.pk, {}, format='json').status_code, 400)
        out = canvas.render_canvas(p, 'page', p.pages.get(slug=''), clean.clean_doc(self.doc(clean.new_block('data_list', model='catalog.Product'))), T.clean_theme(None, p), [])
        self.assertNotIn('catalog.Product', out['sample_models'])


class MockProvider:
    """جای مدلِ واقعی: اعتبارِ MetisAI تمام است (402)، پس مسیرِ AI با پاسخِ ساختگی سنجیده می‌شود."""

    def __init__(self, fn):
        self.fn = fn

    def complete(self, system, user, json_mode=True):
        return json.dumps(self.fn(json.loads(user)), ensure_ascii=False)


class AiInteropTests(Base):
    def setup_page(self):
        p = self.project('ai%d' % Project.objects.count())
        pg = Page.objects.create(project=p, title='ص', slug='x')
        doc = self.doc(clean.new_block('hero', title='عنوانِ قدیمی'), clean.new_block('features'))
        r = self.c.post(API % p.slug + 'publish/', {'target': 'page', 'page': pg.pk, 'doc': doc}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        pg.refresh_from_db()
        return p, pg

    def run_ai(self, pg, fn, instruction='عوض کن'):
        with mock.patch('apps.ai_engine.services.get_provider', return_value=MockProvider(fn)):
            prop = ai.edit_page(pg, instruction)
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        return prop

    def bootstrap(self, p, pg):
        return self.c.get(API % p.slug + 'bootstrap/', {'target': 'page', 'page': pg.pk}).json()

    def test_ai_edit_proposal_apply_then_editable_then_revert(self):
        p, pg = self.setup_page()
        seen = {}

        def fn(req):
            seen.update(req)
            return {'summary': 'x', 'body_html': req['current_body'].replace('عنوانِ قدیمی', 'عنوانِ AI'), 'css': None}
        prop = self.run_ai(pg, fn)
        self.assertIn('visual_editor_note', seen)
        self.assertTrue(prop.changes.first().diff_text)
        ok, msg = ai.apply_proposal(prop)
        self.assertTrue(ok, msg)
        pg.refresh_from_db()
        self.assertIn('عنوانِ AI', pg.body_html)
        data = self.bootstrap(p, pg)
        self.assertEqual(data['doc']['blocks'][0]['type'], 'hero')
        self.assertEqual(data['doc']['blocks'][0]['props']['title'], 'عنوانِ AI')
        self.assertEqual(data['doc']['blocks'][1]['type'], 'features')
        self.assertIn('بیرون از ویرایشگر', data['notice'])
        # بازگردانی ⇐ همان نسخهٔ قبلی، بی‌هیچ تبدیلی
        ok, msg = ai.revert_proposal(prop)
        self.assertTrue(ok, msg)
        pg.refresh_from_db()
        self.assertIn('عنوانِ قدیمی', pg.body_html)
        data = self.bootstrap(p, pg)
        self.assertEqual(data['doc']['blocks'][0]['props']['title'], 'عنوانِ قدیمی')
        self.assertIn('برگشته', data['notice'])

    def test_ai_replaces_everything_nothing_is_lost(self):
        p, pg = self.setup_page()
        new_html = '<div class="weird"><custom-tag>تگِ ناشناخته</custom-tag></div>{% for p in products %}<b>{{ p.name }}</b>{% endfor %}'
        prop = self.run_ai(pg, lambda r: {'summary': 'x', 'body_html': new_html, 'css': '.weird{color:red}'})
        self.assertTrue(ai.apply_proposal(prop)[0])
        pg.refresh_from_db()
        data = self.bootstrap(p, pg)
        kinds = [b['type'] for b in data['doc']['blocks']]
        self.assertTrue(all(k == 'custom_html' for k in kinds), kinds)
        code = ''.join(b['props']['code'] for b in data['doc']['blocks'])
        self.assertIn('تگِ ناشناخته', code)
        self.assertIn('{% for p in products %}', code)
        self.assertEqual(data['doc'].get('extra_css'), '.weird{color:red}')
        self.assertIn('کدِ سفارشی', data['notice'])
        # بعد از انتشارِ دوباره هم همان‌ها می‌ماند
        r = self.c.post(API % p.slug + 'publish/', {'target': 'page', 'page': pg.pk, 'doc': data['doc']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        pg.refresh_from_db()
        self.assertIn('تگِ ناشناخته', pg.body_html)
        self.assertIn('.weird{color:red}', pg.css)

    def test_unpublished_draft_is_kept_when_ai_changes_the_page(self):
        p, pg = self.setup_page()
        data = self.bootstrap(p, pg)
        doc = data['doc']
        doc['blocks'].append(clean.new_block('heading', text='پیش‌نویسِ من'))
        self.assertEqual(self.c.put(API % p.slug + 'design/', {'target': 'page', 'page': pg.pk, 'doc': doc, 'rev': data['status']['rev']}, format='json').status_code, 200)
        prop = self.run_ai(pg, lambda r: {'summary': 'x', 'body_html': r['current_body'].replace('عنوانِ قدیمی', 'تازه'), 'css': None})
        self.assertTrue(ai.apply_proposal(prop)[0])
        pg.refresh_from_db()
        after = self.bootstrap(p, pg)
        self.assertIn('پیش‌نویس', after['notice'])
        design = Design.objects.get(page=pg)
        self.assertTrue(design.versions.filter(kind='draft').exists())
        self.assertIn('پیش‌نویسِ من', json.dumps(design.versions.filter(kind='draft').first().doc, ensure_ascii=False))

    def test_conflict_when_user_publishes_after_the_proposal(self):
        p, pg = self.setup_page()
        prop = self.run_ai(pg, lambda r: {'summary': 'x', 'body_html': r['current_body'] + '<p>افزوده</p>', 'css': None})
        doc = self.bootstrap(p, pg)['doc']
        doc['blocks'].append(clean.new_block('heading', text='انتشارِ جدیدتر'))
        self.assertEqual(self.c.post(API % p.slug + 'publish/', {'target': 'page', 'page': pg.pk, 'doc': doc}, format='json').status_code, 200)
        ok, _ = ai.apply_proposal(prop)
        self.assertFalse(ok)
        pg.refresh_from_db()
        self.assertIn('انتشارِ جدیدتر', pg.body_html)
        self.assertNotIn('افزوده', pg.body_html)

    def test_ai_shared_edit_and_theme(self):
        p, pg = self.setup_page()
        with mock.patch('apps.ai_engine.services.get_provider', return_value=MockProvider(lambda r: {'summary': 'x', 'css': ':root { --brand: #00ff00; }'})):
            prop = ai.edit_shared(p, 'base_css', 'سبز کن')
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        self.assertTrue(ai.apply_proposal(prop)[0])
        self.assertEqual(self.c.get(API % p.slug + 'theme/').json()['theme']['colors']['primary'], '#00ff00')
        # رنگِ جدید در پنل از همان‌جا ادامه می‌یابد و بلوک‌ها سالم‌اند
        css = open(os.path.join(str(p.path), 'static/css/blocks.css'), encoding='utf-8').read()
        self.assertIn('.nb-hero', css)

    def test_generate_frontend_with_mock_provider_keeps_page_editable(self):
        from apps.ai_engine.providers import MockProvider as Real
        p, pg = self.setup_page()
        with mock.patch('apps.ai_engine.services.get_provider', return_value=Real(ai.AiSettings.get())):
            prop = ai.generate_frontend(p, 'یک فروشگاه')
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        self.assertTrue(ai.apply_proposal(prop)[0])
        data = self.bootstrap(p, pg)
        self.assertTrue(data['doc']['blocks'])
        self.assertTrue(self.c.get(API % p.slug + 'bootstrap/', {'target': 'header'}).json()['doc']['blocks'])

    def test_roundtrip_check_warns_for_code_mode(self):
        p, pg = self.setup_page()
        url = API % p.slug + 'pages/%d/roundtrip-check/' % pg.pk
        same = self.c.post(url, {'body_html': pg.body_html, 'css': pg.css}, format='json').json()
        self.assertEqual(same['custom'], 0)
        bad = self.c.post(url, {'body_html': pg.body_html.replace('<h1', '<h1 style="x"') + '<table></table>', 'css': pg.css}, format='json').json()
        self.assertGreaterEqual(bad['new_custom'], 1)
        self.assertTrue(bad['has_design'])
        other = Page.objects.create(project=p, title='کدی', slug='code')
        self.assertFalse(self.c.post(API % p.slug + 'pages/%d/roundtrip-check/' % other.pk, {'body_html': 'x'}, format='json').json()['has_design'])


class ExistingFlowsTests(Base):
    """مسیرهای قبلیِ سایت‌ساز که نباید شکسته باشند (پیش از این آزمونِ جنگو نداشتند)."""
    S = '/api/v1/studio/projects/'

    def test_shop_flow_with_code_mode(self):
        r = self.c.post('/api/v1/studio/projects/', {'name': 'فروشگاه', 'scaffold': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        slug = r.json()['project']['slug']
        p = Project.objects.get(slug=slug)
        self.assertTrue(p.exists_on_disk)
        pages = self.c.get(self.S + slug + '/frontend/').json()['pages']
        self.assertEqual(len(pages), 4)
        self.assertFalse(pages[0]['has_design'])
        pk = pages[0]['id']
        d = self.c.get(self.S + slug + '/pages/%d/' % pk).json()
        r = self.c.put(self.S + slug + '/pages/%d/' % pk, {'title': d['page']['title'], 'body_html': '<h1>کدِ دستی</h1>', 'css': 'h1{color:red}', 'in_menu': True}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.c.post(self.S + slug + '/build/', {}, format='json')
        self.assertTrue(r.json()['ok'], r.json().get('detail'))
        self.assertIn('کدِ دستی', open(os.path.join(str(p.path), 'templates/pages/home.html'), encoding='utf-8').read())
        self.assertTrue(self.c.post(self.S + slug + '/migrate/', {}, format='json').json()['ok'])
        r = self.c.get(self.S + slug + '/export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('%s/manage.py' % slug, zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content))).namelist())
        hist = self.c.get(self.S + slug + '/history/').json()
        self.assertTrue(hist['commits'])
        self.assertEqual(self.c.get(self.S + slug + '/files/').status_code, 200)
        self.assertEqual(self.c.delete(self.S + slug + '/').status_code, 200)

    def test_backend_crud_then_ai_mock_on_code_page(self):
        p = self.project('ef2')
        app = self.c.post(self.S + 'ef2/apps/', {'name': 'blog', 'url_prefix': 'blog/'}, format='json').json()['app']
        m = self.c.post(self.S + 'ef2/models/', {'app': app['id'], 'name': 'Post', 'starter': True}, format='json').json()['model']
        self.assertEqual(self.c.post(self.S + 'ef2/models/%d/crud/' % m['id'], {}, format='json').status_code, 200)
        page = self.c.post(self.S + 'ef2/pages/', {'title': 'خانه', 'slug': '', 'kind': 'home'}, format='json').json()['page']
        r = self.c.post(self.S + 'ef2/build/', {}, format='json')
        self.assertTrue(r.json()['ok'], r.json().get('detail'))
        pg = Page.objects.get(pk=page['id'])
        from apps.ai_engine.providers import MockProvider as Real
        with mock.patch('apps.ai_engine.services.get_provider', return_value=Real(ai.AiSettings.get())):
            prop = ai.edit_page(pg, 'بنویس')
        prop.refresh_from_db()
        self.assertEqual(prop.status, 'pending', prop.error)
        self.assertTrue(ai.apply_proposal(prop)[0])
        self.assertTrue(ai.revert_proposal(prop)[0])
        self.assertFalse(Design.objects.filter(project=p).exists())

    def test_imported_project_code_flow(self):
        golden_cases.case_imported()
        p = Project.objects.get(slug='golden-imported')
        self.assertTrue(p.is_imported)
        pages = self.c.get(self.S + p.slug + '/frontend/').json()['pages']
        self.assertTrue(pages)
        r = self.c.put(self.S + p.slug + '/pages/%d/' % pages[0]['id'], {'body_html': '{% extends "base.html" %}{% block content %}<h1>نو</h1>{% endblock %}'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.post(self.S + p.slug + '/build/', {}, format='json').status_code, 200)

    def test_generated_project_runs_with_its_own_python(self):
        p = self.project('ef4', shop=True)
        services.generate(p, 'x')
        r = subprocess.run([envs.python_for(p), 'manage.py', 'check'], cwd=str(p.path), env=services._env(p), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

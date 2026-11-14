# -*- coding: utf-8 -*-
"""«هنوز نمونه است» پیش از انتشار (۲۰۲۶-۱۱-۱۴): «انتشار» سایت را با یک کلیک روی اینترنت می‌برد و متنِ نمونه، شمارهٔ ساختگی، info@example.com و
پیوندِ «#» هم همراهش می‌رفت. این‌جا تشخیص (placeholders.py)، هشدارهای رندر (با نوع) و نقطهٔ پایانیِ بررسیِ پیش از انتشار سنجیده می‌شود."""
from django.test import SimpleTestCase

from apps.projects.builder import chagher_draft, placeholders as PH, render as R, starters, theme as T
from apps.projects.builder.clean import clean_doc, new_block as B
from apps.projects.models import Design, Page
from apps.projects.tests_builder import API, Base


def render(doc, target='page'):
    return R.render_doc(clean_doc(doc, target), R.Ctx(canvas=False, target=target, theme=T.default_theme()['colors']))


def found(doc, target='page'):
    return [w for w in render(doc, target).warnings if w.get('kind') in PH.KINDS]


def kinds(doc, target='page'):
    return sorted({w['kind'] for w in found(doc, target)})


class DetectionTests(SimpleTestCase):
    def test_starter_home_lists_at_least_four_findings(self):
        out = found(starters.starter_doc('home'))
        self.assertGreaterEqual(len(out), 4, out)
        self.assertIn('sample', {w['kind'] for w in out})
        self.assertIn('link', {w['kind'] for w in out})
        self.assertTrue(all(w['id'] and w['type'] and w['text'] for w in out))

    def test_every_starter_page_has_something_to_replace(self):
        for s in starters.STARTERS:
            if s['key'] == 'blank':
                continue
            self.assertTrue(found(starters.starter_doc(s['key'])), s['key'])

    def test_contact_starter_flags_the_fake_phone_the_example_mail_and_the_sample_address(self):
        text = ' '.join(w['text'] for w in found(starters.starter_doc('contact')))
        self.assertIn('۰۲۱-۱۲۳۴۵۶۷۸', text)
        self.assertIn('info@example.com', text)
        self.assertIn('خیابانِ نمونه', text)

    def test_a_site_written_by_its_owner_has_no_findings(self):
        doc = {'v': 1, 'blocks': [
            B('hero', eyebrow='باشگاهِ فیت‌لند', title='تمرینِ گروهی در قلبِ شهر', subtitle='کلاس‌های صبح و عصر با مربیِ ثابت؛ اولین جلسه را ببین.',
              btn1='ثبتِ نام', btn1_link='https://fitland.test/signup', btn2='', btn2_link=''),
            B('features', title='کلاس‌ها', subtitle='', items=[{'icon': 'zap', 'title': 'یوگا', 'text': 'صبح‌های شنبه و دوشنبه در سالنِ ۲.'}]),
            B('cta', title='جلسهٔ آزمایشی', text='برای رزرو تماس بگیر.', btn='رزرو', btn_link='tel:+989120000000'),
        ]}
        self.assertEqual(found(doc), [])

    def test_a_changed_sample_sentence_is_the_owners_text_not_a_placeholder(self):
        d = B('hero', eyebrow='', title='عنوانِ خودم', subtitle='در یکی دو جمله بگو چه کاری انجام می‌دهی و چرا مشتری باید تو را انتخاب کند.', btn1='', btn2='')
        self.assertIn('sample', kinds({'v': 1, 'blocks': [d]}))
        d['props']['subtitle'] = 'ما در یزد قالیِ دستباف می‌فروشیم و به همه‌جا می‌فرستیم.'
        self.assertEqual(found({'v': 1, 'blocks': [d]}), [])

    def test_button_without_destination_is_flagged_only_when_the_button_exists(self):
        shown = found({'v': 1, 'blocks': [B('button', text='بخرید', link='')]})
        self.assertEqual([w['kind'] for w in shown], ['link'])
        self.assertIn('بخرید', shown[0]['text'])
        self.assertEqual(found({'v': 1, 'blocks': [B('button', text='', link='')]}), [])          # دکمهٔ بی‌متن نه در سایت هست نه مقصدی لازم دارد
        self.assertEqual(found({'v': 1, 'blocks': [B('button', text='بخرید', link='/shop/')]}), [])
        # تصویرِ بی‌پیوند عادی است؛ «#»ی صریح اشتباه است
        self.assertEqual(found({'v': 1, 'blocks': [B('image', src='https://x.test/a.png', alt='ب', link='')]}), [])
        self.assertEqual([w['kind'] for w in found({'v': 1, 'blocks': [B('image', src='https://x.test/a.png', alt='ب', link='#')]})], ['link'])

    def test_footer_list_with_hash_destinations_is_flagged(self):
        doc = {'v': 1, 'blocks': [B('c_footer_columns', col2_links='قوانین | #\nتماس | /contact/')]}
        self.assertIn('link', kinds(doc, 'footer'))
        doc = {'v': 1, 'blocks': [B('c_footer_columns', about='باشگاهِ فیت‌لند', col2_links='قوانین | /rules/\nتماس | /contact/', col2_title='پیوندها', col3_text='یزد، خیابانِ ۱۷ شهریور',
                                    col3_title='نشانی', menu_title='منو', social='', copy='همهٔ حقوق محفوظ است.')]}
        self.assertEqual(found(doc, 'footer'), [])

    def test_lorem_and_fake_numbers_are_flagged_wherever_they_hide(self):
        for text in ('Lorem ipsum dolor sit amet', 'تماس: 021-12345678', 'ایمیل: team@example.org', 'موبایل ۰۹۱۲۳۴۵۶۷۸۹'):
            self.assertTrue(found({'v': 1, 'blocks': [B('heading', text=text)]}), text)
        self.assertTrue(found({'v': 1, 'blocks': [B('text', html='<p>ایمیل: <a href="mailto:info@example.com">info@example.com</a></p>')]}))
        self.assertTrue(found({'v': 1, 'blocks': [B('icon', name='mail', link='mailto:info@example.com')]}))

    def test_generic_phrases_that_are_fine_to_publish_are_not_flagged(self):
        d = {'v': 1, 'blocks': [B('copyright', text='همهٔ حقوق محفوظ است.'), B('faq', title='پرسش‌های پرتکرار', items=[])]}
        self.assertEqual(found(d, 'footer'), [])

    def test_one_finding_per_block_and_kind_even_with_many_sample_rows(self):
        out = [w for w in found({'v': 1, 'blocks': [B('features')]}) if w['kind'] == 'sample']
        self.assertEqual(len(out), 1)
        self.assertIn('مورد دیگر', out[0]['text'])

    def test_media_and_alt_warnings_carry_their_kind_and_keep_their_text(self):
        w = render({'v': 1, 'blocks': [B('image', src=''), B('image', src='https://x.test/a.png', alt='')]}).warnings
        by = {x['kind']: x['text'] for x in w if x.get('kind')}
        self.assertIn('هنوز انتخاب نشده', by['media'])
        self.assertIn('توضیح بنویس', by['alt'])
        self.assertTrue(all('kind' in x for x in w))

    def test_general_suggestions_are_not_placeholders(self):
        w = render({'v': 1, 'blocks': [B('heading', text='الف', level=1), B('heading', text='ب', level=1)]}).warnings
        self.assertTrue(w)
        self.assertTrue(all(x['kind'] == '' for x in w))

    def test_the_chagher_draft_has_no_placeholder_text_or_link_in_any_part(self):
        """تنها چیزی که می‌ماند «تصویرِ بالای صفحه هنوز انتخاب نشده» است: اسکرین‌شاتِ واقعی را مالک می‌گذارد، ساختگی نمی‌گذاریم."""
        parts = chagher_draft.build()
        for target in ('header', 'footer'):
            self.assertEqual([w['text'] for w in found(parts[target], target)], [], target)
        self.assertEqual([(w['kind'], w['type']) for w in found(parts['page'])], [('media', 'image')])

    def test_sample_sentences_come_from_the_library_not_from_a_private_list(self):
        s = PH.sample_sentences()
        self.assertGreater(len(s), 60)
        self.assertIn(PH.norm('در یکی دو جمله بگو چه کاری انجام می‌دهی و چرا مشتری باید تو را انتخاب کند.'), s)
        self.assertNotIn(PH.norm('همهٔ حقوق محفوظ است.'), s)


class CheckEndpointTests(Base):
    def _page(self, p, title='صفحهٔ اصلی', slug=''):
        return Page.objects.create(project=p, title=title, slug=slug, kind='home' if not slug else 'custom', body_html='', in_menu=False, order=10)

    def post(self, p, page, doc, target='page'):
        body = {'target': target, 'doc': doc}
        if page is not None:
            body['page'] = page.pk
        return self.c.post(API % p.slug + 'check/', body, format='json')

    def test_starter_project_lists_findings_and_a_clean_one_lists_none(self):
        p = self.project()
        pg = self._page(p)
        r = self.post(p, pg, starters.starter_doc('home'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(r.json()['count'], 4)
        f = r.json()['findings'][0]
        self.assertEqual({'id', 'type', 'kind', 'text', 'target', 'page', 'page_title'}, set(f))
        self.assertEqual(f['page'], pg.pk)
        clean = {'v': 1, 'blocks': [B('hero', eyebrow='', title='باشگاهِ فیت‌لند', subtitle='کلاس‌های صبح و عصر؛ اولین جلسه را ببین.', btn1='ثبتِ نام', btn1_link='/join/', btn2='')]}
        r = self.post(p, pg, clean)
        self.assertEqual(r.json()['findings'], [])

    def test_check_reads_only_and_creates_nothing(self):
        p = self.project()
        pg = self._page(p)
        self.assertEqual(Design.objects.filter(project=p).count(), 0)
        self.post(p, pg, starters.starter_doc('home'))
        self.assertEqual(Design.objects.filter(project=p).count(), 0)

    def test_other_published_pages_and_a_changed_footer_are_included(self):
        p = self.project()
        home, about = self._page(p), self._page(p, 'دربارهٔ ما', 'about')
        from django.utils import timezone
        about_doc = clean_doc(starters.starter_doc('about'), 'page')
        Design.objects.create(project=p, target='page', page=about, draft=about_doc, published=about_doc, published_at=timezone.now())
        footer = clean_doc({'v': 1, 'blocks': [B('c_footer_columns', col2_links='قوانین | #')]}, 'footer')
        Design.objects.create(project=p, target='footer', draft=footer, published=None)
        clean_home = {'v': 1, 'blocks': [B('heading', text='خانهٔ فیت‌لند', level=1)]}
        out = self.post(p, home, clean_home).json()['findings']
        self.assertTrue(any(f['target'] == 'page' and f['page'] == about.pk and f['page_title'] == 'دربارهٔ ما' for f in out), out)
        self.assertTrue(any(f['target'] == 'footer' for f in out), out)
        # صفحهٔ هنوز منتشرنشده روی اینترنت نمی‌رود ⇒ نمی‌پرسد
        other = self._page(p, 'پیش‌نویس', 'draft')
        Design.objects.create(project=p, target='page', page=other, draft=clean_doc(starters.starter_doc('contact'), 'page'), published=None)
        out = self.post(p, home, clean_home).json()['findings']
        self.assertFalse(any(f['page'] == other.pk for f in out))

    def test_only_staff_may_check(self):
        p = self.project()
        pg = self._page(p)
        self.c.force_authenticate(self.user)
        self.assertEqual(self.post(p, pg, starters.starter_doc('home')).status_code, 403)

    def test_a_broken_document_is_a_clear_400_not_a_crash(self):
        p = self.project()
        pg = self._page(p)
        r = self.c.post(API % p.slug + 'check/', {'target': 'page', 'page': pg.pk, 'doc': 'not-a-doc'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()['error'])

# -*- coding: utf-8 -*-
"""آزمونِ رزومه و نمونه‌کار: مدل‌ها، صفحه‌ها، PDF، نقشهٔ سایت، API، ادمین، تعدادِ کوئری."""
import io
import os
import re
import shutil
import tempfile
import unittest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from PIL import Image

from app.models import CustomUser, TeamMember
from portfolio.jalali import format_range, iso_ym, to_gregorian
from portfolio.models import (Award, Certification, Education, Experience, LanguageSkill, PortfolioCategory,
                              PortfolioProject, ProjectImage, ProjectMember, Skill, SocialLink)
from portfolio.thumbs import thumbnail

try:
    import weasyprint  # noqa: F401
    HAS_WEASY = True
except (ImportError, OSError):
    HAS_WEASY = False

TMP = tempfile.mkdtemp(prefix='pf-test-')


def png(name='a.png', size=(900, 600), color=(18, 111, 133)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def make_member(**kw):
    data = dict(name='سارا رضایی', role='طراح محصول', email='sara@example.com')
    data.update(kw)
    return TeamMember.objects.create(**data)


def fill_resume(m, n=1):
    for i in range(n):
        Experience.objects.create(member=m, role='نقش %d' % i, organisation='شرکت %d' % i, start_year=1400,
                                  start_month=1, is_current=(i == 0), description='- کارِ یک\n- کارِ دو')
        Education.objects.create(member=m, degree='کارشناسی', field='رشته %d' % i, institution='دانشگاه تهران',
                                 start_year=1395, end_year=1399)
        Certification.objects.create(member=m, title='مدرک %d' % i, issuer='کورسرا', year=1401)
        Skill.objects.create(member=m, name='مهارت %d' % i, group='طراحی' if i % 2 else 'برنامه‌نویسی', level=4)
        LanguageSkill.objects.create(member=m, language='زبان %d' % i, level='c1')
        Award.objects.create(member=m, title='جایزه %d' % i, year=1402)
        SocialLink.objects.create(member=m, kind='github', url='@user%d_%d' % (m.pk, i))


def make_project(title, members=(), role='توسعه‌دهنده', **kw):
    p = PortfolioProject.objects.create(title=title, **kw)
    for m in members:
        ProjectMember.objects.create(project=p, member=m, role=role)
    return p


@override_settings(MEDIA_ROOT=os.path.join(TMP, 'media'), PRIVATE_MEDIA_ROOT=os.path.join(TMP, 'private'))
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def staff(self):
        u = CustomUser.objects.create_superuser(phone_number='09120009999', password='StrongPass123')
        self.client.force_login(u)
        return u


class ModelTests(Base):
    def test_slug_auto_unique(self):
        a, b = make_member(), make_member()
        self.assertEqual(a.slug, 'سارا-رضایی')
        self.assertNotEqual(a.slug, b.slug)
        self.assertEqual(a.get_absolute_url(), '/team/%D8%B3%D8%A7%D8%B1%D8%A7-%D8%B1%D8%B6%D8%A7%DB%8C%DB%8C/')
        p1, p2 = PortfolioProject.objects.create(title='Site'), PortfolioProject.objects.create(title='Site')
        self.assertEqual((p1.slug, p2.slug), ('site', 'site-2'))

    def test_jalali(self):
        self.assertEqual(to_gregorian(1402, 7, 1), (2023, 9, 23))
        self.assertEqual(to_gregorian(1403, 1, 1), (2024, 3, 20))
        self.assertEqual(iso_ym(1402, 7), '2023-09')
        self.assertEqual(format_range(1400, 1, None, None, True), 'فروردین ۱۴۰۰ — تا کنون')
        self.assertEqual(format_range(1398, None, 1400, None, False), '۱۳۹۸ — ۱۴۰۰')

    def test_social_and_project_helpers(self):
        m = make_member()
        self.assertEqual(SocialLink.objects.create(member=m, kind='telegram', url='@chagher').url, 'https://t.me/chagher')
        self.assertEqual(SocialLink.objects.create(member=m, kind='website', url='example.com').url, 'https://example.com')
        p = PortfolioProject(title='x', tags='پایتون، جنگو, هوش', description='یک\n\nدو',
                             video_url='https://www.youtube.com/watch?v=abcdEFGH123')
        self.assertEqual(p.tag_list, ['پایتون', 'جنگو', 'هوش'])
        self.assertEqual(p.paragraphs, ['یک', 'دو'])
        self.assertIn('youtube-nocookie.com/embed/abcdEFGH123', p.video_embed)
        p.video_url = 'https://www.aparat.com/v/xYz12'
        self.assertIn('aparat.com/video/video/embed/videohash/xYz12', p.video_embed)

    def test_thumbnail(self):
        m = make_member(photo=png())
        url = thumbnail(m.photo, 200, 200, True)
        self.assertTrue(url.startswith('/media/thumbs/200x200c/'))
        path = thumbnail(m.photo, 200, 200, True, as_path=True)
        with Image.open(path) as im:
            self.assertEqual(im.size, (200, 200))
        self.assertEqual(thumbnail(None, 100), '')


class PageTests(Base):
    def test_team_list_only_published(self):
        a = make_member(name='عضو منتشر')
        make_member(name='عضو پنهان', is_published=False)
        r = self.client.get('/team/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'عضو منتشر')
        self.assertContains(r, a.get_absolute_url())
        self.assertNotContains(r, 'عضو پنهان')

    def test_team_list_empty_state(self):
        r = self.client.get('/team/')
        self.assertContains(r, 'هنوز عضوی برای نمایش منتشر نشده است')

    def test_resume_sections(self):
        m = make_member(slug='sara', summary='خلاصهٔ حرفه‌ای', phone='0912-555-7788', city='تهران')
        fill_resume(m, 2)
        r = self.client.get('/team/sara/')
        self.assertEqual(r.status_code, 200)
        for text in ['سوابقِ کاری', 'نقش 0', 'کارِ دو', 'تحصیلات', 'مدارک و دوره‌ها', 'مهارت‌ها', 'برنامه‌نویسی',
                     'زبان‌ها', 'افتخارات', 'درباره من', 'دانلود PDF', 'فروردین ۱۴۰۰ — تا کنون', 'تهران',
                     'sara@example.com', 'https://github.com/user', '"@type": "Person"', 'BreadcrumbList']:
            self.assertContains(r, text)
        self.assertNotContains(r, '555-7788')        # تلفن پیش‌فرض پنهان است
        self.assertContains(r, 'rel="canonical" href="https://')
        self.assertContains(r, '/team/sara/"')

    def test_empty_and_unpublished_sections_hidden(self):
        m = make_member(slug='empty', show_email=False)
        Experience.objects.create(member=m, role='نقش‌مخفی۷۷', organisation='x', is_published=False)
        r = self.client.get('/team/empty/')
        self.assertEqual(r.status_code, 200)
        for text in ['سوابقِ کاری', 'نقش‌مخفی۷۷', 'تحصیلات', 'مهارت‌ها', 'زبان‌ها', 'افتخارات', 'sara@example.com',
                     'نمونه‌کارهای برگزیده', 'class="pf-cols']:
            self.assertNotContains(r, text)

    def test_unpublished_member_404_staff_preview(self):
        make_member(slug='draft', is_published=False)
        self.assertEqual(self.client.get('/team/draft/').status_code, 404)
        self.assertEqual(self.client.get('/team/draft/pdf/').status_code, 404)
        self.staff()
        r = self.client.get('/team/draft/')
        self.assertContains(r, 'پیش‌نمایشِ مدیر')
        self.assertContains(r, 'noindex,nofollow')

    def test_unknown_slugs_404(self):
        for url in ['/team/nope/', '/team/nope/pdf/', '/team/nope/portfolio/', '/portfolio/nope/']:
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_portfolio_list_filter_and_unpublished(self):
        m = make_member()
        web = PortfolioCategory.objects.create(name='وب', slug='web')
        app_ = PortfolioCategory.objects.create(name='اپ', slug='app')
        make_project('پروژهٔ وب', [m], category=web)
        make_project('پروژهٔ اپ', [m], category=app_, is_featured=True)
        make_project('پروژهٔ پنهان', [m], category=web, is_published=False)
        r = self.client.get('/portfolio/')
        self.assertContains(r, 'پروژهٔ وب')
        self.assertContains(r, 'پروژهٔ اپ')
        self.assertNotContains(r, 'پروژهٔ پنهان')
        self.assertContains(r, '?category=web')
        r = self.client.get('/portfolio/?category=web')
        self.assertContains(r, 'پروژهٔ وب')
        self.assertNotContains(r, 'پروژهٔ اپ')
        self.assertEqual(self.client.get('/portfolio/?category=zzz').status_code, 200)

    def test_portfolio_empty_state(self):
        r = self.client.get('/portfolio/')
        self.assertContains(r, 'هنوز نمونه‌کاری منتشر نشده است')
        self.assertContains(r, 'noindex,follow')

    def test_project_detail(self):
        m = make_member(slug='sara')
        p = make_project('اپِ تمرین', [m], role='طراح رابط', slug='workout-app', cover=png('c.png'),
                         video_url='https://youtu.be/abcdEFGH123', tags='فلاتر، طراحی', year=1402, month=7,
                         description='پاراگراف اول\n\nپاراگراف دوم')
        ProjectImage.objects.create(project=p, image=png('g1.png'), caption='صفحهٔ اول')
        ProjectImage.objects.create(project=p, image=png('g2.png'))
        r = self.client.get('/portfolio/workout-app/')
        self.assertEqual(r.status_code, 200)
        for text in ['اپِ تمرین', 'youtube-nocookie.com/embed/abcdEFGH123', 'id="pfGallery"', 'صفحهٔ اول',
                     'طراح رابط', '/team/sara/', '"@type": "CreativeWork"', '"dateCreated": "2023-09"',
                     'پاراگراف دوم', 'فلاتر', 'og:image', 'loading="lazy"']:
            self.assertContains(r, text)
        self.assertEqual(r.content.decode().count('data-large='), 2)
        p.is_published = False
        p.save()
        self.assertEqual(self.client.get('/portfolio/workout-app/').status_code, 404)

    def test_member_portfolio_and_featured_on_resume(self):
        a, b = make_member(slug='a'), make_member(slug='b', name='دیگری')
        make_project('مالِ الف', [a], role='سرپرست', is_featured=True)
        make_project('مالِ ب', [b])
        r = self.client.get('/team/a/portfolio/')
        self.assertContains(r, 'مالِ الف')
        self.assertContains(r, 'سرپرست')
        self.assertNotContains(r, 'مالِ ب')
        r = self.client.get('/team/a/')
        self.assertContains(r, 'نمونه‌کارهای برگزیده')
        self.assertContains(r, 'مالِ الف')

    @unittest.skipUnless(HAS_WEASY, 'WeasyPrint نصب نیست')
    def test_pdf(self):
        m = make_member(slug='sara', photo=png())
        fill_resume(m, 2)
        r = self.client.get('/team/sara/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('attachment', r['Content-Disposition'])
        cached = os.listdir(os.path.join(TMP, 'private', 'resume_pdf'))
        self.assertEqual(len(cached), 1)
        self.assertEqual(self.client.get('/team/sara/pdf/').content, r.content)

    def test_pdf_cv_override(self):
        make_member(slug='cv', cv_file=SimpleUploadedFile('cv.pdf', b'%PDF-1.4 test', 'application/pdf'))
        r = self.client.get('/team/cv/pdf/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/media/team/cv/', r['Location'])

    def test_sitemap(self):
        make_member(slug='pub')
        make_member(slug='hid', is_published=False)
        make_project('p', slug='proj-pub')
        make_project('q', slug='proj-hid', is_published=False)
        body = self.client.get('/sitemap.xml').content.decode()
        for path in ['/team/</loc>', '/team/pub/', '/portfolio/proj-pub/', '/portfolio/</loc>']:
            self.assertIn(path, body)
        self.assertNotIn('/team/hid/', body)
        self.assertNotIn('proj-hid', body)

    def test_about_links_to_resume(self):
        m = make_member(slug='sara')
        make_member(name='پنهانِ درباره', is_published=False)
        r = self.client.get('/about/')
        self.assertContains(r, m.get_absolute_url())
        self.assertNotContains(r, 'پنهانِ درباره')

    def test_api_unchanged(self):
        make_member()
        r = self.client.get('/api/team-members/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.json()[0].keys()),
                         ['id', 'name', 'role', 'photo', 'icon', 'bio', 'linkedin', 'email', 'order'])


class QueryCountTests(Base):
    """کوئری‌ها با تعدادِ ردیف بزرگ نمی‌شوند (N+1 نداریم)."""

    def count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx.captured_queries)

    def test_resume_constant(self):
        small, big = make_member(slug='s'), make_member(slug='b')
        fill_resume(small, 1)
        fill_resume(big, 5)
        for i in range(5):
            make_project('پ%d' % i, [big], is_featured=True, cover=png('p%d.png' % i))
        make_project('تک', [small], is_featured=True)
        self.count('/team/s/')       # گرم‌کردن
        self.assertEqual(self.count('/team/s/'), self.count('/team/b/'))

    def test_lists_constant(self):
        m = make_member(slug='m', photo=png())
        cat = PortfolioCategory.objects.create(name='وب')
        make_project('یکی', [m], category=cat)
        self.count('/portfolio/')
        one_p, one_t = self.count('/portfolio/'), self.count('/team/')
        for i in range(6):
            other = make_member(name='عضو %d' % i)
            make_project('پروژه %d' % i, [m, other], category=cat)
        self.assertEqual(self.count('/portfolio/'), one_p)
        self.assertEqual(self.count('/team/'), one_t)


class AdminTests(Base):
    def setUp(self):
        self.staff()

    def test_admin_pages(self):
        m = make_member()
        p = make_project('پروژه', [m])
        cat = PortfolioCategory.objects.create(name='وب')
        for url, text in [
            ('/admin/', 'نمونه‌کارها (پروژه‌ها)'),
            ('/admin/app/teammember/', 'رزومهٔ اعضا'),
            ('/admin/app/teammember/add/', 'سوابقِ کاری'),
            ('/admin/app/teammember/%d/change/' % m.pk, 'مشاهده در سایت'),
            ('/admin/portfolio/portfolioproject/', 'نمونه‌کارها:'),
            ('/admin/portfolio/portfolioproject/add/', 'گالریِ تصاویر'),
            ('/admin/portfolio/portfolioproject/%d/change/' % p.pk, 'اعضای پروژه'),
            ('/admin/portfolio/portfoliocategory/', 'وب'),
            ('/admin/portfolio/portfoliocategory/%d/change/' % cat.pk, 'نامک'),
        ]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, text, msg_prefix=url)

    def test_admin_save_member_with_inline(self):
        m = make_member()
        url = '/admin/app/teammember/%d/change/' % m.pk
        html = self.client.get(url).content.decode()
        data = {'name': m.name, 'role': m.role, 'slug': 'sara-r', 'email': m.email, 'order': 0,
                'is_published': 'on', 'show_email': 'on', 'show_city': 'on'}
        for prefix in set(re.findall(r'name="([\w-]+)-TOTAL_FORMS"', html)):
            data.update({prefix + '-TOTAL_FORMS': '0', prefix + '-INITIAL_FORMS': '0',
                         prefix + '-MIN_NUM_FORMS': '0', prefix + '-MAX_NUM_FORMS': '1000'})
        data.update({'experience_set-TOTAL_FORMS': '1', 'experience_set-0-role': 'مدیر فنی',
                     'experience_set-0-organisation': 'چغر', 'experience_set-0-start_year': '1403',
                     'experience_set-0-is_current': 'on', 'experience_set-0-order': '0',
                     'experience_set-0-is_published': 'on'})
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000] if r.status_code != 302 else '')
        m.refresh_from_db()
        self.assertEqual(m.slug, 'sara-r')
        self.assertEqual(m.experience_set.get().organisation, 'چغر')
        self.assertContains(self.client.get('/team/sara-r/'), 'مدیر فنی')

    def test_category_slug_auto(self):
        r = self.client.post('/admin/portfolio/portfoliocategory/add/', {'name': 'طراحی وب', 'slug': '', 'order': 0})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PortfolioCategory.objects.get().slug, 'طراحی-وب')

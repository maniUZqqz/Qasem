# -*- coding: utf-8 -*-
"""تست‌های API محتوای عمومی و صفحات سایت (تمپلیت)"""
from django.test import TestCase
from rest_framework import status

from app.models import BlogPost, ContactMessage, Feature, HomePage, TeamMember
from .utils import BaseAPITestCase, create_user


class ContentAPITests(BaseAPITestCase):
    def test_homepage_404_when_empty(self):
        response = self.client.get('/api/homepage/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_homepage_returns_active(self):
        HomePage.objects.create(title='عنوان', subtitle='زیرعنوان', description='توضیح', is_active=True)
        response = self.client.get('/api/homepage/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'عنوان')

    def test_features_only_active(self):
        Feature.objects.create(title='فعال', description='-', is_active=True)
        Feature.objects.create(title='غیرفعال', description='-', is_active=False)
        response = self.client.get('/api/features/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], 'فعال')

    def test_team_members_list(self):
        TeamMember.objects.create(name='علی', role='توسعه‌دهنده')
        response = self.client.get('/api/team-members/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_contact_message_created(self):
        response = self.client.post('/api/contact/', {
            'name': 'علی',
            'email': 'ali@example.com',
            'subject': 'سوال',
            'message': 'سلام',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_contact_message_invalid_email(self):
        response = self.client.post('/api/contact/', {
            'name': 'علی',
            'email': 'not-an-email',
            'subject': 'سوال',
            'message': 'سلام',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_blog_lists_only_published(self):
        author = create_user()
        BlogPost.objects.create(title='منتشر', slug='pub', author=author,
                                summary='-', content='-', is_published=True)
        BlogPost.objects.create(title='پیش‌نویس', slug='draft', author=author,
                                summary='-', content='-', is_published=False)
        response = self.client.get('/api/blog/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        # جزئیات با slug
        response = self.client.get('/api/blog/pub/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get('/api/blog/draft/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TemplatePagesTests(TestCase):
    """صفحات معرفی سایت باید بدون خطا رندر شوند"""

    def test_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_blog_list_page(self):
        response = self.client.get('/blog/')
        self.assertEqual(response.status_code, 200)

    def test_blog_detail_page(self):
        author = create_user()
        BlogPost.objects.create(title='پست', slug='post-1', author=author,
                                summary='-', content='-', is_published=True)
        response = self.client.get('/blog/post-1/')
        self.assertEqual(response.status_code, 200)

    def test_blog_detail_unpublished_404(self):
        author = create_user()
        BlogPost.objects.create(title='پیش‌نویس', slug='draft-1', author=author,
                                summary='-', content='-', is_published=False)
        response = self.client.get('/blog/draft-1/')
        self.assertEqual(response.status_code, 404)

    def test_contact_page_get_and_post(self):
        response = self.client.get('/contact/')
        self.assertEqual(response.status_code, 200)

        # ارسال فرم → ذخیره پیام + ری‌دایرکت (الگوی PRG) + نمایش پیام موفقیت
        response = self.client.post('/contact/', {
            'name': 'علی', 'email': 'ali@example.com',
            'subject': 'سوال', 'message': 'سلام',
        })
        self.assertEqual(response.status_code, 302)
        # سایت زیرِ /chagher بالا می‌آید، پس redirect هم همان پیشوند را دارد؛
        # کلاینتِ آزمون این پیشوند را نمی‌شناسد و باید دستی برداشته شود.
        from django.conf import settings as _st
        target = response['Location']
        prefix = getattr(_st, 'FORCE_SCRIPT_NAME', '') or ''
        if prefix and target.startswith(prefix):
            target = target[len(prefix):]
        response = self.client.get(target)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertContains(response, 'پیام شما با موفقیت ارسال شد')

    def test_about_page(self):
        response = self.client.get('/about/')
        self.assertEqual(response.status_code, 200)

    def test_features_page(self):
        response = self.client.get('/features/')
        self.assertEqual(response.status_code, 200)

    def test_sitemap(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)

    def test_robots_txt(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)

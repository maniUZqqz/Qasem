from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import BlogPost


class StaticViewSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return ['home', 'features', 'blog_list', 'about', 'contact']

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        priorities = {
            'home': 1.0,
            'features': 0.9,
            'blog_list': 0.9,
            'about': 0.6,
            'contact': 0.7,
        }
        return priorities.get(item, 0.5)


class BlogPostSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return BlogPost.objects.filter(is_published=True).order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

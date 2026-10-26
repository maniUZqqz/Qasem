from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from app.models import TeamMember

from .models import PortfolioProject


class TeamPagesSitemap(Sitemap):
    """/team/ همیشه؛ /portfolio/ فقط وقتی پروژهٔ منتشرشده‌ای هست (صفحهٔ خالی در نقشه نه)."""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        names = ['team-list']
        if PortfolioProject.objects.filter(is_published=True).exists():
            names.append('portfolio-list')
        return names

    def location(self, item):
        return reverse(item)


class TeamMemberSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return TeamMember.objects.filter(is_published=True).exclude(slug='').order_by('order', 'id')

    def lastmod(self, obj):
        return obj.updated_at


class PortfolioProjectSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return PortfolioProject.objects.filter(is_published=True).order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

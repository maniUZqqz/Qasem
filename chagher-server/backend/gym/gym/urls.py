from django.urls import path, include
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from app import views_panel as panel_views
from app.views import (home_page, blog_list, blog_detail, contact_page, about_page,
                       features_page, exercise_detail_page, exercise_list_page)
from app.sitemaps import StaticViewSitemap, BlogPostSitemap

sitemaps = {
    'static': StaticViewSitemap,
    'blog': BlogPostSitemap,
}

urlpatterns = [
    # ==================== Admin Panel ====================
    path('admin/', admin.site.urls),

    # ==================== کتابخانهٔ حرکت‌ها (لینکِ داخلِ PDF) ====================
    path('exercises/', exercise_list_page, name='exercise-list'),
    path('exercise/<str:external_id>/', exercise_detail_page, name='exercise-detail'),

    # ==================== API Endpoints ====================
    path('api/', include('app.urls')),

    # ==================== Swagger & API Documentation ====================
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # ==================== صفحات معرفی (Template Pages) ====================
    path('', home_page, name='home'),
    path('blog/', blog_list, name='blog_list'),
    path('blog/<slug:slug>/', blog_detail, name='blog_detail'),
    path('contact/', contact_page, name='contact'),

    # پنلِ وب — همان قابلیت‌های تازه با مرورگرِ گوشی (تا رسیدنِ سورسِ فلاتر)
    path('form-check/<str:external_id>/', panel_views.form_check_page, name='form-check-page'),
    path('panel/sso/', panel_views.panel_sso, name='panel-sso'),
    path('panel/login/', panel_views.panel_login, name='panel-login'),
    path('panel/signup/', panel_views.panel_signup, name='panel-signup'),
    path('data-coverage/', panel_views.data_coverage, name='data-coverage'),
    path('panel/logout/', panel_views.panel_logout, name='panel-logout'),
    path('panel/manual-program/', panel_views.panel_manual_program, name='panel-manual-program'),
    path('panel/scan/', panel_views.panel_scan, name='panel-scan'),
    path('panel/me/', panel_views.panel_me, name='panel-me'),
    path('panel/', panel_views.panel_home, name='panel-home'),
    path('about/', about_page, name='about'),
    path('features/', features_page, name='features'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path(
        'robots.txt',
        TemplateView.as_view(template_name='robots.txt', content_type='text/plain'),
        name='robots_txt'
    ),
]

# Static & Media Files
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)



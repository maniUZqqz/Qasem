from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as media_serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.jobs.health import LiveView, MetricsView, ReadyView

urlpatterns = [
    # Monitoring (phase 18). Outside /api/v1/ on purpose: a load balancer
    # probing liveness should not be versioned with the product API.
    path("healthz", LiveView.as_view(), name="healthz"),
    path("readyz", ReadyView.as_view(), name="readyz"),
    path("metrics", MetricsView.as_view(), name="metrics"),

    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.stores.urls")),
    path("api/v1/", include("apps.products.urls")),
    path("api/v1/", include("apps.ai.urls")),
    path("api/v1/", include("apps.jobs.urls")),
    path("api/v1/", include("apps.customers.urls")),
    path("api/v1/", include("apps.content.urls")),
    path("api/v1/", include("apps.campaigns.urls")),
    path("api/v1/", include("apps.analytics.urls")),
    path("api/v1/", include("apps.cms.urls")),
    path("api/v1/", include("apps.billing.urls")),
    path("api/v1/", include("apps.marketing.urls")),
    path("api/v1/", include("apps.api_platform.urls")),
    path("api/v1/", include("apps.regen.urls")),            # بازسازیِ یک تکه از وسطِ ویدیو
    # NMarketing: ابزارهای ادغام‌شده
    path("api/v1/compute/", include("apps.compute.urls")),   # سرورهای پردازش (گره‌ها + پنل)
    path("api/v1/panel/", include("apps.panel.urls")),       # دفترِ صفحه‌ها/قابلیت‌های پنل (خاموش/روشن از ادمین)
    path("api/v1/up3d/", include("apps.up3d.api_urls")),      # ویدیوی سه‌بعدی (پنل)
    path("api/v1/studio/", include("apps.projects.api_urls")),  # سایت‌ساز (پنل)
    path("3d/", include("apps.up3d.urls")),                   # پروتکلِ کارگرِ رندر + فایل‌های سه‌بعدی
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # LAN deployment serves media through Django too (product images, generated
    # videos, n8n payload URLs). Put a real web server in front if internet-facing.
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$", media_serve, {"document_root": settings.MEDIA_ROOT}
        )
    ]

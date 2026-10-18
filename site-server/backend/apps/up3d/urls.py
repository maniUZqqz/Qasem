"""نشانی‌های «ویدیوی سه‌بعدی» که باید بی‌سرآیندِ احراز هویت زیرِ /3d/ بمانند (config/urls.py: path("3d/", ...)):

  /3d/asset-file/<kind>/<id>/<name>   تصویر/پیش‌نمایشِ دارایی (با <img>/<video> بار می‌شود — AllowAny)
  /3d/api/worker/...                  پروتکلِ کارگرِ رندر (Authorization: Worker <token>)
  /3d/files/...                       خروجیِ کارها و بارگذاری‌ها (روی سرور nginx مستقیم می‌دهد)

نماهای JSON ِ پنل در api_urls.py زیرِ /api/v1/up3d/ هستند.
"""
import os

from django.conf import settings
from django.urls import path, re_path
from django.views.static import serve

from . import api

urlpatterns = [
    path('asset-file/<str:kind>/<str:asset_id>/<str:name>', api.asset_file),
    # پروتکلِ کارگرِ رندر (توکنِ کارگر یا توکنِ سرورِ پردازش)
    path('api/worker/heartbeat/', api.w_heartbeat),
    path('api/worker/bundle/', api.w_bundle),
    path('api/worker/claim/', api.w_claim),
    path('api/worker/jobs/<int:pk>/package/', api.w_package),
    path('api/worker/jobs/<int:pk>/progress/', api.w_progress),
    path('api/worker/jobs/<int:pk>/upload/', api.w_upload),
    path('api/worker/jobs/<int:pk>/finish/', api.w_finish),
]

# خروجی‌ها (ویدئو، پوستر، GLB): روی سرور nginx مستقیم می‌دهد؛ این‌جا برای اجرای بی‌nginx
if os.environ.get('UP3D_SERVE_FILES', '1') == '1':
    urlpatterns += [
        re_path(r'^files/jobs/(?P<path>.*)$', serve, {'document_root': str(settings.UP3D_DATA_DIR / 'jobs')}),
        re_path(r'^files/uploads/(?P<path>.*)$', serve, {'document_root': str(settings.UP3D_DATA_DIR / 'uploads')}),
    ]

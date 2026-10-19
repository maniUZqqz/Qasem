"""نشانی‌های JSON ِ پنلِ «ویدیوی سه‌بعدی» — زیرِ /api/v1/up3d/ (config/urls.py):

    path("api/v1/up3d/", include("apps.up3d.api_urls"))

همه با احراز هویتِ پیش‌فرضِ DRF (JWT ِ پنل، سشن، توکنِ API) و فقط برای کارکنان (is_staff).
پروتکلِ کارگر، تصویرِ دارایی‌ها و فایل‌های خروجی زیرِ /3d/ می‌مانند (urls.py).
"""
from django.urls import path

from . import api, panel

urlpatterns = [
    # ── پنل (جایگزینِ صفحه‌های HTML ِ قدیمی)
    path('dashboard/', panel.dashboard),
    path('status/', panel.status),
    path('templates/', panel.templates_list),
    path('catalog/', panel.catalog),
    path('assets/thumbnails/', panel.asset_thumbnails),
    path('workers/', panel.workers),
    path('workers/bundle.zip', panel.worker_bundle),
    path('workers/<int:pk>/toggle/', panel.worker_toggle),
    path('workers/<int:pk>/start-worker.bat', panel.worker_bat),
    path('upload/', panel.upload),
    path('token/', panel.api_token),
    # ── REST (همان نماهای api.py؛ SDK و curl هم همین‌ها را می‌زنند)
    path('video-projects/', api.projects),
    path('projects/', api.projects),
    path('video-projects/<int:pk>/', api.project_detail),
    path('video-projects/<int:pk>/plan/', api.project_plan),
    path('video-projects/<int:pk>/scene/', api.project_scene),
    path('video-projects/<int:pk>/edit/', api.project_edit),
    path('video-projects/<int:pk>/preview/', api.project_preview),
    path('video-projects/<int:pk>/render/', api.project_render),
    path('video-projects/<int:pk>/export/', api.project_export),
    path('video-projects/<int:pk>/contact/', api.project_contact),
    path('video-projects/<int:pk>/result/', api.project_result),
    path('scenes/', api.scenes),
    path('scenes/<int:pk>/render/', api.project_preview),
    path('validate/', api.validate_doc),
    path('jobs/', api.jobs_list),
    path('jobs/<int:pk>/', api.job_detail),
    path('jobs/<int:pk>/cancel/', api.job_cancel),
    path('jobs/<int:pk>/allow-cpu/', api.job_allow_cpu),
    path('assets/', api.assets),
    path('estimate/', api.estimate),
]

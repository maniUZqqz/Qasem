"""نشانی‌های «سرورهای پردازش» — mounted at /api/v1/compute/ (config/urls.py)."""
from django.urls import path

from . import api

urlpatterns = [
    # پروتکلِ گره‌ها (Authorization: Node <token>)
    path("heartbeat/", api.heartbeat),
    path("claim/", api.claim),
    path("jobs/<uuid:uid>/package/", api.package),
    path("jobs/<uuid:uid>/progress/", api.progress),
    path("jobs/<uuid:uid>/upload/", api.upload),
    path("jobs/<uuid:uid>/finish/", api.finish),
    path("jobs/<uuid:uid>/outputs/<str:name>", api.output_file),
    path("log/", api.node_log),
    path("enroll/", api.enroll),
    # پنل (کارکنان، JWT)
    path("nodes/", api.nodes),
    path("nodes/<int:pk>/", api.node_action),
    path("nodes/<int:pk>/start.bat", api.node_bat),
    path("jobs/", api.jobs),
    path("jobs/<uuid:uid>/", api.job_detail),
    path("submit/", api.submit),
    path("nodes/<int:pk>/logs/", api.node_logs),
    path("settings/", api.compute_settings),
]

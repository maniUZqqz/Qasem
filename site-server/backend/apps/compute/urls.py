"""نشانی‌های «سرورهای پردازش» — mounted at /api/v1/compute/ (config/urls.py)."""
from django.urls import path

from . import api, views_update, views_voice

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
    # به‌روزرسانیِ کدِ گره از خودِ سایت (توکنِ گره یا کارمند) — updates.py
    path("update/", views_update.manifest),
    path("update/package/", views_update.package),
    # پنل (کارکنان، JWT)
    path("nodes/", api.nodes),
    path("nodes/<int:pk>/", api.node_action),
    path("nodes/<int:pk>/start.bat", api.node_bat),
    path("jobs/", api.jobs),
    path("jobs/<uuid:uid>/", api.job_detail),
    path("submit/", api.submit),
    path("nodes/<int:pk>/logs/", api.node_logs),
    path("nodes/<int:pk>/desired/", api.node_desired),
    path("settings/", api.compute_settings),
    # «مدل‌های صدا» of a node: switches, «تست», status, «دانلود» (staff)
    path("nodes/<int:pk>/audio/", views_voice.node_audio),
    path("nodes/<int:pk>/audio/test/", views_voice.node_audio_test),
    path("nodes/<int:pk>/audio/tests/", views_voice.node_audio_tests),
    path("nodes/<int:pk>/models/download/", views_voice.node_models_download),
    path("nodes/<int:pk>/update/", views_update.node_update),
]

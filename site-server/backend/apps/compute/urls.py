"""نشانی‌های «سرورهای پردازش» — mounted at /api/v1/compute/ (config/urls.py)."""
from django.urls import path

from . import (api, transfer, views_matting, views_models, views_ollama, views_commands, views_report, views_retry,
               views_update, views_voice)

urlpatterns = [
    # پروتکلِ گره‌ها (Authorization: Node <token>)
    path("heartbeat/", api.heartbeat),
    path("claim/", api.claim),
    path("jobs/<uuid:uid>/package/", api.package),
    path("jobs/<uuid:uid>/progress/", api.progress),
    path("jobs/<uuid:uid>/upload/", api.upload),
    path("jobs/<uuid:uid>/finish/", api.finish),
    # فایل‌های بزرگِ رندرِ نهایی: دانلودِ ازسرگیرِ ورودی‌ها (Range) و آپلودِ ازسرگیرِ خروجی (تکه‌تکه) — transfer.py
    path("jobs/<uuid:uid>/files/<str:fid>/", transfer.job_file),
    path("jobs/<uuid:uid>/chunks/<str:name>/", transfer.output_chunks),
    path("jobs/<uuid:uid>/outputs/<str:name>", api.output_file),
    path("log/", api.node_log),
    path("enroll/", api.enroll),
    path("commands/<str:cid>/", views_commands.command_report),     # گره: نتیجهٔ «دستورها» ِ پنل
    path("ollama/pullable/", views_ollama.pullable),                # فهرستِ مجازِ دانلودِ مدل (گره پیش از ollama.pull می‌پرسد)
    # به‌روزرسانیِ کدِ گره از خودِ سایت (توکنِ گره یا کارمند) — updates.py
    path("update/", views_update.manifest),
    path("update/package/", views_update.package),
    path("update/Update.bat", views_update.update_bat),            # همگانی (بی راز): دانلودِ Update.bat برای هر پوشهٔ نسخه
    path("update/bootstrap/", views_update.bootstrap),             # همگانی: ابزارِ کوچکِ به‌روزرسانی که Update.bat می‌گیرد
    path("downloads/", views_update.downloads),                    # اندازه + sha256 ِ فایل‌های بزرگِ سایت (توکنِ گره/کارمند)
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
    # جداسازیِ پس‌زمینهٔ عکس (u2netp / isnet / birefnet-lite روی گره): وضعیت، دانلود، تست
    path("matting/", views_matting.matting_status),
    path("matting/download/", views_matting.matting_download),
    path("matting/test/", views_matting.matting_test),
    # صفِ پردازش (کارکنان): فهرست، شمارش برای نوارِ بالا، لغو و تلاشِ دوباره
    path("queue/", api.queue_list),
    path("queue/summary/", api.queue_summary),
    path("queue/cancel-waiting/", api.queue_cancel_waiting),
    path("queue/retry-failed/", views_retry.queue_retry_failed),     # «پردازشِ دوبارهٔ همه» (ناموفق/لغوشده) ِ همان فیلتر
    path("store-jobs/", views_retry.store_jobs),                       # کارهای فروشگاه‌ها که ناموفق/لغو شدند
    path("store-jobs/retry-all/", views_retry.store_jobs_retry_all),
    path("store-jobs/<int:pk>/retry/", views_retry.store_job_retry),
    path("models/", views_models.models_listing),                      # همهٔ بسته‌های دانلودیِ گره‌ها (حذفِ پس‌زمینه، صدا، ویدیو…)
    path("queue/<uuid:uid>/cancel/", api.queue_cancel),
    path("queue/<uuid:uid>/retry/", api.queue_retry),
    # گزارشِ سرورهای پردازش (کارکنان): یک JSON برای کلِ صفحه، لاگ‌ها با فیلتر، خروجیِ CSV
    path("report/", views_report.report),
    path("report/logs/", views_report.logs),
    path("report/export.csv", views_report.export_csv),
    # «مدل‌های صدا» of a node: switches, «تست», status, «دانلود» (staff)
    path("nodes/<int:pk>/audio/", views_voice.node_audio),
    path("nodes/<int:pk>/audio/test/", views_voice.node_audio_test),
    path("nodes/<int:pk>/audio/tests/", views_voice.node_audio_tests),
    path("nodes/<int:pk>/models/download/", views_voice.node_models_download),
    path("nodes/<int:pk>/update/", views_update.node_update),
    path("nodes/<int:pk>/commands/", views_commands.node_commands),  # «دستورها»: به‌روزرسانی/راه‌اندازیِ دوباره/ساخت/وضعیت/لاگ
]

from django.urls import path

from . import views

urlpatterns = [
    path("knowledge/", views.KnowledgeListView.as_view(), name="growth-knowledge"),
    path("knowledge/restore-defaults/", views.RestoreDefaultsView.as_view(), name="growth-knowledge-restore"),
    path("knowledge/writer-status/", views.WriterStatusView.as_view(), name="growth-writer-status"),
    path("knowledge/<int:pk>/", views.KnowledgeDetailView.as_view(), name="growth-knowledge-item"),
    path("knowledge/<int:pk>/reset/", views.KnowledgeResetView.as_view(), name="growth-knowledge-reset"),
    path("outreach/campaigns/<int:pk>/ai-write/", views.BulkWriteView.as_view(), name="growth-ai-write-bulk"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/ai/", views.WriteView.as_view(), name="growth-ai-write"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/versions/", views.VersionListView.as_view(), name="growth-ai-versions"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/versions/compare/", views.VersionCompareView.as_view(), name="growth-ai-compare"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/versions/<int:vid>/approve/", views.VersionApproveView.as_view(), name="growth-ai-approve"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/versions/<int:vid>/reject/", views.VersionRejectView.as_view(), name="growth-ai-reject"),
]

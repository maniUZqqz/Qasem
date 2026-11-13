"""Mounted at /api/v1/ (config/urls.py)."""
from django.urls import path

from . import views

urlpatterns = [
    path("stores/<int:store_id>/igtrends/", views.OverviewView.as_view(), name="ig-overview"),
    path("stores/<int:store_id>/igtrends/scan/", views.ScanView.as_view(), name="ig-scan"),
    path("stores/<int:store_id>/igtrends/seeds/", views.SeedsView.as_view(), name="ig-seeds"),
    path("stores/<int:store_id>/igtrends/seeds/reset/", views.SeedsResetView.as_view(), name="ig-seeds-reset"),
    path("stores/<int:store_id>/igtrends/seeds/<int:pk>/", views.SeedView.as_view(), name="ig-seed"),
    path("stores/<int:store_id>/igtrends/config/", views.ConfigView.as_view(), name="ig-config"),
    path("stores/<int:store_id>/igtrends/import/", views.ImportView.as_view(), name="ig-import"),
    path("stores/<int:store_id>/igtrends/clusters/<int:pk>/brief/", views.ClusterBriefView.as_view(), name="ig-brief"),
    path("stores/<int:store_id>/igtrends/clusters/<int:pk>/dismiss/", views.ClusterDismissView.as_view(), name="ig-dismiss"),
    path("igtrends/ingest/", views.ingest_view, name="ig-ingest"),
    path("igtrends/settings/", views.settings_view, name="ig-settings"),
]

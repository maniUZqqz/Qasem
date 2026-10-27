from django.urls import path

from . import views

P = "stores/<int:store_id>/photo-editor/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="photoedit-overview"),
    path(P + "sources/", views.SourcesView.as_view(), name="photoedit-sources"),
    path(P + "assets/", views.AssetListView.as_view(), name="photoedit-assets"),
    path(P + "assets/<int:pk>/", views.AssetView.as_view(), name="photoedit-asset"),
    path(P + "assets/<int:pk>/analyze/", views.AssetAnalyzeView.as_view(), name="photoedit-asset-analyze"),
    path(P + "plan/", views.PlanView.as_view(), name="photoedit-plan"),
    path(P + "edits/", views.EditListView.as_view(), name="photoedit-edits"),
    path(P + "edits/<int:pk>/", views.EditView.as_view(), name="photoedit-edit"),
    path(P + "edits/<int:pk>/<str:action>/", views.EditView.as_view(), name="photoedit-edit-action"),
    path(P + "batches/<str:batch>/zip/", views.BatchZipView.as_view(), name="photoedit-batch-zip"),
]

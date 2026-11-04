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
    path(P + "preview/", views.PreviewView.as_view(), name="photoedit-preview"),
    path(P + "edits/", views.EditListView.as_view(), name="photoedit-edits"),
    path(P + "edits/<int:pk>/", views.EditView.as_view(), name="photoedit-edit"),
    path(P + "edits/<int:pk>/<str:action>/", views.EditView.as_view(), name="photoedit-edit-action"),
    path(P + "batches/<str:batch>/zip/", views.BatchZipView.as_view(), name="photoedit-batch-zip"),
    path(P + "projects/", views.ProjectListView.as_view(), name="photoedit-projects"),
    path(P + "projects/<int:pk>/", views.ProjectView.as_view(), name="photoedit-project"),
    path(P + "projects/<int:pk>/masks/<str:mid>/", views.MaskView.as_view(), name="photoedit-mask"),
    path(P + "exact/", views.ExactView.as_view(), name="photoedit-exact"),
    path(P + "exact/<uuid:uid>/", views.ExactStatusView.as_view(), name="photoedit-exact-status"),
    path(P + "subject/", views.SubjectView.as_view(), name="photoedit-subject"),
    path(P + "subject/<uuid:uid>/", views.SubjectStatusView.as_view(), name="photoedit-subject-status"),
    path(P + "presets/", views.PresetListView.as_view(), name="photoedit-presets"),
    path(P + "presets/<int:pk>/", views.PresetView.as_view(), name="photoedit-preset"),
    path(P + "presets/<int:pk>/apply/", views.PresetApplyView.as_view(), name="photoedit-preset-apply"),
    path(P + "fonts/", views.FontsView.as_view(), name="photoedit-fonts"),
    path(P + "genfill/", views.GenFillView.as_view(), name="photoedit-genfill"),
    path(P + "genfill/translate/", views.GenFillTranslateView.as_view(), name="photoedit-genfill-translate"),
    path(P + "genfill/<uuid:uid>/", views.GenFillStatusView.as_view(), name="photoedit-genfill-status"),
    path(P + "genfill/<uuid:uid>/prompt/", views.GenFillPromptView.as_view(), name="photoedit-genfill-prompt"),
    path(P + "projects/<int:pk>/liquify/", views.LiquifyView.as_view(), name="photoedit-liquify"),
]

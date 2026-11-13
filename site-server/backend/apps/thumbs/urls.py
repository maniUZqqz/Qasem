from django.urls import path

from . import views

P = "stores/<int:store_id>/thumbnails/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="thumbs-overview"),
    path(P + "styles/<str:key>/sample.jpg", views.StyleSampleView.as_view(), name="thumbs-style-sample"),
    path(P + "moodboard/", views.MoodboardView.as_view(), name="thumbs-moodboard"),
    path(P + "ideas/", views.IdeasView.as_view(), name="thumbs-ideas"),
    path(P + "preview/", views.PreviewView.as_view(), name="thumbs-preview"),
    path(P + "render/", views.RenderView.as_view(), name="thumbs-render"),
    path(P + "items/", views.ItemListView.as_view(), name="thumbs-items"),
    path(P + "items/<int:pk>/", views.ItemView.as_view(), name="thumbs-item"),
    path(P + "items/<int:pk>/download/", views.ItemDownloadView.as_view(), name="thumbs-item-download"),
    path(P + "items/<int:pk>/editor/", views.ItemEditorView.as_view(), name="thumbs-item-editor"),
    path(P + "items/<int:pk>/layers/", views.ItemLayersView.as_view(), name="thumbs-item-layers"),
    path(P + "batches/<str:batch>/zip/", views.BatchZipView.as_view(), name="thumbs-batch-zip"),
    path(P + "backgrounds/", views.BackgroundsView.as_view(), name="thumbs-backgrounds"),
    path(P + "backgrounds/<uuid:uid>/", views.BackgroundStatusView.as_view(), name="thumbs-background"),
    path(P + "cutout/", views.CutoutView.as_view(), name="thumbs-cutout"),
    path(P + "cutout/<uuid:uid>/", views.CutoutStatusView.as_view(), name="thumbs-cutout-status"),
    path(P + "library/", views.LibraryView.as_view(), name="thumbs-library"),
    path(P + "library/upload/", views.LibraryUploadView.as_view(), name="thumbs-library-upload"),
    path(P + "library/import/", views.LibraryImportView.as_view(), name="thumbs-library-import"),
]

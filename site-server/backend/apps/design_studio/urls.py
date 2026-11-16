from django.urls import path

from . import views

P = "stores/<int:store_id>/design/"

urlpatterns = [
    path("design/fonts/<str:key>/<int:weight>.ttf", views.FontFileView.as_view(), name="design-font"),
    path(P, views.OverviewView.as_view(), name="design-overview"),
    path(P + "sample/", views.SampleView.as_view(), name="design-sample"),
    path(P + "ui/catalog/", views.UiCatalogView.as_view(), name="design-ui-catalog"),
    path(P + "docs/", views.DocListView.as_view(), name="design-docs"),
    path(P + "docs/<int:pk>/", views.DocView.as_view(), name="design-doc"),
    path(P + "docs/<int:pk>/ops/", views.OpsView.as_view(), name="design-ops"),
    path(P + "docs/<int:pk>/scene/", views.SceneView.as_view(), name="design-scene"),
    path(P + "docs/<int:pk>/preview/<str:page>.png", views.PreviewView.as_view(), name="design-preview"),
    path(P + "docs/<int:pk>/exports/", views.ExportListView.as_view(), name="design-exports"),
    path(P + "docs/<int:pk>/designer/", views.DesignerView.as_view(), name="design-designer"),
    path(P + "docs/<int:pk>/video/", views.VideoView.as_view(), name="design-video"),
    path(P + "docs/<int:pk>/site/", views.SiteView.as_view(), name="design-site"),
    path(P + "docs/<int:pk>/ai/", views.AiView.as_view(), name="design-ai"),
    path(P + "docs/<int:pk>/comments/", views.CommentListView.as_view(), name="design-comments"),
    path(P + "comments/<int:cid>/", views.CommentView.as_view(), name="design-comment"),
    path(P + "exports/<int:pk>/", views.ExportView.as_view(), name="design-export"),
    path(P + "exports/<int:pk>/download/", views.ExportDownloadView.as_view(), name="design-export-download"),
]

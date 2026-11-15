from django.urls import path

from . import views

P = "stores/<int:store_id>/mascot/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="mascot-overview"),
    path(P + "<int:pk>/", views.MascotView.as_view(), name="mascot-item"),
    path(P + "<int:pk>/lock/", views.LockView.as_view(), name="mascot-lock"),
    path(P + "<int:pk>/unlock/", views.UnlockView.as_view(), name="mascot-unlock"),
    path(P + "<int:pk>/preview/", views.PreviewView.as_view(), name="mascot-preview"),
    path(P + "<int:pk>/render/", views.RenderView.as_view(), name="mascot-render"),
    path(P + "<int:pk>/sticker/", views.StickerView.as_view(), name="mascot-sticker"),
    path(P + "<int:pk>/sheet/", views.SheetView.as_view(), name="mascot-sheet"),
    path(P + "<int:pk>/check/", views.CheckView.as_view(), name="mascot-check"),
    path(P + "<int:pk>/shots/", views.ShotListView.as_view(), name="mascot-shots"),
    path(P + "<int:pk>/shots/<int:rid>/", views.ShotView.as_view(), name="mascot-shot"),
    path(P + "<int:pk>/shots/<int:rid>/download/", views.ShotDownloadView.as_view(), name="mascot-shot-download"),
]

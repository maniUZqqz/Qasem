from django.urls import path

from . import views

urlpatterns = [
    path("stores/<int:store_id>/multiangle/", views.OverviewView.as_view(), name="multiangle-overview"),
    path("stores/<int:store_id>/multiangle/status/", views.StatusView.as_view(), name="multiangle-status"),
    path("stores/<int:store_id>/multiangle/prepare/", views.PrepareView.as_view(), name="multiangle-prepare"),
    path("stores/<int:store_id>/multiangle/runs/", views.RunListView.as_view(), name="multiangle-runs"),
    path("stores/<int:store_id>/multiangle/runs/<int:pk>/", views.RunView.as_view(), name="multiangle-run"),
    path("stores/<int:store_id>/multiangle/runs/<int:pk>/<str:action>/", views.RunActionView.as_view(), name="multiangle-run-action"),
    path("stores/<int:store_id>/multiangle/real/", views.RealCamerasView.as_view(), name="multiangle-real"),
    path("stores/<int:store_id>/multiangle/selftest/", views.SelfTestView.as_view(), name="multiangle-selftest"),
]

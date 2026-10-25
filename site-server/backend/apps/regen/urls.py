from django.urls import path

from . import views

urlpatterns = [
    path("stores/<int:store_id>/regen/", views.OverviewView.as_view(), name="regen-overview"),
    path("stores/<int:store_id>/regen/sessions/", views.SessionListView.as_view(), name="regen-sessions"),
    path("stores/<int:store_id>/regen/sessions/<int:pk>/", views.SessionView.as_view(), name="regen-session"),
    path("stores/<int:store_id>/regen/sessions/<int:pk>/frame/", views.FrameView.as_view(), name="regen-frame"),
    path("stores/<int:store_id>/regen/sessions/<int:pk>/estimate/", views.EstimateView.as_view(),
         name="regen-estimate"),
    path("stores/<int:store_id>/regen/sessions/<int:pk>/versions/", views.VersionCreateView.as_view(),
         name="regen-versions"),
    path("stores/<int:store_id>/regen/versions/<int:pk>/", views.VersionView.as_view(), name="regen-version"),
    path("stores/<int:store_id>/regen/versions/<int:pk>/<str:action>/", views.VersionView.as_view(),
         name="regen-version-action"),
]

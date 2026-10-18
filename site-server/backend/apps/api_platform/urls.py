"""Two URL sets: the public API, and the panel screens that manage its keys."""
from django.urls import path

from .views import (
    CaptionAPI,
    PosterAPI,
    PublicJobView,
    SalesAgentAPI,
    ShowcaseAPI,
    VideoAPI,
)
from .views_keys import APIKeyDetailView, APIKeyListView, APIUsageView

urlpatterns = [
    # ---- what a shop's own system calls (§28) ----------------------------
    path("public/sales-agent/", SalesAgentAPI.as_view(), name="public-sales-agent"),
    path("public/caption/", CaptionAPI.as_view(), name="public-caption"),
    path("public/video/", VideoAPI.as_view(), name="public-video"),
    path("public/poster/", PosterAPI.as_view(), name="public-poster"),
    path("public/showcase/", ShowcaseAPI.as_view(), name="public-showcase"),
    # `str`, not `int`: a sandbox job id is prefixed so it cannot be mistaken
    # for a real one, and an int converter would 404 on it confusingly.
    path("public/jobs/<str:pk>/", PublicJobView.as_view(), name="public-job"),

    # ---- what the panel uses to manage keys ------------------------------
    path(
        "stores/<int:store_id>/api-keys/",
        APIKeyListView.as_view(), name="api-key-list",
    ),
    path(
        "stores/<int:store_id>/api-keys/<int:pk>/",
        APIKeyDetailView.as_view(), name="api-key-detail",
    ),
    path(
        "stores/<int:store_id>/api-usage/",
        APIUsageView.as_view(), name="api-usage",
    ),
]

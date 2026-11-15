"""Mounted at /api/v1/ (config/urls.py)."""
from django.urls import path

from . import views

P = "stores/<int:store_id>/ideas/"

urlpatterns = [
    path(P, views.IdeasView.as_view(), name="ideabank-list"),
    path(P + "random/", views.RandomView.as_view(), name="ideabank-random"),
    path(P + "generate/", views.GenerateView.as_view(), name="ideabank-generate"),
    path(P + "from-trend/", views.FromTrendView.as_view(), name="ideabank-from-trend"),
    path(P + "<str:key>/", views.IdeaView.as_view(), name="ideabank-idea"),
    path(P + "<str:key>/duplicate/", views.DuplicateView.as_view(), name="ideabank-duplicate"),
    path(P + "<str:key>/mark/", views.MarkView.as_view(), name="ideabank-mark"),
    path(P + "<str:key>/start/", views.StartView.as_view(), name="ideabank-start"),
]

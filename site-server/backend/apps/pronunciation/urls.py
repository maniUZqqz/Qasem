from django.urls import path

from . import views

P = "stores/<int:store_id>/pronunciation/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="pron-overview"),
    path(P + "settings/", views.SettingsView.as_view(), name="pron-settings"),
    path(P + "preview/", views.PreviewView.as_view(), name="pron-preview"),
    path(P + "convert/", views.ConvertView.as_view(), name="pron-convert"),
    path(P + "listen/", views.ListenView.as_view(), name="pron-listen"),
    path(P + "listen/<str:token>/", views.ListenResultView.as_view(), name="pron-listen-result"),
    path(P + "audio/<str:name>", views.AudioFileView.as_view(), name="pron-audio"),
    path(P + "shared/", views.SharedView.as_view(), name="pron-shared"),
    path(P + "lexicon/", views.LexiconView.as_view(), name="pron-lexicon"),
    path(P + "lexicon/<int:pk>/", views.LexiconItemView.as_view(), name="pron-lexicon-item"),
    path(P + "problems/", views.ProblemsView.as_view(), name="pron-problems"),
    path(P + "problems/<int:pk>/", views.ProblemItemView.as_view(), name="pron-problem"),
    path(P + "eval/", views.EvalListView.as_view(), name="pron-eval"),
    path(P + "eval/<int:pk>/", views.EvalItemView.as_view(), name="pron-eval-item"),
]

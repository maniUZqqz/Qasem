from django.urls import path

from . import views

P = "stores/<int:store_id>/shoot/"
S = P + "sessions/<int:pk>/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="shoot-overview"),
    path(P + "sessions/", views.SessionListView.as_view(), name="shoot-sessions"),
    path(S, views.SessionView.as_view(), name="shoot-session"),
    path(S + "upload/", views.UploadView.as_view(), name="shoot-upload"),
    path(S + "takes/<int:tid>/", views.TakeView.as_view(), name="shoot-take"),
    path(S + "outputs/", views.OutputListView.as_view(), name="shoot-outputs"),
    path(S + "outputs/<int:oid>/", views.OutputView.as_view(), name="shoot-output"),
    path(S + "outputs/<int:oid>/<str:action>/", views.OutputView.as_view(), name="shoot-output-action"),
    path(S + "<str:action>/", views.SessionActionView.as_view(), name="shoot-session-action"),
]

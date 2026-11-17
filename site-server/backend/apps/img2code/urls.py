from django.urls import path

from . import views

P = "stores/<int:store_id>/image-to-code/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="img2code-overview"),
    path(P + "<int:pk>/", views.ItemView.as_view(), name="img2code-item"),
    path(P + "<int:pk>/cancel/", views.CancelView.as_view(), name="img2code-cancel"),
    path(P + "<int:pk>/again/", views.AgainView.as_view(), name="img2code-again"),
    path(P + "<int:pk>/code/", views.CodeView.as_view(), name="img2code-code"),
    path(P + "<int:pk>/files/<str:name>", views.FileView.as_view(), name="img2code-file"),
    path(P + "<int:pk>/site-targets/", views.SiteTargetsView.as_view(), name="img2code-site-targets"),
    path(P + "<int:pk>/site-draft/", views.SiteDraftView.as_view(), name="img2code-site-draft"),
    path(P + "<int:pk>/ui-design/", views.UiDesignView.as_view(), name="img2code-ui-design"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("stores/<int:store_id>/marketing-plan/", views.PlanView.as_view(), name="mktplan-plan"),
    path("stores/<int:store_id>/marketing-plan/items/<int:item_id>/", views.ItemView.as_view(), name="mktplan-item"),
    path("stores/<int:store_id>/test-guide/", views.GuideView.as_view(), name="mktplan-guide"),
    path("stores/<int:store_id>/bug-reports/", views.BugReportsView.as_view(), name="mktplan-bugs-store"),
    path("bug-reports/", views.BugReportsView.as_view(), name="mktplan-bugs"),
    path("bug-reports/sections/", views.BugSectionsView.as_view(), name="mktplan-bug-sections"),
    path("bug-reports/<int:pk>/", views.BugReportDetailView.as_view(), name="mktplan-bug"),
]

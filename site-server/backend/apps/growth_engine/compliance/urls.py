from django.urls import path

from . import views

urlpatterns = [
    path("settings/", views.SettingsView.as_view(), name="growth-settings"),
    path("settings/emergency-stop/", views.EmergencyStopView.as_view(), name="growth-emergency-stop"),
    path("settings/audit/", views.AuditView.as_view(), name="growth-audit"),
    path("compliance/suppression/", views.SuppressionListView.as_view(), name="growth-suppression"),
    path("compliance/suppression/<int:pk>/", views.SuppressionDetailView.as_view(), name="growth-suppression-entry"),
    path("leads/<int:pk>/do-not-contact/", views.LeadDoNotContactView.as_view(), name="growth-lead-dnc"),
]

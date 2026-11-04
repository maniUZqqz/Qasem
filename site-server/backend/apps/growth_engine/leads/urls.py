from django.urls import path

from . import views

urlpatterns = [
    path("leads/", views.LeadListView.as_view(), name="growth-leads"),
    path("leads/bulk/", views.LeadBulkView.as_view(), name="growth-leads-bulk"),
    path("leads/export/", views.LeadExportView.as_view(), name="growth-leads-export"),
    path("leads/<int:pk>/", views.LeadDetailView.as_view(), name="growth-lead"),
    path("leads/<int:pk>/activity/", views.LeadActivityView.as_view(), name="growth-lead-activity"),
    path("leads/<int:pk>/notes/", views.LeadNotesView.as_view(), name="growth-lead-notes"),
    path("leads/<int:pk>/notes/<int:note_id>/", views.LeadNoteDetailView.as_view(), name="growth-lead-note"),
    path("leads/<int:pk>/contacts/", views.LeadContactsView.as_view(), name="growth-lead-contacts"),
    path("leads/<int:pk>/contacts/<int:contact_id>/", views.LeadContactDetailView.as_view(), name="growth-lead-contact"),
    path("tags/", views.TagListView.as_view(), name="growth-tags"),
]

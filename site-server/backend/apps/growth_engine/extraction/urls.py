from django.urls import path

from . import views

urlpatterns = [
    path("extraction/jobs/", views.JobListCreateView.as_view(), name="growth-extraction-jobs"),
    path("extraction/jobs/<int:pk>/", views.JobDetailView.as_view(), name="growth-extraction-job"),
    path("extraction/jobs/<int:pk>/cancel/", views.JobCancelView.as_view(), name="growth-extraction-job-cancel"),
    path("extraction/jobs/<int:pk>/resume/", views.JobResumeView.as_view(), name="growth-extraction-job-resume"),
    path("leads/<int:lead_id>/extraction/", views.LeadExtractionView.as_view(), name="growth-lead-extraction"),
]

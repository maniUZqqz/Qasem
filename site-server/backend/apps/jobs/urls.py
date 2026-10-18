from django.urls import path

from .views import JobCancelView, JobDetailView, JobListView
from .stream import JobStreamView
from .views_approval import JobApproveView, JobModeView, JobRegenerateView, JobRejectView

urlpatterns = [
    path("jobs/", JobListView.as_view(), name="job-list"),
    path("jobs/<int:pk>/", JobDetailView.as_view(), name="job-detail"),
    path("jobs/<int:pk>/cancel/", JobCancelView.as_view(), name="job-cancel"),
    path("jobs/<int:pk>/approve/", JobApproveView.as_view(), name="job-approve"),
    path("jobs/<int:pk>/reject/", JobRejectView.as_view(), name="job-reject"),
    path("jobs/<int:pk>/regenerate/", JobRegenerateView.as_view(), name="job-regenerate"),
    path("jobs/<int:pk>/mode/", JobModeView.as_view(), name="job-mode"),
    path("jobs/<int:pk>/stream/", JobStreamView.as_view(), name="job-stream"),
]

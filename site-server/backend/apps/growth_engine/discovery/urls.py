from django.urls import path

from . import views

urlpatterns = [
    path("manual/check/", views.ManualCheckView.as_view(), name="growth-manual-check"),
    path("manual/", views.ManualSubmitView.as_view(), name="growth-manual"),
    path("csv/upload/", views.CsvUploadView.as_view(), name="growth-csv-upload"),
    path("csv/check/", views.CsvCheckView.as_view(), name="growth-csv-check"),
    path("csv/import/", views.CsvImportView.as_view(), name="growth-csv-import"),
    path("providers/", views.ProviderListView.as_view(), name="growth-providers"),
    path("providers/<str:key>/", views.ProviderDetailView.as_view(), name="growth-provider"),
    path("search/check/", views.SearchCheckView.as_view(), name="growth-search-check"),
    path("search/", views.SearchStartView.as_view(), name="growth-search"),
    path("jobs/", views.JobListView.as_view(), name="growth-jobs"),
    path("jobs/<int:pk>/", views.JobDetailView.as_view(), name="growth-job"),
    path("jobs/<int:pk>/rows/", views.JobRowsView.as_view(), name="growth-job-rows"),
    path("jobs/<int:pk>/errors.csv", views.JobErrorsCsvView.as_view(), name="growth-job-errors"),
    path("jobs/<int:pk>/cancel/", views.JobCancelView.as_view(), name="growth-job-cancel"),
    path("jobs/<int:pk>/resume/", views.JobResumeView.as_view(), name="growth-job-resume"),
    path("jobs/<int:pk>/resolve/", views.JobResolveView.as_view(), name="growth-job-resolve"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("finder/meta/", views.MetaView.as_view(), name="finder-meta"),
    path("finder/node/", views.NodeStatusView.as_view(), name="finder-node"),
    path("finder/neshan-key/", views.NeshanKeyView.as_view(), name="finder-neshan-key"),
    path("finder/engines/probe/", views.EnginesProbeView.as_view(), name="finder-engines-probe"),
    path("finder/missions/", views.MissionListView.as_view(), name="finder-missions"),
    path("finder/missions/from-preset/", views.MissionFromPresetView.as_view(), name="finder-mission-preset"),
    path("finder/missions/<int:pk>/", views.MissionDetailView.as_view(), name="finder-mission"),
    path("finder/missions/<int:pk>/run/", views.MissionRunView.as_view(), name="finder-mission-run"),
    path("finder/missions/<int:pk>/drafts/", views.DraftGenerateView.as_view(), name="finder-mission-drafts"),
    path("finder/runs/", views.RunListView.as_view(), name="finder-runs"),
    path("finder/runs/<int:pk>/", views.RunDetailView.as_view(), name="finder-run"),
    path("finder/runs/<int:pk>/logs/", views.RunLogsView.as_view(), name="finder-run-logs"),
    path("finder/runs/<int:pk>/tasks/", views.RunTasksView.as_view(), name="finder-run-tasks"),
    path("finder/runs/<int:pk>/<str:action>/", views.RunActionView.as_view(), name="finder-run-action"),
    path("finder/results/", views.ResultListView.as_view(), name="finder-results"),
    path("finder/results/map/", views.ResultMapView.as_view(), name="finder-results-map"),
    path("finder/results/summary/", views.ResultSummaryView.as_view(), name="finder-results-summary"),
    path("finder/results/export/", views.ResultExportView.as_view(), name="finder-results-export"),
    path("finder/pipeline/", views.PipelineView.as_view(), name="finder-pipeline"),
    path("finder/leads/<int:pk>/stage/", views.LeadStageView.as_view(), name="finder-lead-stage"),
    path("finder/leads/<int:pk>/reminders/", views.LeadReminderCreateView.as_view(), name="finder-lead-reminders"),
    path("finder/reminders/", views.ReminderListView.as_view(), name="finder-reminders"),
    path("finder/reminders/<int:pk>/", views.ReminderDetailView.as_view(), name="finder-reminder"),
    path("finder/drafts/", views.DraftListView.as_view(), name="finder-drafts"),
    path("finder/drafts/bulk/", views.DraftBulkView.as_view(), name="finder-drafts-bulk"),
    path("finder/drafts/<int:pk>/", views.DraftDetailView.as_view(), name="finder-draft"),
    path("finder/drafts/<int:pk>/<str:action>/", views.DraftActionView.as_view(), name="finder-draft-action"),
]

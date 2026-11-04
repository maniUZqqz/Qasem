from django.urls import path

from . import views

urlpatterns = [
    path("outreach/placeholders/", views.PlaceholdersView.as_view(), name="growth-outreach-placeholders"),
    path("outreach/templates/", views.TemplateListView.as_view(), name="growth-outreach-templates"),
    path("outreach/templates/preview/", views.TemplatePreviewView.as_view(), name="growth-outreach-template-preview"),
    path("outreach/templates/<int:pk>/", views.TemplateDetailView.as_view(), name="growth-outreach-template"),
    path("outreach/campaigns/", views.CampaignListView.as_view(), name="growth-outreach-campaigns"),
    path("outreach/campaigns/<int:pk>/", views.CampaignDetailView.as_view(), name="growth-outreach-campaign"),
    path("outreach/campaigns/<int:pk>/add-leads/", views.AddLeadsView.as_view(), name="growth-outreach-add-leads"),
    path("outreach/campaigns/<int:pk>/remove-items/", views.RemoveItemsView.as_view(), name="growth-outreach-remove-items"),
    path("outreach/campaigns/<int:pk>/prepare/", views.PrepareView.as_view(), name="growth-outreach-prepare"),
    path("outreach/campaigns/<int:pk>/approve/", views.ApproveView.as_view(), name="growth-outreach-approve"),
    path("outreach/campaigns/<int:pk>/revoke/", views.RevokeView.as_view(), name="growth-outreach-revoke"),
    path("outreach/campaigns/<int:pk>/start/", views.StartView.as_view(), name="growth-outreach-start"),
    path("outreach/campaigns/<int:pk>/pause/", views.PauseView.as_view(), name="growth-outreach-pause"),
    path("outreach/campaigns/<int:pk>/cancel/", views.CancelView.as_view(), name="growth-outreach-cancel"),
    path("outreach/campaigns/<int:pk>/status/", views.StatusView.as_view(), name="growth-outreach-status"),
    path("outreach/campaigns/<int:pk>/items/", views.ItemListView.as_view(), name="growth-outreach-items"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/", views.ItemDetailView.as_view(), name="growth-outreach-item"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/rerender/", views.ItemRerenderView.as_view(), name="growth-outreach-item-rerender"),
    path("outreach/campaigns/<int:pk>/items/<int:item_id>/outcome/", views.ItemOutcomeView.as_view(), name="growth-outreach-item-outcome"),
    path("outreach/jobs/<int:pk>/", views.JobDetailView.as_view(), name="growth-outreach-job"),
    path("outreach/jobs/<int:pk>/cancel/", views.JobCancelView.as_view(), name="growth-outreach-job-cancel"),
    path("outreach/jobs/<int:pk>/resume/", views.JobResumeView.as_view(), name="growth-outreach-job-resume"),
]

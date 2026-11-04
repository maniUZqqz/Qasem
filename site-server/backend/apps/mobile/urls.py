"""/api/v1/mobile/ — see docs/api-contract.md in the NM-Mobile repository."""
from django.urls import path

from . import views as v
from . import views_admin as a

urlpatterns = [
    # pairing + device
    path("pair/", v.PairView.as_view()),
    path("me/", v.MeView.as_view()),
    path("heartbeat/", v.HeartbeatView.as_view()),
    path("unpair/", v.UnpairView.as_view()),
    # monitoring
    path("monitor/summary/", v.MonitorSummaryView.as_view()),
    path("monitor/actions/", v.MonitorActionsView.as_view()),
    # SMS
    path("sms/claim/", v.SmsClaimView.as_view()),
    path("sms/incoming/", v.SmsIncomingView.as_view()),
    path("sms/queue/", v.SmsQueueView.as_view()),
    path("sms/optouts/", v.OptOutsFeedView.as_view()),
    path("sms/<uuid:uid>/report/", v.SmsReportView.as_view()),
    path("sms/<uuid:uid>/cancel/", a.SmsCancelView.as_view()),
    # calls
    path("calls/log/", v.CallsLogView.as_view()),
    path("calls/live/", v.CallsLiveView.as_view()),
    path("calls/consent/", v.ConsentView.as_view()),
    path("calls/consent/revoke/", v.ConsentRevokeView.as_view()),
    path("calls/", v.CallsListView.as_view()),
    path("calls/<uuid:uid>/", v.CallDetailView.as_view()),
    path("calls/<uuid:uid>/recording/", v.CallRecordingView.as_view()),
    path("calls/<uuid:uid>/audio/", v.CallAudioView.as_view()),
    path("calls/<uuid:uid>/reprocess/", v.CallReprocessView.as_view()),
    # in-call helpers
    path("products/search/", v.ProductSearchView.as_view()),
    path("callerid/", v.CallerIdView.as_view()),
    path("assistant/ask/", v.AssistantAskView.as_view()),
    path("contacts/sync/", v.ContactsSyncView.as_view()),
    # messenger lookups (caller identification)
    path("lookups/config/", v.LookupConfigView.as_view()),
    path("lookups/authorize/", v.LookupAuthorizeView.as_view()),
    path("lookups/server/", v.LookupServerView.as_view()),
    path("lookups/latest/", v.LookupLatestView.as_view()),
    path("lookups/<uuid:uid>/avatar/", v.LookupAvatarView.as_view()),
    path("lookups/", v.LookupListView.as_view()),
    # panel (staff login)
    path("admin/overview/", a.OverviewView.as_view()),
    path("admin/devices/", a.DevicesView.as_view()),
    path("admin/devices/<uuid:uid>/", a.DeviceDetailView.as_view()),
    path("admin/devices/<uuid:uid>/revoke/", a.DeviceRevokeView.as_view()),
    path("admin/optouts/", a.OptOutsView.as_view()),
    path("admin/optouts/<int:pk>/", a.OptOutDetailView.as_view()),
    path("admin/approvals/", a.ApprovalsView.as_view()),
    path("admin/approvals/<int:pk>/revoke/", a.ApprovalRevokeView.as_view()),
    path("admin/consents/", a.ConsentsListView.as_view()),
    path("admin/settings/", a.SettingsView.as_view()),
    path("admin/products/", a.AdminProductsView.as_view()),
    path("admin/products/<int:pk>/pricing/", a.ProductPricingView.as_view()),
    path("admin/lookups/", a.AdminLookupsView.as_view()),
    path("admin/lookups/telegram/", a.TelegramAdminView.as_view()),
    path("admin/actions-log/", a.ActionLogView.as_view()),
]

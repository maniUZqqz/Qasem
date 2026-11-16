from django.urls import path

from . import views_channels as ch
from . import views_conversations as cv
from . import views_crm as crm
from . import views_dev as dev
from . import views_team as tm
from . import views_widget as wd

S = "stores/<int:store_id>/inbox/"

urlpatterns = [
    # ---- inbound doors (no login: the platform / the visitor is the caller) ---
    path("inbox/hook/<str:slug>/<str:secret>/", ch.HookView.as_view(), name="inbox-hook"),
    path("widget/<str:key>.js", wd.ScriptView.as_view(), name="widget-script"),
    path("widget/<str:key>/config/", wd.ConfigView.as_view(), name="widget-config"),
    path("widget/<str:key>/session/", wd.SessionView.as_view(), name="widget-session"),
    path("widget/<str:key>/send/", wd.SendView.as_view(), name="widget-send"),
    path("widget/<str:key>/messages/", wd.MessagesView.as_view(), name="widget-messages"),

    # ---- the public API (API key) ----------------------------------------
    path("inbox-api/conversations/", dev.ApiConversations.as_view(), name="inbox-api-conversations"),
    path("inbox-api/conversations/<int:pk>/messages/", dev.ApiMessages.as_view(), name="inbox-api-messages"),
    path("inbox-api/conversations/<int:pk>/reply/", dev.ApiReply.as_view(), name="inbox-api-reply"),
    path("inbox-api/messages/", dev.ApiInbound.as_view(), name="inbox-api-inbound"),
    path("inbox-api/contacts/", dev.ApiContacts.as_view(), name="inbox-api-contacts"),
    path("inbox-api/contacts/upsert/", dev.ApiContactUpsert.as_view(), name="inbox-api-contact-upsert"),
    path("inbox-api/segments/", dev.ApiSegments.as_view(), name="inbox-api-segments"),
    path("inbox-api/broadcasts/", dev.ApiBroadcastDraft.as_view(), name="inbox-api-broadcast"),

    # ---- the three-pane inbox --------------------------------------------
    path(S + "v2/", cv.ListView.as_view(), name="inbox2-list"),
    path(S + "v2/<int:pk>/", cv.ThreadView.as_view(), name="inbox2-thread"),
    path(S + "v2/<int:pk>/reply/", cv.ReplyView.as_view(), name="inbox2-reply"),
    path(S + "v2/<int:pk>/note/", cv.NoteView.as_view(), name="inbox2-note"),
    path(S + "v2/<int:pk>/assign/", cv.AssignView.as_view(), name="inbox2-assign"),
    path(S + "v2/<int:pk>/state/", cv.StateView.as_view(), name="inbox2-state"),
    path(S + "v2/<int:pk>/tags/", cv.TagsView.as_view(), name="inbox2-tags"),
    path(S + "v2/<int:pk>/followup/", cv.FollowUpCreateView.as_view(), name="inbox2-followup"),
    path(S + "v2/<int:pk>/contact/", crm.ConversationContactView.as_view(), name="inbox2-contact"),
    path(S + "canned/", cv.CannedListView.as_view(), name="inbox-canned"),
    path(S + "canned/<int:pk>/", cv.CannedDetailView.as_view(), name="inbox-canned-detail"),
    path(S + "mentions/", cv.MentionsView.as_view(), name="inbox-mentions"),

    # ---- team ---------------------------------------------------------------
    path(S + "settings/", tm.SettingsView.as_view(), name="inbox-settings"),
    path(S + "presence/", tm.PresenceView.as_view(), name="inbox-presence"),
    path(S + "team/", tm.TeamView.as_view(), name="inbox-team"),
    path(S + "team/<str:username>/", tm.TeamMemberView.as_view(), name="inbox-team-member"),
    path(S + "stats/", tm.StatsView.as_view(), name="inbox-stats"),

    # ---- channels -----------------------------------------------------------
    path(S + "channels/", ch.ChannelsView.as_view(), name="inbox-channels"),
    path(S + "channels/sms/forwarding/", ch.SmsForwardingView.as_view(), name="inbox-sms-forwarding"),
    path(S + "channels/<str:kind>/", ch.ChannelDetailView.as_view(), name="inbox-channel"),
    path(S + "channels/<str:kind>/check/", ch.ChannelCheckView.as_view(), name="inbox-channel-check"),
    path(S + "channels/<str:kind>/webhook/", ch.ChannelWebhookView.as_view(), name="inbox-channel-webhook"),
    path(S + "channels/<str:kind>/poll/", ch.ChannelPollView.as_view(), name="inbox-channel-poll"),

    # ---- CRM ----------------------------------------------------------------
    path(S + "contacts/", crm.ContactListView.as_view(), name="inbox-contacts"),
    path(S + "contacts/<int:pk>/", crm.ContactDetailView.as_view(), name="inbox-contact"),
    path(S + "contacts/<int:pk>/merge/", crm.ContactMergeView.as_view(), name="inbox-contact-merge"),
    path(S + "customers/<int:customer_id>/unlink/", crm.CustomerUnlinkView.as_view(), name="inbox-customer-unlink"),
    path(S + "segments/", crm.SegmentListView.as_view(), name="inbox-segments"),
    path(S + "segments/preview/", crm.SegmentPreviewView.as_view(), name="inbox-segment-preview"),
    path(S + "segments/<int:pk>/", crm.SegmentDetailView.as_view(), name="inbox-segment"),
    path(S + "broadcasts/", crm.BroadcastListView.as_view(), name="inbox-broadcasts"),
    path(S + "broadcasts/<int:pk>/", crm.BroadcastDetailView.as_view(), name="inbox-broadcast"),
    path(S + "broadcasts/<int:pk>/preview/", crm.BroadcastPreviewView.as_view(), name="inbox-broadcast-preview"),
    path(S + "broadcasts/<int:pk>/<str:action>/", crm.BroadcastActionView.as_view(), name="inbox-broadcast-action"),
    path(S + "followups/", crm.FollowUpListView.as_view(), name="inbox-followups"),
    path(S + "followups/<int:pk>/", crm.FollowUpDetailView.as_view(), name="inbox-followup"),

    # ---- developers ----------------------------------------------------------
    path(S + "dev/webhooks/", dev.WebhookListView.as_view(), name="inbox-dev-webhooks"),
    path(S + "dev/webhooks/<int:pk>/", dev.WebhookDetailView.as_view(), name="inbox-dev-webhook"),
    path(S + "dev/webhooks/<int:pk>/test/", dev.WebhookTestView.as_view(), name="inbox-dev-webhook-test"),
    path(S + "dev/docs/", dev.ApiDocsView.as_view(), name="inbox-dev-docs"),
]

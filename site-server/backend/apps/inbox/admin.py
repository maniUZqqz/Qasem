from django.contrib import admin

from .models import (
    AgentProfile, Broadcast, CannedReply, ChannelConnection, Contact, FollowUp, InboxSettings, SatisfactionSurvey,
    Segment, WebhookEndpoint,
)


@admin.register(ChannelConnection)
class ChannelConnectionAdmin(admin.ModelAdmin):
    list_display = ("store", "kind", "enabled", "health_ok", "last_inbound_at", "inbound_count", "outbound_count")
    list_filter = ("kind", "enabled", "health_ok")
    #: the credential and the URL secret never show in the admin list or form
    exclude = ("token", "secret")
    readonly_fields = ("last_error", "last_error_at", "health_detail", "poll_cursor")


@admin.register(InboxSettings)
class InboxSettingsAdmin(admin.ModelAdmin):
    list_display = ("store", "assignment_mode", "sla_first_response_min", "bot_enabled", "survey_enabled")


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("store", "user", "status", "last_seen_at", "accepts_chats", "max_open")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("store", "name", "phone", "orders_count", "last_activity_at", "is_test")
    search_fields = ("name", "phone")
    list_filter = ("is_test",)


@admin.register(Segment, CannedReply, WebhookEndpoint, SatisfactionSurvey)
class PlainAdmin(admin.ModelAdmin):
    pass


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ("store", "name", "status", "is_test", "created_by", "approved_by", "created_at")
    list_filter = ("status", "is_test")


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ("store", "kind", "status", "due_at", "is_test")
    list_filter = ("kind", "status", "is_test")

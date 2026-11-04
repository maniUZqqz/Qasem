from django.contrib import admin

from . import models as m


@admin.register(m.MobileDevice)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "model", "last_seen_at", "revoked_at")
    readonly_fields = ("token_hash", "token_prefix", "install_id")
    exclude = ("token_hash",)


@admin.register(m.SmsMessage)
class SmsAdmin(admin.ModelAdmin):
    list_display = ("to_number", "kind", "state", "device", "created_at")
    list_filter = ("state", "kind")


@admin.register(m.SmsOptOut)
class OptOutAdmin(admin.ModelAdmin):
    list_display = ("number", "reason", "created_at")


@admin.register(m.MobileCall)
class CallAdmin(admin.ModelAdmin):
    list_display = ("number", "direction", "status", "started_at")
    exclude = ("transcript", "segments")


admin.site.register(m.MobileSettings)
admin.site.register(m.SmsCampaignApproval)
admin.site.register(m.MobileActionLog)
admin.site.register(m.ProductPricing)

from django.contrib import admin

from .models import ShootOutput, ShootSession, ShootTake


@admin.register(ShootSession)
class ShootSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "store", "product", "purpose", "state", "plan_source", "created_at")
    list_filter = ("purpose", "state", "plan_source")
    raw_id_fields = ("store", "product", "created_by")


@admin.register(ShootTake)
class ShootTakeAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "shot", "kind", "ok", "accepted", "score", "created_at")
    list_filter = ("kind", "ok", "accepted")
    raw_id_fields = ("session",)


@admin.register(ShootOutput)
class ShootOutputAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "kind", "aspect", "version", "state", "created_at")
    list_filter = ("kind", "state")
    raw_id_fields = ("session",)

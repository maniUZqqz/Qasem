from django.contrib import admin

from .models import Mascot, MascotRender


@admin.register(Mascot)
class MascotAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "store", "role", "version", "locked", "updated_at")
    list_filter = ("role", "locked")
    search_fields = ("name",)


@admin.register(MascotRender)
class MascotRenderAdmin(admin.ModelAdmin):
    list_display = ("id", "mascot", "kind", "version", "width", "height", "created_at")
    list_filter = ("kind",)

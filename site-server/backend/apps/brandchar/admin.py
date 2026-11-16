from django.contrib import admin

from .models import BrandCharacter, BrandPersona, CharacterRender, UsageEvent


@admin.register(BrandPersona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("store", "version", "locked", "active", "source", "updated_at")


@admin.register(BrandCharacter)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "store", "version", "locked", "is_primary", "updated_at")


@admin.register(CharacterRender)
class RenderAdmin(admin.ModelAdmin):
    list_display = ("character", "kind", "created_at")


@admin.register(UsageEvent)
class UsageAdmin(admin.ModelAdmin):
    list_display = ("store", "surface", "ref", "created_at")

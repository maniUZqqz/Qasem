"""Cloned voices in the Django admin: who agreed to what, and the state of each build. Read-mostly —
recordings are made and voices built from the panel («صدا و گوینده» › «کلونِ صدا»)."""
from django.contrib import admin

from .voice_clone_models import ClonedVoice, ClonedVoiceClip


class ClonedVoiceClipInline(admin.TabularInline):
    model = ClonedVoiceClip
    extra = 0
    can_delete = False
    fields = ("index", "text", "source", "seconds", "snr", "level", "ok", "message", "node")
    readonly_fields = fields


@admin.register(ClonedVoice)
class ClonedVoiceAdmin(admin.ModelAdmin):
    list_display = ("name", "person", "store", "status", "engine", "node_name", "revision", "built_at", "consent_at")
    list_filter = ("status", "engine")
    search_fields = ("name", "person", "store__name")
    readonly_fields = ("consent_text", "consent_at", "consent_by", "consent_ip", "node_name", "node_voice_id",
                       "build_job", "revision", "report", "built_at", "engine_license")
    inlines = [ClonedVoiceClipInline]


from .audio_library_models import AudioAsset  # noqa: E402


@admin.register(AudioAsset)
class AudioAssetAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "store", "status", "engine", "duration", "saved", "commercial", "created_at")
    list_filter = ("kind", "status", "engine", "saved")
    search_fields = ("title", "text", "store__name")
    readonly_fields = ("job_uid", "file_name", "size", "duration", "used_in", "params", "prompt")

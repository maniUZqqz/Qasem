from django.contrib import admin

from .models import Caption, GeneratedImage, VideoScene, VideoScript, VideoSegment


@admin.register(Caption)
class CaptionAdmin(admin.ModelAdmin):
    name_en = "Captions"
    description = (
        "کپشن‌های تولیدشده برای هر محصول، به تفکیک پلتفرم."
    )
    list_display = ["id", "product", "platform", "tone", "created_at"]
    list_filter = ["platform"]


@admin.register(GeneratedImage)
class GeneratedImageAdmin(admin.ModelAdmin):
    name_en = "Generated images"
    description = (
        "تصویرها و پوسترهایی که هوش مصنوعی ساخته."
    )
    list_display = ["id", "product", "kind", "workflow_version", "created_at"]
    list_filter = ["kind"]


class VideoSceneInline(admin.TabularInline):
    model = VideoScene
    extra = 0


class VideoSegmentInline(admin.TabularInline):
    model = VideoSegment
    extra = 0
    readonly_fields = ["status", "anchor_source", "video", "last_frame", "error"]


@admin.register(VideoScript)
class VideoScriptAdmin(admin.ModelAdmin):
    name_en = "Video scripts"
    description = (
        "نقشه‌ی ماشین‌خوان یک ویدیوی تبلیغاتی: پلان‌ها، متن، صدا. رندر ویدیو از روی "
        "همین انجام می‌شود."
    )
    list_display = ["id", "product", "status", "total_duration", "created_at"]
    list_filter = ["status"]
    inlines = [VideoSceneInline, VideoSegmentInline]

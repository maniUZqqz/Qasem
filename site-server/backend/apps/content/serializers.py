from rest_framework import serializers

from .models import Caption, GeneratedImage, VideoScene, VideoScript, VideoSegment


class GeneratedImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedImage
        fields = [
            "id",
            "product",
            "kind",
            "concept",
            "prompt_en",
            "style",
            "instructions",
            "source_image",
            "image",
            "workflow_version",
            # the poster's Persian headline/price live here, and so does
            # `text_overlay_error` — without it a poster whose text overlay
            # failed looks exactly like one that worked
            "metadata",
            "created_at",
        ]


class CaptionSerializer(serializers.ModelSerializer):
    about_image_url = serializers.SerializerMethodField()
    about_label = serializers.SerializerMethodField()

    class Meta:
        model = Caption
        fields = [
            "id",
            "product",
            "platform",
            "tone",
            "objective",
            "short_text",
            "medium_text",
            "long_text",
            "hashtags",
            "cta",
            "about_image",
            "about_video",
            "about_image_url",
            "about_label",
            "created_at",
        ]

    def get_about_image_url(self, obj):
        if obj.about_image and obj.about_image.image:
            request = self.context.get("request")
            url = obj.about_image.image.url
            return request.build_absolute_uri(url) if request else url
        return None

    def get_about_label(self, obj):
        if obj.about_image:
            kind = {
                "POSTER": "پوستر",
                "PRODUCT_SHOT": "عکس اینستاگرامی",
                "ENHANCED": "عکس بهبودیافته",
            }.get(obj.about_image.kind, "تصویر")
            return f"برای {kind} #{obj.about_image_id}"
        if obj.about_video:
            return f"برای ویدیو #{obj.about_video_id}"
        return "برای خود محصول"


class VideoSceneSerializer(serializers.ModelSerializer):
    #: What will actually play under this scene: the shop's or the script
    #: model's choice where one was made, the planner's reading of the scene's
    #: words otherwise. The panel shows it so "خودکار" is never a mystery.
    sound_plan = serializers.SerializerMethodField()

    class Meta:
        model = VideoScene
        fields = [
            "index",
            "duration",
            "visual_prompt",
            "motion_prompt",
            "narration",
            "transition",
            "sound",
            "sound_plan",
            "speaker_on_camera",
        ]

    def get_sound_plan(self, obj) -> dict:
        from services.audio import soundscape

        try:
            plan = soundscape.plan_scene(obj)
        except Exception:  # noqa: BLE001 — a display aid must never break the script view
            return {"ambience": None, "ambience_label": None, "effects": []}
        ambience = plan.get("ambience")
        return {
            "ambience": ambience,
            "ambience_label": soundscape.CATALOGUE[ambience].label if ambience in soundscape.CATALOGUE else None,
            "effects": [
                {**e, "label": soundscape.CATALOGUE[e["key"]].label}
                for e in plan.get("effects", []) if e.get("key") in soundscape.CATALOGUE
            ],
        }


class VideoSegmentSerializer(serializers.ModelSerializer):
    #: The QC verdict, flattened out of `metadata` so the panel does not have
    #: to know the shape of an internal blob. A score nobody can see changes
    #: nothing about the product.
    quality = serializers.SerializerMethodField()

    class Meta:
        model = VideoSegment
        fields = [
            "index",
            "status",
            "anchor_source",
            "video",
            "last_frame",
            "retry_count",
            "error",
            "quality",
            "updated_at",
        ]

    def get_quality(self, obj) -> dict | None:
        meta = obj.metadata or {}
        report = meta.get("qc")
        if not report:
            return None
        before = meta.get("qc_before_repair") or {}
        code_repair = meta.get("code_repair") or {}
        return {
            "overall": report.get("overall"),
            "verdict": report.get("verdict"),
            # Only the axes worth mentioning: a list of eight perfect scores is
            # noise, and the one that dropped is the whole message.
            "problems": [
                axis for axis in report.get("axes", [])
                if axis.get("note") or (axis.get("score") or 100) < 80
            ],
            "vision_checked": report.get("vision_checked", False),
            "vision_reason": report.get("vision_reason", ""),
            "repaired": code_repair.get("applied") if code_repair.get("repaired") else [],
            "plan": meta.get("repair_plan"),
            # Before/after of a code repair, so the shop (and we) can see what
            # the filter changed rather than wonder why the clip differs from
            # the preview. `original_video` is the un-repaired render.
            "original_video": meta.get("original_video"),
            "overall_before_repair": before.get("overall"),
            "attempts": len(meta.get("attempts") or []),
        }


class VideoScriptSerializer(serializers.ModelSerializer):
    scenes = VideoSceneSerializer(many=True, read_only=True)
    segments = VideoSegmentSerializer(many=True, read_only=True)

    class Meta:
        model = VideoScript
        fields = [
            "id",
            "product",
            "concept",
            "objective",
            "cta",
            "total_duration",
            "narration_language",
            "status",
            "final_video",
            "voice_audio",
            "final_video_voiced",
            "sound_design",
            "scenes",
            "segments",
            "created_at",
            "updated_at",
        ]

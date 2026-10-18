from django.db import models

from apps.ai.models import AIRequest
from apps.common.models import TimeStampedModel
from apps.products.models import Product, ProductImage
from apps.stores.models import Store


class Caption(TimeStampedModel):
    """Platform-specific caption set for a product (Phase 10)."""

    class Platform(models.TextChoices):
        INSTAGRAM = "INSTAGRAM", "اینستاگرام"
        TELEGRAM = "TELEGRAM", "تلگرام"
        LINKEDIN = "LINKEDIN", "لینکدین"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="captions")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="captions")
    platform = models.CharField(max_length=16, choices=Platform.choices)
    tone = models.CharField(max_length=100, blank=True)
    objective = models.CharField(max_length=200, blank=True)
    short_text = models.TextField(blank=True)
    medium_text = models.TextField(blank=True)
    long_text = models.TextField(blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    cta = models.CharField(max_length=300, blank=True)
    # beter.md #11: a caption belongs to a specific piece of CONTENT (a generated
    # poster/photo or a video), not to the product in the abstract. Both empty =
    # legacy product-level caption.
    about_image = models.ForeignKey(
        "GeneratedImage", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="captions",
    )
    about_video = models.ForeignKey(
        "VideoScript", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="captions",
    )
    source_request = models.ForeignKey(
        AIRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "کپشن"
        verbose_name_plural = "کپشن‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.platform} caption for {self.product.name}"


class GeneratedImage(TimeStampedModel):
    """AI-generated marketing image (Phase 9 — Image Studio)."""

    class Kind(models.TextChoices):
        POSTER = "POSTER", "پوستر تبلیغاتی"
        PRODUCT_SHOT = "PRODUCT_SHOT", "عکس محصول آماده‌ی اینستاگرام"
        ENHANCED = "ENHANCED", "بهبود تصویر با حفظ خود محصول"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="generated_images")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="generated_images")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    concept = models.TextField(blank=True)
    prompt_en = models.TextField(blank=True)
    negative_en = models.TextField(blank=True)
    style = models.CharField(max_length=200, blank=True)
    instructions = models.TextField(blank=True)
    source_image = models.ForeignKey(
        ProductImage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    image = models.FileField(upload_to="generated/images/")
    workflow_version = models.CharField(max_length=40, blank=True)
    source_request = models.ForeignKey(
        AIRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "تصویر تولیدشده"
        verbose_name_plural = "تصویرهای تولیدشده"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} image for {self.product.name}"


class VideoScript(TimeStampedModel):
    """Machine-readable advertising video plan (Phase 11)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        GENERATING = "GENERATING", "در حال ساخت ویدیو"
        READY = "READY", "ویدیو آماده"
        FAILED = "FAILED", "شکست خورد"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="video_scripts")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="video_scripts")
    concept = models.TextField(blank=True)
    objective = models.CharField(max_length=200, blank=True)
    cta = models.CharField(max_length=300, blank=True)
    total_duration = models.PositiveIntegerField(default=30)
    # narration + voice-over language ('fa' or 'en') — chosen in the UI
    narration_language = models.CharField(max_length=5, default="fa")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    final_video = models.FileField(upload_to="generated/videos/", null=True, blank=True)
    voice_audio = models.FileField(upload_to="generated/audio/", null=True, blank=True)
    #: What the voice job produced besides the words: which engine spoke,
    #: which ambience and effects were laid under it per scene, and the credit
    #: line of every recording used. Shown next to the voiced video.
    sound_design = models.JSONField(default=dict, blank=True)
    final_video_voiced = models.FileField(upload_to="generated/videos/", null=True, blank=True)
    #: The version ending on the shop's own real photo (§26). A separate field
    #: rather than overwriting the voiced cut, so a shop that decides against
    #: showing their face still has the video they had a minute ago.
    final_video_real = models.FileField(
        upload_to="generated/videos/", null=True, blank=True,
    )
    #: Subtitles, generated from the narration we wrote — no speech-to-text
    #: needed, because we already know every word that was said.
    subtitles = models.FileField(
        upload_to="generated/subtitles/", null=True, blank=True,
    )
    #: Per video, because the answer genuinely differs: a product demo wants
    #: subtitles (most people watch muted), a mood piece with no speech does
    #: not. Null means "whatever the shop's default is" — see
    #: `subtitles_wanted`.
    subtitles_enabled = models.BooleanField(null=True, blank=True, default=None)
    #: Burned into the picture, or a separate .srt file. Burned-in survives
    #: every platform that strips subtitle tracks; a file stays editable.
    subtitles_burned = models.BooleanField(null=True, blank=True, default=None)
    #: Music the shop supplied. We never ship audio: an imperfect licence
    #: becomes a copyright strike on *their* account, weeks later.
    music = models.FileField(upload_to="uploads/music/", null=True, blank=True)
    #: Where the track came from and what it obliges the shop to do. Kept with
    #: the file because a licence is only useful next to the thing it licenses —
    #: a credit line in a different table is one nobody pastes into the post.
    music_source = models.URLField(blank=True)
    music_licence = models.CharField(max_length=20, blank=True)
    music_attribution = models.CharField(
        max_length=400, blank=True,
        help_text="متنی که باید در توضیحات پست بنویسید — برای CC-BY اجباری است",
    )
    music_level_db = models.FloatField(
        default=-22.0,
        help_text="بلندی موسیقی نسبت به صدا. هرچه بنویسید، از سقف امن بالاتر نمی‌رود",
    )
    #: The cut with music laid under the narration.
    final_video_music = models.FileField(
        upload_to="generated/videos/", null=True, blank=True,
    )
    raw = models.JSONField(default=dict, blank=True)
    source_request = models.ForeignKey(
        AIRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "سناریوی ویدیو"
        verbose_name_plural = "سناریوهای ویدیو"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Video script #{self.id} for {self.product.name}"


class VideoScene(models.Model):
    class Transition(models.TextChoices):
        CONTINUE = "CONTINUE", "Continue from last frame"
        TRANSITION = "TRANSITION", "Soft transition"
        NEW_SCENE = "NEW_SCENE", "New visual anchor"

    script = models.ForeignKey(VideoScript, on_delete=models.CASCADE, related_name="scenes")
    index = models.PositiveIntegerField()
    duration = models.PositiveIntegerField(default=5)
    visual_prompt = models.TextField()
    motion_prompt = models.TextField(blank=True)
    narration = models.TextField(blank=True)
    transition = models.CharField(
        max_length=12, choices=Transition.choices, default=Transition.CONTINUE
    )
    #: Structured scene description from the script — characters, objects,
    #: location, lighting, camera, clothing, colours, action. See
    #: services.video.scene_state. Whatever the script leaves out is inherited
    #: from the previous segment rather than reset, because silence means
    #: "as before" and treating it as a reset is what makes stitched video drift.
    state = models.JSONField(default=dict, blank=True)
    #: What this scene should SOUND like besides the voice — an ambience and
    #: up to two effects, from services.audio.soundscape.CATALOGUE. Written by
    #: the script model; empty means "decide from the scene's own words".
    sound = models.JSONField(default=dict, blank=True)
    #: The person in this scene SPEAKS the narration to camera. Their mouth is
    #: redrawn to the narration with lip-sync (services.video.lipsync), the
    #: video prompt asks for a frontal face instead of a closed mouth, and the
    #: mouth check does not reject the scene for talking. Off by default:
    #: every other scene is a voice-over, where a moving mouth is a defect.
    speaker_on_camera = models.BooleanField(default=False)

    class Meta:
        ordering = ["index"]
        constraints = [
            models.UniqueConstraint(fields=["script", "index"], name="uniq_scene_index")
        ]

    def __str__(self):
        return f"Scene {self.index} of script #{self.script_id}"


class VideoCut(TimeStampedModel):
    """One platform-shaped cut of a finished video. `ایده‌ها.md` §10.

    Rows rather than files-on-disk-only, because the shop needs to know which
    cuts exist for which video without a directory listing, and because a cut
    that was trimmed to fit a story has to say so — the owner is about to post
    it and needs to know the last ten seconds are missing.
    """

    script = models.ForeignKey(
        "VideoScript", on_delete=models.CASCADE, related_name="cuts"
    )
    #: `reel`, `story`, `feed`, `square`, `wide` — see services.video.repurpose.
    format = models.CharField(max_length=16)
    video = models.FileField(upload_to="generated/cuts/")
    trimmed = models.BooleanField(
        default=False,
        help_text="طول اصلی از سقف این قالب بیشتر بود و کوتاه شد",
    )
    #: True when the source had narration mixed in, so the owner knows whether
    #: this cut can be posted with sound.
    has_audio = models.BooleanField(default=False)

    class Meta:
        ordering = ["script", "format"]
        constraints = [
            models.UniqueConstraint(
                fields=["script", "format"], name="one_cut_per_format"
            ),
        ]
        verbose_name = "برش ویدیو"
        verbose_name_plural = "برش‌های ویدیو"

    def __str__(self):
        return f"{self.format} of script #{self.script_id}"


class VideoSegment(TimeStampedModel):
    """One generated ~5s clip. Files live under MEDIA and are tracked here (Phase 12)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        GENERATING = "GENERATING", "Generating"
        DONE = "DONE", "Done"
        FAILED = "FAILED", "Failed"

    script = models.ForeignKey(VideoScript, on_delete=models.CASCADE, related_name="segments")
    index = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    anchor_source = models.CharField(max_length=200, blank=True)
    video = models.FileField(upload_to="generated/videos/", null=True, blank=True)
    last_frame = models.FileField(upload_to="generated/frames/", null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    #: The state this segment actually rendered with, after inheritance. The
    #: next segment starts from this rather than from the script, so a resumed
    #: job continues the video that exists instead of the one that was planned.
    scene_state = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["index"]
        constraints = [
            models.UniqueConstraint(fields=["script", "index"], name="uniq_segment_index")
        ]

    def __str__(self):
        return f"Segment {self.index} of script #{self.script_id} [{self.status}]"


class EditDecision(TimeStampedModel):
    """One thing a shop said yes or no to in the editor. §9.

    Rows rather than a folded-in preference, because a habit derived from counts
    can be re-derived when the rules change and an average that was written into
    a preference three months ago cannot. It also means «چرا این کار را کرد؟» has
    an answer: the decisions are still here.
    """

    class Source(models.TextChoices):
        SUGGESTED = "SUGGESTED", "پیشنهاد سیستم"
        MANUAL = "MANUAL", "خود کاربر"
        DIRECTED = "DIRECTED", "کارگردانی"
        AUTO = "AUTO", "خودکار"

    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="edit_decisions",
    )
    video = models.ForeignKey(
        "UploadedVideo", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="decisions",
    )
    tool = models.CharField(max_length=40)
    params = models.JSONField(default=dict, blank=True)
    #: False is the informative case: a tool turned down four times is a clear
    #: instruction, while an accepted suggestion mostly means it was not annoying.
    accepted = models.BooleanField(default=True)
    source = models.CharField(
        max_length=12, choices=Source.choices, default=Source.SUGGESTED,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "tool"])]

    def __str__(self):
        return f"{self.tool} {'✓' if self.accepted else '✗'} ({self.store_id})"


class UploadedVideo(TimeStampedModel):
    """A video the shop filmed themselves. §8, §10.

    §8 is explicit that the editing engine serves both our generated videos and
    «ویدیویی که خود مشتری آپلود می‌کند» — and §10 turns one of those into ten
    outputs. The measurements are cached on the row because they cost an ffmpeg
    pass each and nothing about a finished upload changes them.
    """

    class State(models.TextChoices):
        UPLOADED = "UPLOADED", "آپلود شد"
        ANALYZING = "ANALYZING", "در حال بررسی"
        READY = "READY", "آماده‌ی تدوین"
        EDITED = "EDITED", "تدوین شد"
        FAILED = "FAILED", "خطا"

    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="uploaded_videos",
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="uploaded_videos",
    )
    title = models.CharField(max_length=200, blank=True)
    video = models.FileField(upload_to="uploads/videos/")
    edited = models.FileField(upload_to="generated/edited/", null=True, blank=True)
    state = models.CharField(
        max_length=12, choices=State.choices, default=State.UPLOADED,
    )
    duration = models.FloatField(default=0)
    has_audio = models.BooleanField(default=True)
    #: What `analysis.describe` measured. Cached because each read is an ffmpeg
    #: pass and a finished upload does not change.
    facts = models.JSONField(default=dict, blank=True)
    #: The last edit, as the agent reported it: the plan that ran, the
    #: measurements before and after, and what each tool did to its own
    #: target. This is what lets the panel put the original and the edited
    #: video side by side with the numbers that changed between them.
    edit_outcome = models.JSONField(default=dict, blank=True)
    transcript = models.JSONField(default=list, blank=True)
    #: Same three-state switch as a generated video: on, off, or "ask the shop
    #: default". Subtitling someone's own footage needs Whisper, so the panel
    #: says what it costs before turning it on.
    subtitles_enabled = models.BooleanField(null=True, blank=True, default=None)
    subtitles_burned = models.BooleanField(null=True, blank=True, default=None)
    subtitles = models.FileField(
        upload_to="generated/subtitles/", null=True, blank=True,
    )
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Upload #{self.pk}"

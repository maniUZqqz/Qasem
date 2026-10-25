from django.urls import path

from .views_voice_clone import (
    ClonedVoiceBuildView,
    ClonedVoiceClipAudioView,
    ClonedVoiceClipsView,
    ClonedVoiceClipView,
    ClonedVoiceDetailView,
    ClonedVoiceListView,
    ClonedVoiceSampleView,
    ClonedVoiceTestAudioView,
    ClonedVoiceTestStatusView,
    ClonedVoiceTestView,
    ClonedVoiceUseView,
)
from .views_sound import (
    SceneSoundView,
    SceneSpeakerView,
    SoundCatalogueView,
    StoreVoiceView,
    VoicePreviewView,
)
from .views_editing import (
    EditApplyView,
    MusicLibraryView,
    MusicView,
    SubtitleView,
    UploadSubtitleView,
    EditPlanView,
    EditRejectView,
    RealPhotoView,
    RepurposeUploadView,
    UploadedVideoDetailView,
    UploadedVideoListView,
)
from .views import (
    CaptionView,
    ImageStudioView,
    ProductReadinessView,
    VideoCutsView,
    VideoGenerateView,
    VideoScriptView,
    VoiceGenerateView,
)


urlpatterns = [
    path("products/<int:pk>/captions/", CaptionView.as_view(), name="product-captions"),
    path("products/<int:pk>/image-studio/", ImageStudioView.as_view(), name="product-image-studio"),
    path("products/<int:pk>/video-script/", VideoScriptView.as_view(), name="product-video-script"),
    # What Advanced mode asks for before generating (§25).
    path(
        "products/<int:pk>/readiness/",
        ProductReadinessView.as_view(), name="product-readiness",
    ),
    path("video-scripts/<int:pk>/generate/", VideoGenerateView.as_view(), name="video-generate"),
    path("video-scripts/<int:pk>/voice/", VoiceGenerateView.as_view(), name="video-voice"),
    # The shop's side of sound: its narrator, its pronunciations, and each
    # scene's ambience and effects. Engines themselves are the admin's.
    path(
        "video-scripts/<int:pk>/scenes/<int:index>/sound/",
        SceneSoundView.as_view(), name="scene-sound",
    ),
    path(
        "video-scripts/<int:pk>/scenes/<int:index>/on-camera/",
        SceneSpeakerView.as_view(), name="scene-on-camera",
    ),
    path("stores/<int:store_id>/voice/", StoreVoiceView.as_view(), name="store-voice"),
    path(
        "stores/<int:store_id>/voice/preview/",
        VoicePreviewView.as_view(), name="store-voice-preview",
    ),
    # «کلونِ صدا»: consent, recordings and builds here; the voice itself on a processing node.
    path("stores/<int:store_id>/voice/clones/", ClonedVoiceListView.as_view(), name="voice-clones"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/", ClonedVoiceDetailView.as_view(), name="voice-clone"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/clips/", ClonedVoiceClipsView.as_view(),
         name="voice-clone-clips"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/clips/<int:index>/", ClonedVoiceClipView.as_view(),
         name="voice-clone-clip"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/clips/<int:index>/audio/",
         ClonedVoiceClipAudioView.as_view(), name="voice-clone-clip-audio"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/build/", ClonedVoiceBuildView.as_view(),
         name="voice-clone-build"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/sample/", ClonedVoiceSampleView.as_view(),
         name="voice-clone-sample"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/test/", ClonedVoiceTestView.as_view(),
         name="voice-clone-test"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/test/<uuid:uid>/", ClonedVoiceTestStatusView.as_view(),
         name="voice-clone-test-status"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/test/<uuid:uid>/audio/",
         ClonedVoiceTestAudioView.as_view(), name="voice-clone-test-audio"),
    path("stores/<int:store_id>/voice/clones/<int:pk>/use/", ClonedVoiceUseView.as_view(),
         name="voice-clone-use"),
    path("audio/sounds/", SoundCatalogueView.as_view(), name="sound-catalogue"),
    # One shoot, every platform (`ایده‌ها.md` §10).
    path("video-scripts/<int:pk>/cuts/", VideoCutsView.as_view(), name="video-cuts"),

    # ---- the editing engine (ideas §8-§10) -------------------------------
    path(
        "stores/<int:store_id>/videos/",
        UploadedVideoListView.as_view(), name="uploaded-videos",
    ),
    path(
        "stores/<int:store_id>/videos/<int:pk>/",
        UploadedVideoDetailView.as_view(), name="uploaded-video",
    ),
    # Planning and applying are separate so that "suggest" can mean suggest.
    path(
        "stores/<int:store_id>/videos/<int:pk>/plan/",
        EditPlanView.as_view(), name="edit-plan",
    ),
    path(
        "stores/<int:store_id>/videos/<int:pk>/edit/",
        EditApplyView.as_view(), name="edit-apply",
    ),
    path(
        "stores/<int:store_id>/videos/<int:pk>/reject/",
        EditRejectView.as_view(), name="edit-reject",
    ),
    path(
        "stores/<int:store_id>/videos/<int:pk>/repurpose/",
        RepurposeUploadView.as_view(), name="upload-repurpose",
    ),
    # §26 — the real photo at the end, as an explicit choice.
    path(
        "stores/<int:store_id>/video-scripts/<int:pk>/real-photo/",
        RealPhotoView.as_view(), name="video-real-photo",
    ),
    # §8 — subtitles, free because we wrote the narration ourselves.
    path(
        "stores/<int:store_id>/video-scripts/<int:pk>/subtitles/",
        SubtitleView.as_view(), name="video-subtitles",
    ),
    # §7 — the shop's own music. We never ship audio; the licence is theirs.
    path(
        "stores/<int:store_id>/video-scripts/<int:pk>/music/",
        MusicView.as_view(), name="video-music",
    ),
    # §8 — subtitles for video the shop filmed themselves. Needs Whisper.
    path(
        "stores/<int:store_id>/videos/<int:pk>/subtitles/",
        UploadSubtitleView.as_view(), name="upload-subtitles",
    ),
    # §7 — free music a shop may actually use. Licence filtering is in
    # the service layer, so tracks they may not use never appear.
    path(
        "stores/<int:store_id>/music-library/",
        MusicLibraryView.as_view(), name="music-library",
    ),
]

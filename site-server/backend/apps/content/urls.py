from django.urls import path

from .views_caption_edit import CaptionDetailView
from .views_audio import (
    AudioAssetDetailView,
    AudioAssetFileView,
    AudioAssetListView,
    AudioAssetRetryView,
    AudioAssetUploadView,
    AudioOverviewView,
    VideoSoundMixView,
)
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
from .views_editor_pro import (
    CaptionsStatusView,
    CaptionsTranslateView,
    ProjectCollectView,
    CaptionsView,
    EditorAnalysisView,
    EditorCatalogueView,
    ProjectPreviewView,
    ProjectRendersView,
)
from .views_editor_pro2 import (
    EditorLutDetailView,
    EditorLutFileView,
    EditorLutsView,
    EditorMatteDetailView,
    EditorMattesView,
    EditorSyncView,
    EditorTrackView,
    MatteStatusView,
    RenderWhereView,
)
from .views_director import (
    DirectorApplyView,
    DirectorCatalogueView,
    DirectorDraftDetailView,
    DirectorDraftOpenView,
    DirectorDraftsView,
    DirectorRerunView,
    DirectorRunView,
    EditorReframeView,
    EditorScenesView,
    EditorSettingsView,
    ProjectVersionRestoreView,
    ProjectVersionsView,
)
from .views_autoedit import LookPreviewView, ProjectSizesView, SilenceReviewView, SizesCatalogueView, UploadAutoEditView
from .views_upload import UploadChunkView, UploadFinishView, UploadStartView
from .views_timeline import (
    EditorBinView,
    EditorProxyView,
    EditorSubtitlesView,
    ProjectDetailView,
    ProjectListView,
    ProjectRenderView,
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
    path("products/<int:pk>/captions/<int:caption_id>/", CaptionDetailView.as_view(), name="product-caption-detail"),
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
    # «صدا»: speech, ambience/effects, music and the library; and the same sounds under a video
    path("stores/<int:store_id>/audio/", AudioOverviewView.as_view(), name="audio-overview"),
    path("stores/<int:store_id>/audio/assets/", AudioAssetListView.as_view(), name="audio-assets"),
    path("stores/<int:store_id>/audio/assets/upload/", AudioAssetUploadView.as_view(), name="audio-asset-upload"),
    path("stores/<int:store_id>/audio/assets/<int:pk>/", AudioAssetDetailView.as_view(), name="audio-asset"),
    path("stores/<int:store_id>/audio/assets/<int:pk>/retry/", AudioAssetRetryView.as_view(), name="audio-asset-retry"),
    path("stores/<int:store_id>/audio/assets/<int:pk>/file/", AudioAssetFileView.as_view(),
         name="audio-asset-file"),
    path("stores/<int:store_id>/video-scripts/<int:pk>/sound-mix/", VideoSoundMixView.as_view(),
         name="video-sound-mix"),
    path("audio/sounds/", SoundCatalogueView.as_view(), name="sound-catalogue"),
    # One shoot, every platform (`ایده‌ها.md` §10).
    path("video-scripts/<int:pk>/cuts/", VideoCutsView.as_view(), name="video-cuts"),

    # ---- the «دستی» workspace: media bin, timeline projects, render -----
    path("stores/<int:store_id>/editor/bin/", EditorBinView.as_view(), name="editor-bin"),
    path("stores/<int:store_id>/editor/proxy/", EditorProxyView.as_view(), name="editor-proxy"),
    path("stores/<int:store_id>/editor/subtitles/", EditorSubtitlesView.as_view(), name="editor-subtitles"),
    path("stores/<int:store_id>/editor/projects/", ProjectListView.as_view(), name="editor-projects"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/", ProjectDetailView.as_view(), name="editor-project"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/render/", ProjectRenderView.as_view(), name="editor-project-render"),
    path("stores/<int:store_id>/editor/catalogue/", EditorCatalogueView.as_view(), name="editor-catalogue"),
    path("stores/<int:store_id>/editor/analysis/", EditorAnalysisView.as_view(), name="editor-analysis"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/preview/", ProjectPreviewView.as_view(), name="editor-project-preview"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/renders/", ProjectRendersView.as_view(), name="editor-project-renders"),
    path("stores/<int:store_id>/editor/captions/status/", CaptionsStatusView.as_view(), name="editor-captions-status"),
    path("stores/<int:store_id>/editor/captions/", CaptionsView.as_view(), name="editor-captions"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/collect/", ProjectCollectView.as_view(), name="editor-project-collect"),
    path("stores/<int:store_id>/editor/captions/translate/", CaptionsTranslateView.as_view(), name="editor-captions-translate"),
    path("stores/<int:store_id>/editor/luts/", EditorLutsView.as_view(), name="editor-luts"),
    path("stores/<int:store_id>/editor/luts/<str:key>/", EditorLutDetailView.as_view(), name="editor-lut"),
    path("stores/<int:store_id>/editor/luts/<str:key>/file/", EditorLutFileView.as_view(), name="editor-lut-file"),
    path("stores/<int:store_id>/editor/track/", EditorTrackView.as_view(), name="editor-track"),
    path("stores/<int:store_id>/editor/multicam/sync/", EditorSyncView.as_view(), name="editor-multicam-sync"),
    path("stores/<int:store_id>/editor/matte/status/", MatteStatusView.as_view(), name="editor-matte-status"),
    path("stores/<int:store_id>/editor/mattes/", EditorMattesView.as_view(), name="editor-mattes"),
    path("stores/<int:store_id>/editor/mattes/<str:key>/", EditorMatteDetailView.as_view(), name="editor-matte"),
    path("stores/<int:store_id>/editor/render-where/", RenderWhereView.as_view(), name="editor-render-where"),
    # ---- the director (semi-automatic edit), one-click sound tools, auto-reframe, project versions
    path("stores/<int:store_id>/editor/director/catalogue/", DirectorCatalogueView.as_view(), name="editor-director-catalogue"),
    path("stores/<int:store_id>/editor/director/run/", DirectorRunView.as_view(), name="editor-director-run"),
    path("stores/<int:store_id>/editor/director/rerun/", DirectorRerunView.as_view(), name="editor-director-rerun"),
    path("stores/<int:store_id>/editor/director/apply/", DirectorApplyView.as_view(), name="editor-director-apply"),
    path("stores/<int:store_id>/editor/director/drafts/", DirectorDraftsView.as_view(), name="editor-director-drafts"),
    path("stores/<int:store_id>/editor/director/drafts/<int:pk>/open/", DirectorDraftOpenView.as_view(), name="editor-director-draft-open"),
    path("stores/<int:store_id>/editor/director/drafts/<int:pk>/", DirectorDraftDetailView.as_view(), name="editor-director-draft"),
    path("stores/<int:store_id>/editor/settings/", EditorSettingsView.as_view(), name="editor-settings"),
    path("stores/<int:store_id>/editor/reframe/", EditorReframeView.as_view(), name="editor-reframe"),
    path("stores/<int:store_id>/editor/scenes/", EditorScenesView.as_view(), name="editor-scenes"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/versions/", ProjectVersionsView.as_view(), name="editor-project-versions"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/versions/<str:name>/", ProjectVersionRestoreView.as_view(), name="editor-project-version-restore"),

    # ---- the editing engine (ideas §8-§10) -------------------------------
    # ---- the automatic edit: ask about doubtful pauses, every network's size, the polish run for an upload
    path("stores/<int:store_id>/autoedit/silences/", SilenceReviewView.as_view(), name="autoedit-silences"),
    path("stores/<int:store_id>/autoedit/sizes/", SizesCatalogueView.as_view(), name="autoedit-sizes"),
    path("stores/<int:store_id>/autoedit/look-preview/", LookPreviewView.as_view(), name="autoedit-look-preview"),
    path("stores/<int:store_id>/editor/projects/<int:pk>/sizes/", ProjectSizesView.as_view(), name="autoedit-project-sizes"),
    path("stores/<int:store_id>/videos/<int:pk>/autoedit/", UploadAutoEditView.as_view(), name="autoedit-upload"),
    path("stores/<int:store_id>/videos/uploads/", UploadStartView.as_view(), name="video-upload-start"),
    path("stores/<int:store_id>/videos/uploads/<str:uid>/", UploadChunkView.as_view(), name="video-upload-chunk"),
    path("stores/<int:store_id>/videos/uploads/<str:uid>/finish/", UploadFinishView.as_view(), name="video-upload-finish"),
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

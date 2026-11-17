from django.urls import path

from . import views as v

P = "stores/<int:store_id>/brand-character/"
C = P + "characters/<int:pk>/"

urlpatterns = [
    path(P, v.OverviewView.as_view(), name="brandchar-overview"),
    path(P + "node/", v.NodeView.as_view(), name="brandchar-node"),
    # شخصیتِ گفتار
    path(P + "persona/", v.PersonaView.as_view(), name="brandchar-persona"),
    path(P + "persona/draft/", v.PersonaDraftView.as_view(), name="brandchar-persona-draft"),
    path(P + "persona/lock/", v.PersonaLockView.as_view(), name="brandchar-persona-lock"),
    path(P + "persona/unlock/", v.PersonaUnlockView.as_view(), name="brandchar-persona-unlock"),
    path(P + "persona/active/", v.PersonaActiveView.as_view(), name="brandchar-persona-active"),
    path(P + "persona/versions/", v.PersonaVersionsView.as_view(), name="brandchar-persona-versions"),
    path(P + "persona/restore/", v.PersonaRestoreView.as_view(), name="brandchar-persona-restore"),
    path(P + "persona/prompt/", v.PersonaPromptView.as_view(), name="brandchar-persona-prompt"),
    # شخصیتِ دیداری
    path(P + "characters/", v.CharactersView.as_view(), name="brandchar-characters"),
    path(C, v.CharacterView.as_view(), name="brandchar-character"),
    path(C + "lock/", v.LockView.as_view(), name="brandchar-lock"),
    path(C + "unlock/", v.UnlockView.as_view(), name="brandchar-unlock"),
    path(C + "primary/", v.PrimaryView.as_view(), name="brandchar-primary"),
    path(C + "publish-mascot/", v.PublishMascotView.as_view(), name="brandchar-publish-mascot"),
    path(C + "check/", v.CheckView.as_view(), name="brandchar-check"),
    path(C + "cover/", v.CoverView.as_view(), name="brandchar-cover"),
    path(C + "versions/", v.VersionsView.as_view(), name="brandchar-versions"),
    path(C + "restore/", v.RestoreView.as_view(), name="brandchar-restore"),
    path(C + "preview/", v.PreviewView.as_view(), name="brandchar-preview"),
    path(C + "svg/", v.SvgView.as_view(), name="brandchar-svg"),
    path(C + "render/", v.RenderView.as_view(), name="brandchar-render"),
    path(C + "sticker/", v.StickerView.as_view(), name="brandchar-sticker"),
    path(C + "sheet/", v.SheetView.as_view(), name="brandchar-sheet"),
    path(C + "sheet-pdf/", v.SheetPdfView.as_view(), name="brandchar-sheet-pdf"),
    path(C + "svg-file/", v.SvgFileView.as_view(), name="brandchar-svg-file"),
    path(C + "export/", v.ExportView.as_view(), name="brandchar-export"),
    path(C + "renders/", v.RendersView.as_view(), name="brandchar-renders"),
    path(C + "renders/<int:rid>/", v.RenderItemView.as_view(), name="brandchar-render-item"),
    path(C + "renders/<int:rid>/download/", v.RenderDownloadView.as_view(), name="brandchar-render-download"),
    path(C + "ai-render/", v.AIRenderView.as_view(), name="brandchar-ai-render"),
    path(C + "ai-jobs/", v.AIJobsView.as_view(), name="brandchar-ai-jobs"),
    # ایده
    path(P + "concepts/", v.ConceptsView.as_view(), name="brandchar-concepts"),
    path(P + "concepts/<int:cid>/choose/", v.ConceptChooseView.as_view(), name="brandchar-concept-choose"),
    # قالب‌ها و کاربردها
    path(P + "templates/", v.TemplatesView.as_view(), name="brandchar-templates"),
    path(P + "templates/<str:tid>/render/", v.TemplateRenderView.as_view(), name="brandchar-template-render"),
    path(P + "usage/", v.UsageView.as_view(), name="brandchar-usage"),
    path(P + "use/motion/", v.UseMotionView.as_view(), name="brandchar-use-motion"),
    path(P + "use/thumbnail/", v.UseThumbnailView.as_view(), name="brandchar-use-thumbnail"),
    path(P + "use/site-hero/", v.UseSiteHeroView.as_view(), name="brandchar-use-site-hero"),
    path(P + "use/director/", v.UseDirectorView.as_view(), name="brandchar-use-director"),
    path(P + "use/inbox/", v.UseInboxView.as_view(), name="brandchar-use-inbox"),
]

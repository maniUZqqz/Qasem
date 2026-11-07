from django.urls import path

from . import views, views_designer, views_effects

P = "stores/<int:store_id>/photo-editor/"

urlpatterns = [
    path(P, views.OverviewView.as_view(), name="photoedit-overview"),
    path(P + "sources/", views.SourcesView.as_view(), name="photoedit-sources"),
    path(P + "assets/", views.AssetListView.as_view(), name="photoedit-assets"),
    path(P + "assets/<int:pk>/", views.AssetView.as_view(), name="photoedit-asset"),
    path(P + "assets/<int:pk>/analyze/", views.AssetAnalyzeView.as_view(), name="photoedit-asset-analyze"),
    path(P + "plan/", views.PlanView.as_view(), name="photoedit-plan"),
    path(P + "preview/", views.PreviewView.as_view(), name="photoedit-preview"),
    path(P + "edits/", views.EditListView.as_view(), name="photoedit-edits"),
    path(P + "edits/<int:pk>/", views.EditView.as_view(), name="photoedit-edit"),
    path(P + "edits/<int:pk>/<str:action>/", views.EditView.as_view(), name="photoedit-edit-action"),
    path(P + "batches/<str:batch>/zip/", views.BatchZipView.as_view(), name="photoedit-batch-zip"),
    path(P + "projects/", views.ProjectListView.as_view(), name="photoedit-projects"),
    path(P + "projects/<int:pk>/", views.ProjectView.as_view(), name="photoedit-project"),
    path(P + "projects/<int:pk>/masks/<str:mid>/", views.MaskView.as_view(), name="photoedit-mask"),
    path(P + "exact/", views.ExactView.as_view(), name="photoedit-exact"),
    path(P + "exact/<uuid:uid>/", views.ExactStatusView.as_view(), name="photoedit-exact-status"),
    path(P + "subject/", views.SubjectView.as_view(), name="photoedit-subject"),
    path(P + "subject/<uuid:uid>/", views.SubjectStatusView.as_view(), name="photoedit-subject-status"),
    path(P + "presets/", views.PresetListView.as_view(), name="photoedit-presets"),
    path(P + "presets/<int:pk>/", views.PresetView.as_view(), name="photoedit-preset"),
    path(P + "presets/<int:pk>/apply/", views.PresetApplyView.as_view(), name="photoedit-preset-apply"),
    path(P + "fonts/", views.FontsView.as_view(), name="photoedit-fonts"),
    path(P + "genfill/", views.GenFillView.as_view(), name="photoedit-genfill"),
    path(P + "genfill/translate/", views.GenFillTranslateView.as_view(), name="photoedit-genfill-translate"),
    path(P + "genfill/<uuid:uid>/", views.GenFillStatusView.as_view(), name="photoedit-genfill-status"),
    path(P + "genfill/<uuid:uid>/prompt/", views.GenFillPromptView.as_view(), name="photoedit-genfill-prompt"),
    path(P + "projects/<int:pk>/liquify/", views.LiquifyView.as_view(), name="photoedit-liquify"),
    # طراحِ خودکار (نیمه‌خودکار با دستور)
    path(P + "designer/", views_designer.DesignerInfoView.as_view(), name="photoedit-designer"),
    path(P + "designer/analyze/", views_designer.DesignerAnalyzeView.as_view(), name="photoedit-designer-analyze"),
    path(P + "designer/designs/", views_designer.DesignListView.as_view(), name="photoedit-designs"),
    path(P + "designer/designs/<int:pk>/", views_designer.DesignView.as_view(), name="photoedit-design"),
    path(P + "designer/designs/<int:pk>/rerender/", views_designer.DesignRerenderView.as_view(), name="photoedit-design-rerender"),
    path(P + "designer/designs/<int:pk>/apply/", views_designer.DesignApplyView.as_view(), name="photoedit-design-apply"),
    # نوبت ۴: تنظیماتِ فروشگاه (پیش‌فرضِ هوش مصنوعی + سبکِ برند) و طراحیِ گروهی
    path(P + "settings/", views_designer.SettingsView.as_view(), name="photoedit-settings"),
    path(P + "designer/batches/", views_designer.BatchListView.as_view(), name="photoedit-batches"),
    path(P + "designer/batches/<int:pk>/", views_designer.BatchView.as_view(), name="photoedit-batch"),
    path(P + "designer/batches/<int:pk>/zip/", views_designer.BatchZipView.as_view(), name="photoedit-batch-zip2"),
    # نوبت ۴: جعبهٔ فیلترها
    path(P + "effects/", views_effects.EffectsCatalogView.as_view(), name="photoedit-effects"),
    path(P + "effects/preview/", views_effects.EffectPreviewView.as_view(), name="photoedit-effect-preview"),
    path(P + "effects/apply/", views_effects.EffectApplyView.as_view(), name="photoedit-effect-apply"),
]

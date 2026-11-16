from django.urls import path

from . import views, views_custom, views_v2

P = "stores/<int:store_id>/motion/"

urlpatterns = [
    path("motion/styles/", views.StylesView.as_view(), name="motion-styles"),
    path("motion/styles/<str:style_id>/thumb/", views.style_thumb, name="motion-style-thumb"),
    path("motion/player/", views.player_page, name="motion-player"),
    path("motion/player/player.js", views.player_js, name="motion-player-js"),
    path("motion/player/fonts/<str:name>", views.player_font, name="motion-player-font"),
    path("motion/library/", views_v2.LibraryView.as_view(), name="motion-library"),
    path("motion/style-schema/", views_custom.SchemaView.as_view(), name="motion-style-schema"),
    path("motion/components/<str:cid>/thumb/", views_v2.component_thumb, name="motion-component-thumb"),
    path(P, views.OverviewView.as_view(), name="motion-overview"),
    path(P + "custom-styles/", views_custom.ListView.as_view(), name="motion-custom-styles"),
    path(P + "custom-styles/validate/", views_custom.ValidateView.as_view(), name="motion-custom-style-validate"),
    path(P + "custom-styles/describe/", views_custom.DescribeView.as_view(), name="motion-custom-style-describe"),
    path(P + "custom-styles/palette/", views_custom.PaletteView.as_view(), name="motion-custom-style-palette"),
    path(P + "custom-styles/preview/", views_custom.PreviewView.as_view(), name="motion-custom-style-preview"),
    path(P + "custom-styles/import/", views_custom.ImportView.as_view(), name="motion-custom-style-import"),
    path(P + "custom-styles/check/", views_custom.CheckView.as_view(), name="motion-custom-style-check"),
    path(P + "custom-styles/check/<int:cid>/", views_custom.CheckDetailView.as_view(), name="motion-custom-style-check-detail"),
    path(P + "custom-styles/<int:pk>/", views_custom.DetailView.as_view(), name="motion-custom-style"),
    path(P + "custom-styles/<int:pk>/export/", views_custom.ExportView.as_view(), name="motion-custom-style-export"),
    path(P + "sound/", views_v2.SoundView.as_view(), name="motion-sound"),
    path(P + "plans/", views_v2.PlansView.as_view(), name="motion-plans"),
    path(P + "plans/<int:pk>/", views_v2.PlanView.as_view(), name="motion-plan"),
    path(P + "plans/<int:pk>/<str:action>/", views_v2.PlanActionView.as_view(), name="motion-plan-action"),
    path(P + "assets/", views.AssetsView.as_view(), name="motion-assets"),
    path(P + "assets/<int:pk>/", views.AssetView.as_view(), name="motion-asset"),
    path(P + "sources/", views.SourcesView.as_view(), name="motion-sources"),
    path(P + "preview/", views.PreviewView.as_view(), name="motion-preview"),
    path(P + "ai/", views.AiView.as_view(), name="motion-ai"),
    path(P + "ai-code/", views.AiCodeView.as_view(), name="motion-ai-code"),
    path(P + "code/check/", views.CodeCheckView.as_view(), name="motion-code-check"),
    path(P + "renders/", views.RenderListView.as_view(), name="motion-renders"),
    path(P + "renders/<int:pk>/", views.RenderView.as_view(), name="motion-render"),
    path(P + "renders/<int:pk>/<str:action>/", views.RenderActionView.as_view(), name="motion-render-action"),
]

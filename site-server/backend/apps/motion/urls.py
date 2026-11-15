from django.urls import path

from . import views, views_v2

P = "stores/<int:store_id>/motion/"

urlpatterns = [
    path("motion/styles/", views.StylesView.as_view(), name="motion-styles"),
    path("motion/styles/<str:style_id>/thumb/", views.style_thumb, name="motion-style-thumb"),
    path("motion/player/", views.player_page, name="motion-player"),
    path("motion/player/player.js", views.player_js, name="motion-player-js"),
    path("motion/player/fonts/<str:name>", views.player_font, name="motion-player-font"),
    path("motion/library/", views_v2.LibraryView.as_view(), name="motion-library"),
    path("motion/components/<str:cid>/thumb/", views_v2.component_thumb, name="motion-component-thumb"),
    path(P, views.OverviewView.as_view(), name="motion-overview"),
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

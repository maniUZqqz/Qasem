from django.urls import path

from . import views

# نکته: مسیرهای ثابت (themes، compose، …) پیش از «<سبک>/» می‌آیند؛ آزمون می‌سنجد هیچ سبکی نامش با آن‌ها یکی نباشد.
urlpatterns = [
    path("looks/", views.LooksView.as_view(), name="looks-list"),
    path("looks/themes/", views.ThemesView.as_view(), name="looks-themes"),
    path("looks/themes/<str:key>/", views.ThemeView.as_view(), name="looks-theme"),
    path("looks/compose/", views.ComposeView.as_view(), name="looks-compose"),
    path("looks/check/", views.CheckView.as_view(), name="looks-check"),
    path("looks/suggest/", views.SuggestView.as_view(), name="looks-suggest"),
    path("looks/samples/", views.SamplesView.as_view(), name="looks-samples"),
    path("looks/<str:key>/", views.LookView.as_view(), name="looks-detail"),
    path("looks/<str:key>/preview.svg", views.PreviewSvgView.as_view(), name="looks-preview"),
    path("looks/<str:key>/sample.jpg", views.SampleImageView.as_view(), name="looks-sample"),
]

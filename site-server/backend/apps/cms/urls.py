from django.urls import path

from .views import (
    ArticleDetail,
    ArticleList,
    CategoryList,
    FaqList,
    ProofView,
    RedirectList,
    ResourceList,
    SeoPageList,
    ShowcaseList,
    SiteSettingsView,
)

urlpatterns = [
    path("blog/articles/", ArticleList.as_view(), name="blog-articles"),
    path("blog/articles/<str:slug>/", ArticleDetail.as_view(), name="blog-article"),
    path("blog/categories/", CategoryList.as_view(), name="blog-categories"),
    path("blog/redirects/", RedirectList.as_view(), name="blog-redirects"),
    # The public site's own content, edited in the admin rather than deployed.
    path("site/settings/", SiteSettingsView.as_view(), name="site-settings"),
    path("site/showcase/", ShowcaseList.as_view(), name="site-showcase"),
    path("site/faq/", FaqList.as_view(), name="site-faq"),
    path("site/pages/", SeoPageList.as_view(), name="site-pages"),
    # §11 · §12 · §13 — one subject, one request, three pages.
    path("site/proof/", ProofView.as_view(), name="site-proof"),
    path("site/resources/", ResourceList.as_view(), name="site-resources"),
]

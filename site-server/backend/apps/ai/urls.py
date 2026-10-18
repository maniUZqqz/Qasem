from django.urls import path

from .views import EmbeddingsView, MarketAnalysisView, ProductAnalyzeView, ProductIntelligenceView
from .views_competitors import (
    CompetitorDetailView,
    CompetitorListView,
    CompetitorProductsView,
    OpportunityDetailView,
    OpportunityListView,
    ProfitReportView,
)
from .views_policy import StoreAIPolicyView
from .views_providers import AIProviderHealthView, AIStatusView



from .views_trends import (
    TrendIdeaDismissView,
    TrendIdeaUseView,
    TrendIdeaView,
    TrendListView,
)

urlpatterns = [
    path("ai/status/", AIStatusView.as_view(), name="ai-status"),
    path(
        "stores/<int:store_id>/ai-policy/",
        StoreAIPolicyView.as_view(),
        name="store-ai-policy",
    ),
    path("ai/providers/health/", AIProviderHealthView.as_view(), name="ai-provider-health"),
    path("products/<int:pk>/analyze/", ProductAnalyzeView.as_view(), name="product-analyze"),
    # ---- competitors (§3) ------------------------------------------------
    path(
        "stores/<int:store_id>/competitors/",
        CompetitorListView.as_view(), name="competitor-list",
    ),
    path(
        "stores/<int:store_id>/competitors/<int:pk>/",
        CompetitorDetailView.as_view(), name="competitor-detail",
    ),
    path(
        "stores/<int:store_id>/competitors/<int:pk>/products/",
        CompetitorProductsView.as_view(), name="competitor-products",
    ),
    # ---- profit and opportunities (§4, §5) -------------------------------
    path(
        "stores/<int:store_id>/profit/",
        ProfitReportView.as_view(), name="store-profit",
    ),
    path(
        "stores/<int:store_id>/opportunities/",
        OpportunityListView.as_view(), name="opportunity-list",
    ),
    path(
        "stores/<int:store_id>/opportunities/<int:pk>/",
        OpportunityDetailView.as_view(), name="opportunity-detail",
    ),
    path("stores/<int:store_id>/embeddings/", EmbeddingsView.as_view(), name="store-embeddings"),
    path(
        "stores/<int:store_id>/embeddings/rebuild/",
        EmbeddingsView.as_view(),
        name="store-embeddings-rebuild",
    ),
    path(
        "products/<int:pk>/intelligence/",
        ProductIntelligenceView.as_view(),
        name="product-intelligence",
    ),
    path(
        "products/<int:pk>/market-analysis/",
        MarketAnalysisView.as_view(),
        name="product-market-analysis",
    ),
    # ---- trending (§6) ---------------------------------------------------
    path(
        "stores/<int:store_id>/trends/",
        TrendListView.as_view(), name="store-trends",
    ),
    path(
        "stores/<int:store_id>/trends/ideas/",
        TrendIdeaView.as_view(), name="trend-ideas",
    ),
    # §6.3: from the trend straight into generation, no retyping.
    path(
        "stores/<int:store_id>/trends/ideas/<int:pk>/use/",
        TrendIdeaUseView.as_view(), name="trend-idea-use",
    ),
    path(
        "stores/<int:store_id>/trends/ideas/<int:pk>/dismiss/",
        TrendIdeaDismissView.as_view(), name="trend-idea-dismiss",
    ),
]

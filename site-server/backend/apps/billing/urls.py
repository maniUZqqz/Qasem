from django.urls import path

from .payment_views import (
    PaymentCallbackView,
    PaymentHistoryView,
    PaymentProviderListView,
    PaymentStartView,
)
from .views import (
    PlanListView,
    StoreSubscriptionView,
    StoreUsageHistoryView,
    StoreUsageView,
    UsageQualityView,
)

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="plan-list"),
    path("payment-providers/", PaymentProviderListView.as_view(), name="payment-providers"),
    path("stores/<int:pk>/payments/", PaymentStartView.as_view(), name="payment-start"),
    path("stores/<int:pk>/billing/", PaymentHistoryView.as_view(), name="billing-history"),
    path("payments/callback/", PaymentCallbackView.as_view(), name="payment-callback"),
    path("stores/<int:pk>/usage/", StoreUsageView.as_view(), name="store-usage"),
    path("stores/<int:pk>/usage/history/", StoreUsageHistoryView.as_view(), name="store-usage-history"),
    path(
        "stores/<int:pk>/usage/<int:usage_id>/reject/",
        UsageQualityView.as_view(),
        name="store-usage-reject",
    ),
    path("stores/<int:pk>/subscription/", StoreSubscriptionView.as_view(), name="store-subscription"),
]

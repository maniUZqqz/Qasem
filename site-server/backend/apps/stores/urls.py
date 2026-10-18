from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import StoreViewSet
from .views_automation import StoreContentAutomationView
from .views_connections import StoreConnectionsView
from .views_members import (
    StoreAgentSettingsView,
    StoreMembersView,
    StoreMemberView,
    StoreOnboardingView,
)

router = DefaultRouter()
router.register(r"stores", StoreViewSet, basename="store")

urlpatterns = router.urls + [
    path("stores/<int:pk>/members/", StoreMembersView.as_view(), name="store-members"),
    path(
        "stores/<int:pk>/members/<int:member_id>/",
        StoreMemberView.as_view(),
        name="store-member",
    ),
    path(
        "stores/<int:pk>/agent-settings/",
        StoreAgentSettingsView.as_view(),
        name="store-agent-settings",
    ),
    path(
        "stores/<int:pk>/onboarding/",
        StoreOnboardingView.as_view(),
        name="store-onboarding",
    ),
    # صفحه ۳ — اتصال شبکه‌های اجتماعی.
    path(
        "stores/<int:pk>/connections/",
        StoreConnectionsView.as_view(),
        name="store-connections",
    ),
    # صفحه ۴ — تولید محتوا: اتوماسیون و زمان‌بندی.
    path(
        "stores/<int:pk>/content-automation/",
        StoreContentAutomationView.as_view(),
        name="store-content-automation",
    ),
]

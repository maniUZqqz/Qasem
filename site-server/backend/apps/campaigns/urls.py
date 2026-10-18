from django.urls import path
from rest_framework.routers import DefaultRouter

from .views_board import CampaignBoardView, CampaignTaskView
from .views import (
    CampaignScheduleView,
    CampaignViewSet,
    PerformanceView,
    ScheduledPublishesView,
)

router = DefaultRouter()
router.register(r"campaigns", CampaignViewSet, basename="campaign")

urlpatterns = router.urls + [
    # ---- scheduling (phase 24) -------------------------------------------
    path(
        "campaigns/<int:pk>/schedule/",
        CampaignScheduleView.as_view(), name="campaign-schedule",
    ),
    path(
        "stores/<int:store_id>/scheduled/",
        ScheduledPublishesView.as_view(), name="store-scheduled",
    ),
    # ---- what actually happened (phase 25) -------------------------------
    path(
        "stores/<int:store_id>/performance/",
        PerformanceView.as_view(), name="store-performance",
    ),
    # ---- campaign as a task manager (§29.1) ------------------------------
    path(
        "campaigns/<int:pk>/board/",
        CampaignBoardView.as_view(), name="campaign-board",
    ),
    path(
        "campaigns/<int:pk>/board/<int:task_id>/",
        CampaignTaskView.as_view(), name="campaign-task",
    ),
]

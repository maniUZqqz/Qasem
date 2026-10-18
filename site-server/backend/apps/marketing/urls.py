from django.urls import path

from .event_views import EventIngestView
from .views import LeadCreateView
from .views_gtm import (
    AttributionView,
    CRMView,
    CodeCheckView,
    MarketingReportView,
    MyReferralView,
    RewardListView,
)

urlpatterns = [
    path("leads/", LeadCreateView.as_view(), name="lead-create"),
    path("events/", EventIngestView.as_view(), name="event-ingest"),

    # ---- GTM (phase 26) --------------------------------------------------
    # Public: the code is typed before the account exists.
    path("codes/check/", CodeCheckView.as_view(), name="code-check"),
    path(
        "stores/<int:store_id>/referral/",
        MyReferralView.as_view(), name="store-referral",
    ),
    path(
        "stores/<int:store_id>/attribution/",
        AttributionView.as_view(), name="store-attribution",
    ),
    # Staff: these span every customer, so they are ours, not any one shop's.
    path("marketing/report/", MarketingReportView.as_view(), name="marketing-report"),
    path("marketing/rewards/", RewardListView.as_view(), name="marketing-rewards"),
    # Lead → Customer → Onboarding → Support → Retention, as one read.
    path("marketing/crm/", CRMView.as_view(), name="marketing-crm"),
]

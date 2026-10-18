from django.urls import path

from .views import StoreAnalyticsView, StoreSalesView, StoreTimeseriesView

urlpatterns = [
    path("stores/<int:store_id>/analytics/", StoreAnalyticsView.as_view(), name="store-analytics"),
    path(
        "stores/<int:store_id>/analytics/timeseries/",
        StoreTimeseriesView.as_view(),
        name="store-analytics-timeseries",
    ),
    path(
        "stores/<int:store_id>/analytics/sales/",
        StoreSalesView.as_view(),
        name="store-analytics-sales",
    ),
]

from django.urls import path

from . import views as v

urlpatterns = [
    path("overview/", v.OverviewView.as_view(), name="egress-overview"),
    path("proxies/", v.ProxyListView.as_view(), name="egress-proxies"),
    path("proxies/test/", v.ProxyTestView.as_view(), name="egress-proxy-test"),
    path("proxies/<int:pk>/", v.ProxyDetailView.as_view(), name="egress-proxy"),
    path("proxies/<int:pk>/test/", v.ProxyTestView.as_view(), name="egress-proxy-test-saved"),
    path("routes/", v.RoutesView.as_view(), name="egress-routes"),
    path("switch/", v.SwitchView.as_view(), name="egress-switch"),
    path("services/<str:key>/test/", v.ServiceTestView.as_view(), name="egress-service-test"),
    path("check-routed/", v.CheckRoutedView.as_view(), name="egress-check-routed"),
    path("test-direct/", v.DirectTestView.as_view(), name="egress-test-direct"),
    path("node/", v.node_proxy, name="egress-node"),
]

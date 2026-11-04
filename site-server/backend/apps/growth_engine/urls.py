"""All Growth Engine endpoints, mounted at ``/api/v1/growth/`` (config/urls.py).

Each module owns its urls; this file only assembles them. The always-present modules are listed
statically; optional ones (extraction, compliance, outreach, knowledge) are included only when the module is
installed, so a module can be added or removed in INSTALLED_APPS without touching this file.
"""
from django.apps import apps
from django.urls import include, path

from . import meta

urlpatterns = [
    path("meta/", meta.MetaView.as_view(), name="growth-meta"),
    path("", include("apps.growth_engine.analytics.urls")),
    path("", include("apps.growth_engine.leads.urls")),
    path("discovery/", include("apps.growth_engine.discovery.urls")),
]

for _module in ("extraction", "compliance", "outreach", "knowledge"):
    if apps.is_installed(f"apps.growth_engine.{_module}"):
        urlpatterns.append(path("", include(f"apps.growth_engine.{_module}.urls")))

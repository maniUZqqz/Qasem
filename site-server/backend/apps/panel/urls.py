from django.urls import path

from . import api, api_domain

urlpatterns = [
    path("flags/", api.flags, name="panel-flags"),
    # «دامنه و SSL» (فقط کارکنان، فقط خواندنی): وضعیت + سنجشِ DNS
    path("domain/", api_domain.domain_state, name="panel-domain"),
    path("domain/check/", api_domain.domain_check, name="panel-domain-check"),
]

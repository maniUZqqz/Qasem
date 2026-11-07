# -*- coding: utf-8 -*-
"""مسیرهای نسخه — در config/urls.py زیرِ `api/v1/` سوار می‌شوند."""
from django.urls import path

from .version_views import ChangelogView, VersionView

urlpatterns = [
    path("version/", VersionView.as_view(), name="nm-version"),
    path("version/changelog/", ChangelogView.as_view(), name="nm-version-changelog"),
]

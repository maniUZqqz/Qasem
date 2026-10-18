from django.urls import path

from . import api

urlpatterns = [path("flags/", api.flags, name="panel-flags")]

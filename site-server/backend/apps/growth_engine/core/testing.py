"""Test helpers shared by every Growth Engine test module."""
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


class NoNetworkMixin:
    """Fails the test if anything opens a real network connection (nothing may leave the machine)."""

    def setUp(self):  # noqa: N802
        super().setUp()
        patcher = mock.patch("socket.socket.connect", side_effect=AssertionError("a test tried to open a network connection"))
        patcher.start()
        self.addCleanup(patcher.stop)


def make_staff(username="ge-staff", **extra):
    return get_user_model().objects.create_user(username, f"{username}@example.com", "pw", is_staff=True, **extra)


def make_plain_user(username="ge-user"):
    return get_user_model().objects.create_user(username, f"{username}@example.com", "pw")


def client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


class TempMediaMixin:
    """Uploads go to a throw-away MEDIA_ROOT that is deleted after each test."""

    def setUp(self):  # noqa: N802
        import shutil
        import tempfile

        from django.test import override_settings

        super().setUp()
        tmp = tempfile.mkdtemp(prefix="ge-test-media-")
        override = override_settings(MEDIA_ROOT=tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

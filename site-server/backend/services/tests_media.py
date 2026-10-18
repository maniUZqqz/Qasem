"""Media that lives somewhere other than this disk. Phase 18.

Every `.path` in the pipeline worked perfectly until somebody set
`MEDIA_STORAGE=s3`, and then raised `NotImplementedError`. That is the failure
class these tests exist for: code that is correct on one machine and wrong on
two, where nothing fails until the day you deploy.

The remote side is simulated rather than run against a real bucket — there is
no MinIO here — but the simulation is exact in the one way that matters: it
raises `NotImplementedError` from `.path`, the way every non-filesystem Django
storage does. That is the line the old code tripped on.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from apps.products.models import Product, ProductImage
from apps.stores.models import Store
from services.content import trust
from services.media import files as media

TEMP_MEDIA = tempfile.mkdtemp()


def png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


class LocalTests(SimpleTestCase):
    """The common path has to stay free."""

    def test_reading_a_local_file_makes_no_copy(self):
        """On one machine the alternative is duplicating a 200 MB render for
        every QC pass."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video")
            original = Path(handle.name)

        class LocalField:
            name = original.name

            @property
            def path(self):
                return str(original)

            def __bool__(self):
                return True

        with media.reading(LocalField()) as path:
            self.assertEqual(Path(path), original)
        # Still there: we handed back the file itself, not a copy to delete.
        self.assertTrue(original.exists())
        original.unlink()

    def test_an_empty_field_is_refused_rather_than_returning_a_bad_path(self):
        class Empty:
            def __bool__(self):
                return False

        with self.assertRaises(ValueError):
            with media.reading(Empty()):
                pass


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class RemoteTests(TestCase):
    """What happens when storage is not this filesystem."""

    def setUp(self):
        owner = User.objects.create_user("media-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه فایل")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )
        self.image = ProductImage.objects.create(
            product=self.product,
            image=SimpleUploadedFile("real.png", png(), "image/png"),
            is_main=True,
        )

    def _remote(self):
        """Patch `.path` to raise, the way every non-filesystem storage does."""
        def explode(self):
            raise NotImplementedError(
                "This backend doesn't support absolute paths."
            )

        return patch(
            "django.db.models.fields.files.FieldFile.path",
            property(explode),
        )

    def test_reading_a_remote_file_downloads_it(self):
        with patch.object(media, "is_shared", return_value=True), self._remote():
            with media.reading(self.image.image) as path:
                local = Path(path)
                self.assertTrue(local.exists())
                self.assertEqual(local.read_bytes(), png())
        self.assertFalse(local.exists())  # cleaned up on the way out

    def test_the_temp_file_keeps_the_original_extension(self):
        """ffmpeg and Pillow both decide what to do by looking at it."""
        with patch.object(media, "is_shared", return_value=True), self._remote():
            with media.reading(self.image.image) as path:
                self.assertEqual(Path(path).suffix, ".png")

    def test_several_files_are_cleaned_up_together(self):
        second = ProductImage.objects.create(
            product=self.product,
            image=SimpleUploadedFile("other.png", png(), "image/png"),
        )
        with patch.object(media, "is_shared", return_value=True), self._remote():
            with media.reading_all([self.image.image, second.image]) as paths:
                opened = [Path(p) for p in paths]
                self.assertTrue(all(p.exists() for p in opened))
        self.assertFalse(any(p.exists() for p in opened))

    def test_the_real_photo_is_still_found_on_remote_storage(self):
        """The bug this whole module exists to prevent. `.path` raises on S3,
        the old `except` swallowed it, and a shop with a perfectly good photo
        was told they had none — a silent "no" from the one feature that must
        never give one by accident."""
        with patch.object(media, "is_shared", return_value=True), self._remote():
            with trust.open_real_photo(self.store, self.product) as photo:
                self.assertEqual(photo.kind, "product")
                self.assertTrue(Path(photo.path).exists())

    def test_the_real_photo_never_leaks_a_server_path_to_the_panel(self):
        answer = trust.available(self.store, self.product)
        self.assertTrue(answer["available"])
        self.assertNotIn("path", answer["photo"])

    def test_a_row_pointing_at_a_missing_file_is_still_a_no(self):
        Path(self.image.image.path).unlink()
        with self.assertRaises(trust.NoRealPhoto):
            trust.choose(self.store, self.product)


class SettingsGuardTests(SimpleTestCase):
    """The guard that stops a silent, expensive mistake."""

    def test_local_is_the_default(self):
        from django.conf import settings

        self.assertEqual(settings.MEDIA_STORAGE, "local")
        self.assertFalse(settings.MEDIA_IS_SHARED)

    def test_the_helper_agrees_with_the_setting(self):
        self.assertFalse(media.is_shared())

    def test_media_rel_produces_forward_slashes(self):
        """FileField names are URL paths, and a Windows backslash in one gives
        a 404 that only happens in production."""
        from django.conf import settings

        made = media.media_rel(Path(settings.MEDIA_ROOT) / "a" / "b.mp4")
        self.assertEqual(made, "a/b.mp4")
        self.assertNotIn("\\", made)

"""The real photo at the end. §26.

Almost every test here is about one refusal: **a generated image may never be
used as the real one.** That is the whole feature. A viewer's belief that this
last frame was not made up is what §26 is buying, and the first time we quietly
substitute an AI image for a missing photo, the feature has become the opposite
of itself — so the code refuses and asks for an upload instead.
"""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.content.models import GeneratedImage
from apps.products.models import Product, ProductImage
from apps.stores.models import Store
from services.content import trust

TEMP_MEDIA = tempfile.mkdtemp()


def png() -> bytes:
    """The smallest valid PNG, so ImageField accepts it."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ChoosingTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("trust-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه اعتماد")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )

    def _owner_photo(self, caption="مهدی، صاحب فروشگاه"):
        profile = self.store.profile
        profile.owner_photo = SimpleUploadedFile("me.png", png(), "image/png")
        profile.owner_caption = caption
        profile.save()

    def _product_photo(self, **kwargs):
        return ProductImage.objects.create(
            product=self.product,
            image=SimpleUploadedFile("real.png", png(), "image/png"),
            **kwargs,
        )

    def test_the_owners_photo_is_used_when_there_is_one(self):
        self._owner_photo()
        photo = trust.choose(self.store, self.product)
        self.assertEqual(photo.kind, "owner")
        self.assertEqual(photo.caption, "مهدی، صاحب فروشگاه")

    def test_the_products_real_photo_is_the_fallback(self):
        self._product_photo(is_main=True)
        self.assertEqual(trust.choose(self.store, self.product).kind, "product")

    def test_the_shop_can_ask_for_the_product_instead(self):
        self._owner_photo()
        self._product_photo(is_main=True)
        self.assertEqual(
            trust.choose(self.store, self.product, prefer="product").kind, "product",
        )

    def test_the_main_photo_wins_over_the_others(self):
        self._product_photo(order=1)
        main = self._product_photo(is_main=True, order=9)
        chosen = trust.choose(self.store, self.product)
        self.assertEqual(Path(chosen.path).name, Path(main.image.path).name)

    def test_nothing_uploaded_is_refused_with_instructions(self):
        """Not a stock image, not the logo, not a generated stand-in."""
        with self.assertRaises(trust.NoRealPhoto) as caught:
            trust.choose(self.store, self.product)
        self.assertIn("عکس واقعی", str(caught.exception))

    def test_a_generated_image_is_never_used_as_the_real_one(self):
        """The refusal this whole module exists for. A shop with fifty
        beautiful generated images and no uploaded one still gets a "no"."""
        GeneratedImage.objects.create(
            store=self.store, product=self.product,
            kind=GeneratedImage.Kind.PRODUCT_SHOT,
            image=SimpleUploadedFile("ai.png", png(), "image/png"),
        )
        with self.assertRaises(trust.NoRealPhoto):
            trust.choose(self.store, self.product)

    def test_an_enhanced_image_is_not_real_either(self):
        """It started from the shop's own photo, which makes it the most
        tempting substitute and exactly the wrong one: a model still touched
        every pixel."""
        GeneratedImage.objects.create(
            store=self.store, product=self.product,
            kind=GeneratedImage.Kind.ENHANCED,
            image=SimpleUploadedFile("enh.png", png(), "image/png"),
        )
        with self.assertRaises(trust.NoRealPhoto):
            trust.choose(self.store, self.product)

    def test_a_missing_file_on_disk_is_not_offered(self):
        """A row pointing at a file that is gone would fail mid-render, after
        the shop has already waited."""
        self._owner_photo()
        Path(self.store.profile.owner_photo.path).unlink()
        with self.assertRaises(trust.NoRealPhoto):
            trust.choose(self.store, self.product)

    def test_the_caption_falls_back_to_the_shop_name(self):
        self._owner_photo(caption="")
        self.assertEqual(trust.choose(self.store).caption, "فروشگاه اعتماد")

    def test_availability_answers_without_raising(self):
        """The panel asks before showing the button, so a shop sees the ask for
        a photo instead of a button that fails when pressed."""
        answer = trust.available(self.store, self.product)
        self.assertFalse(answer["available"])
        self.assertTrue(answer["reason"])

        self._owner_photo()
        self.assertTrue(trust.available(self.store, self.product)["available"])

"""One shoot, every platform — and what Advanced mode asks for first.

Both of these exist to avoid spending the GPU: repurposing crops a file that
already exists instead of re-rendering it, and readiness asks for the missing
photo *before* forty minutes of video is made from a product with one angle.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from apps.products.models import Product
from apps.stores.models import Store
from services.content import readiness
from services.video import repurpose


class FormatTests(TestCase):
    def test_every_format_names_where_it_gets_posted(self):
        """A list of aspect ratios is a spec sheet; a list of places is a
        decision the shop owner can make."""
        for fmt in repurpose.FORMATS:
            self.assertTrue(fmt.where, fmt.key)

    def test_a_story_is_capped_and_a_wide_cut_is_not(self):
        self.assertEqual(repurpose.FORMATS_BY_KEY["story"].max_seconds, 15)
        self.assertIsNone(repurpose.FORMATS_BY_KEY["wide"].max_seconds)

    def test_a_long_source_is_marked_as_trimming(self):
        """The owner is about to post it and needs to know the end is missing."""
        rows = {r["key"]: r for r in repurpose.available_formats(source_seconds=60)}
        self.assertTrue(rows["story"]["trims"])
        self.assertFalse(rows["wide"]["trims"])

    def test_a_short_source_trims_nothing(self):
        rows = {r["key"]: r for r in repurpose.available_formats(source_seconds=10)}
        self.assertFalse(rows["story"]["trims"])

    def test_an_unknown_duration_still_lists_the_formats(self):
        self.assertEqual(len(repurpose.available_formats(None)), len(repurpose.FORMATS))

    def test_the_crop_keeps_dimensions_even(self):
        """An odd dimension fails the h264 encode with a message that says
        nothing about aspect ratios."""
        for fmt in repurpose.FORMATS:
            self.assertIn("trunc(iw/2)*2", repurpose.crop_filter(fmt.ratio))

    def test_the_crop_is_centred_not_guessed(self):
        """Smarter framing needs subject detection, and a wrong guess crops the
        product out of its own advert."""
        expression = repurpose.crop_filter((9, 16))
        self.assertIn("crop=", expression)
        self.assertNotIn("detect", expression)


class ReadinessTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("ready-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه آماده‌سازی")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )

    def _keys(self, kind):
        return [r.key for r in readiness.check(self.product, kind)]

    def test_video_without_a_photo_is_blocked(self):
        """The one genuinely blocking requirement: video is built from an
        image, and without one the model invents a product."""
        summary = readiness.summary(self.product, readiness.VIDEO)
        self.assertFalse(summary["ready"])
        self.assertEqual(summary["blocking"][0]["key"], "product_image")

    def test_a_caption_is_never_blocked(self):
        """A requirement that blocks everything turns an assistant into a
        gatekeeper."""
        summary = readiness.summary(self.product, readiness.CAPTION)
        self.assertTrue(summary["ready"])

    def test_a_short_description_is_a_warning_not_a_wall(self):
        summary = readiness.summary(self.product, readiness.CAPTION)
        keys = [r["key"] for r in summary["improvements"]]
        self.assertIn("description", keys)

    def test_a_real_description_removes_the_warning(self):
        self.product.description = (
            "کفش چرم دست‌دوز با زیره‌ی طبیعی، مناسب استفاده‌ی روزمره و رسمی."
        )
        self.product.save()
        self.assertNotIn("description", self._keys(readiness.CAPTION))

    def test_every_requirement_explains_why_this_output_needs_it(self):
        """"Upload a photo" is a demand. "Video is built from an image, and
        without one the model invents a product" is an answer."""
        for kind in (readiness.VIDEO, readiness.POSTER, readiness.CAPTION):
            for requirement in readiness.check(self.product, kind):
                self.assertTrue(requirement.why.strip(), f"{kind}/{requirement.key}")
                self.assertGreater(len(requirement.why), 25)

    def test_a_reference_video_is_offered_not_demanded(self):
        offered = [
            r for r in readiness.check(self.product, readiness.VIDEO)
            if r.key == "reference"
        ]
        self.assertTrue(offered)
        self.assertFalse(offered[0].blocking)

    def test_a_fully_prepared_product_has_nothing_to_ask(self):
        """Advanced mode is worth using when there is something to answer, and
        pointless when there is not."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.ai.models import ProductIntelligence
        from apps.products.models import ProductImage

        self.product.description = (
            "کفش چرم دست‌دوز با زیره‌ی طبیعی، مناسب استفاده‌ی روزمره و رسمی."
        )
        self.product.save()
        for index in range(3):
            ProductImage.objects.create(
                product=self.product,
                image=SimpleUploadedFile(f"p{index}.jpg", b"x", content_type="image/jpeg"),
            )
        ProductIntelligence.objects.create(product=self.product)
        self.store.profile.tone = "دوستانه"
        self.store.profile.save()
        self.product.refresh_from_db()

        summary = readiness.summary(self.product, readiness.POSTER)
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["improvements"], [])
        self.assertFalse(summary["advanced_worth_it"])


class ReadinessAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("ready-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه API")
        self.product = Product.objects.create(store=self.store, name="کفش", price=1)
        self.client.force_login(self.owner)

    def test_it_answers_per_output_kind(self):
        video = self.client.get(
            f"/api/v1/products/{self.product.pk}/readiness/?kind=VIDEO"
        ).json()
        caption = self.client.get(
            f"/api/v1/products/{self.product.pk}/readiness/?kind=CAPTION"
        ).json()

        self.assertFalse(video["ready"])
        self.assertTrue(caption["ready"])

    def test_an_unknown_kind_is_refused(self):
        response = self.client.get(
            f"/api/v1/products/{self.product.pk}/readiness/?kind=HOLOGRAM"
        )
        self.assertEqual(response.status_code, 400)

    def test_another_users_product_is_invisible(self):
        stranger = User.objects.create_user("ready-stranger", password="x")
        self.client.force_login(stranger)
        response = self.client.get(f"/api/v1/products/{self.product.pk}/readiness/")
        self.assertEqual(response.status_code, 404)


class CutsAPITests(TestCase):
    def setUp(self):
        from apps.content.models import VideoScript

        self.owner = User.objects.create_user("cuts-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه برش")
        product = Product.objects.create(store=self.store, name="کفش", price=1)
        self.script = VideoScript.objects.create(store=self.store, product=product)
        self.client.force_login(self.owner)
        self.url = f"/api/v1/video-scripts/{self.script.pk}/cuts/"

    def test_listing_says_the_video_is_not_ready_yet(self):
        body = self.client.get(self.url).json()
        self.assertFalse(body["ready"])
        self.assertEqual(body["cuts"], [])
        # The formats are still listed so the panel can show what will be made.
        self.assertTrue(body["available"])

    def test_cutting_before_there_is_a_video_is_refused_clearly(self):
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "no_video")

    def test_a_stranger_gets_404(self):
        stranger = User.objects.create_user("cuts-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

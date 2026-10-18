import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from apps.stores.models import Store

from .models import Product

TEMP_MEDIA = tempfile.mkdtemp(prefix="upmarket-test-media-")


def make_test_image(name="test.png"):
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(200, 30, 30)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ProductAPITests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="Str0ngPass!x")
        self.bob = User.objects.create_user("bob", password="Str0ngPass!x")
        self.alice_store = Store.objects.create(owner=self.alice, name="Alice Shop")
        self.bob_store = Store.objects.create(owner=self.bob, name="Bob Shop")
        self.client.force_authenticate(user=self.alice)

    def test_create_product_in_own_store(self):
        resp = self.client.post(
            "/api/v1/products/",
            {
                "store": self.alice_store.id,
                "name": "کفش اسپرت مردانه",
                "description": "کفش سبک مناسب دویدن شهری",
                "price": "1250000",
                "stock_quantity": 12,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        product = Product.objects.get(id=resp.data["id"])
        self.assertEqual(product.store, self.alice_store)
        self.assertTrue(product.slug)

    def test_cannot_create_product_in_foreign_store(self):
        resp = self.client.post(
            "/api/v1/products/",
            {"store": self.bob_store.id, "name": "hack", "price": "1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_product_list_is_tenant_scoped(self):
        Product.objects.create(store=self.alice_store, name="A1")
        Product.objects.create(store=self.bob_store, name="B1")
        resp = self.client.get("/api/v1/products/")
        names = [p["name"] for p in resp.data["results"]]
        self.assertEqual(names, ["A1"])

    def test_image_upload_and_delete(self):
        product = Product.objects.create(store=self.alice_store, name="A1")
        resp = self.client.post(
            f"/api/v1/products/{product.id}/images/",
            {"image": make_test_image(), "is_main": "true", "alt_text": "نمای اصلی"},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        image_id = resp.data["id"]
        self.assertEqual(product.images.count(), 1)

        resp = self.client.delete(f"/api/v1/products/{product.id}/images/{image_id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(product.images.count(), 0)

    def test_attributes_and_variants(self):
        product = Product.objects.create(store=self.alice_store, name="A1")
        resp = self.client.post(
            f"/api/v1/products/{product.id}/attributes/", {"key": "رنگ", "value": "مشکی"}
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.client.post(
            f"/api/v1/products/{product.id}/variants/",
            {"name": "سایز ۴۲", "stock_quantity": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        detail = self.client.get(f"/api/v1/products/{product.id}/")
        self.assertEqual(len(detail.data["attributes"]), 1)
        self.assertEqual(len(detail.data["variants"]), 1)

    def test_foreign_product_not_visible(self):
        foreign = Product.objects.create(store=self.bob_store, name="B1")
        resp = self.client.get(f"/api/v1/products/{foreign.id}/")
        self.assertEqual(resp.status_code, 404)

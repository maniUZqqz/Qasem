from django.contrib.auth.models import User
from django.http import Http404
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from . import api_errors


class StockTextTests(SimpleTestCase):
    def test_the_stock_english_404_texts_are_matched(self):
        for text in ["No AudioAsset matches the given query.", "Not found.", "No Product matches the given query"]:
            self.assertTrue(api_errors._STOCK_404.match(text), text)

    def test_a_views_own_persian_text_is_not_touched(self):
        self.assertFalse(api_errors._STOCK_404.match("فایلِ این صدا آماده نیست."))


class MissingAssetApiTests(TestCase):
    def test_a_missing_audio_take_says_so_in_persian(self):
        from apps.stores.models import Store

        owner = User.objects.create_user("err-owner", password="x")
        store = Store.objects.create(owner=owner, name="فروشگاه")
        api = APIClient()
        api.force_authenticate(owner)
        r = api.post(f"/api/v1/stores/{store.pk}/audio/assets/99999/retry/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["detail"], api_errors.NOT_FOUND_FA)
        self.assertEqual(r.data["error"]["code"], "not_found")
        self.assertNotIn("matches the given query", str(r.data))

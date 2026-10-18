"""The music endpoints: who may use them, and what a shop is told. §7

The service layer is tested in `services/tests_library.py` — that the licence
filtering works. These test the part the shop actually touches, where two
things have to hold:

**A shop can only reach their own store's videos.** Ordinary REST scoping, but
worth pinning here: the picker takes a `script_id`, and a view that trusted it
would let anyone attach music to anyone else's video.

**The obligation is carried, not merely displayed.** A CC-BY track needs a
credit line. It is shown in the picker, stored beside the file, and handed back
where the video is produced — because a credit a shop cannot find at the moment
they publish is a credit that never gets pasted.
"""
import pathlib
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.products.models import Product
from apps.stores.models import Store
from services.audio import library

from .models import VideoScript

TRACK = {
    "id": "t1",
    "title": "آرام",
    "creator": "کسی",
    "seconds": 90.0,
    "url": "https://example.com/a.mp3",
    "page": "https://example.com/a",
    "licence": "by",
    "licence_name": "CC-BY",
    "attribution": "by کسی — CC BY 4.0",
    "needs_credit": True,
    "source": "jamendo",
}


def _wrote(url, out):
    """A download that succeeds, without a network."""
    pathlib.Path(out).write_bytes(b"x" * 32)
    return pathlib.Path(out)


class MusicLibraryAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("music-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )
        self.script = VideoScript.objects.create(
            store=self.store, product=self.product, concept="تیزر",
        )
        self.client.force_login(self.owner)

    def _found(self):
        return patch.object(library, "search", return_value={
            "tracks": [TRACK], "total": 1, "page": 1, "note": "…",
        })

    # ------------------------------------------------------------ search

    def test_a_shop_can_search_the_library(self):
        with self._found():
            body = self.client.get(
                f"/api/v1/stores/{self.store.pk}/music-library/?q=آرام",
            ).json()
        self.assertEqual(len(body["tracks"]), 1)

    def test_the_response_says_where_the_music_comes_from(self):
        with self._found():
            body = self.client.get(
                f"/api/v1/stores/{self.store.pk}/music-library/",
            ).json()
        self.assertEqual(body["about"]["source"], "Openverse")
        self.assertIn("NC", body["about"]["excluded"])

    def test_a_dead_library_is_503_not_an_empty_list(self):
        """"Nothing matched" and "we could not look" send a shop in opposite
        directions, and an empty list says the first."""
        with patch.object(
            library, "search",
            side_effect=library.LibraryUnavailable("در دسترس نیست"),
        ):
            response = self.client.get(
                f"/api/v1/stores/{self.store.pk}/music-library/",
            )
        self.assertEqual(response.status_code, 503)

    def test_a_rubbish_page_number_is_refused(self):
        response = self.client.get(
            f"/api/v1/stores/{self.store.pk}/music-library/?page=abc",
        )
        self.assertEqual(response.status_code, 400)

    def test_another_shop_cannot_search_through_this_store(self):
        other = User.objects.create_user("outsider", password="x")
        self.client.force_login(other)
        response = self.client.get(
            f"/api/v1/stores/{self.store.pk}/music-library/",
        )
        self.assertIn(response.status_code, (403, 404))

    def test_logging_out_closes_the_library(self):
        self.client.logout()
        response = self.client.get(
            f"/api/v1/stores/{self.store.pk}/music-library/",
        )
        self.assertIn(response.status_code, (401, 403))

    # ------------------------------------------------------------- take

    def _take(self, **overrides):
        payload = {
            "script_id": self.script.pk,
            "url": TRACK["url"],
            "licence": TRACK["licence"],
            "attribution": TRACK["attribution"],
        }
        payload.update(overrides)
        return self.client.post(
            f"/api/v1/stores/{self.store.pk}/music-library/",
            payload, content_type="application/json",
        )

    def test_taking_a_track_stores_the_credit_line_with_the_file(self):
        """A credit in a different table is one nobody pastes into the post."""
        with patch.object(library, "fetch", side_effect=_wrote):
            response = self._take()
        self.assertEqual(response.status_code, 201)
        self.script.refresh_from_db()
        self.assertIn("CC BY", self.script.music_attribution)
        self.assertEqual(self.script.music_licence, "by")

    def test_a_track_that_will_not_download_leaves_the_video_alone(self):
        with patch.object(
            library, "fetch",
            side_effect=library.LibraryUnavailable("برداشته شده است"),
        ):
            response = self._take()
        self.assertEqual(response.status_code, 502)
        self.script.refresh_from_db()
        self.assertFalse(self.script.music)

    def test_a_url_that_is_not_a_url_is_refused(self):
        self.assertEqual(self._take(url="javascript:alert(1)").status_code, 400)

    def test_a_missing_url_is_refused(self):
        self.assertEqual(self._take(url="").status_code, 400)

    def test_a_video_belonging_to_someone_else_is_not_found(self):
        """The picker takes a script_id, and a view that trusted it would let
        anyone attach music to anyone else's video."""
        stranger = User.objects.create_user("stranger", password="x")
        other_store = Store.objects.create(owner=stranger, name="دیگری")
        other_product = Product.objects.create(
            store=other_store, name="چیزی", price=1,
        )
        theirs = VideoScript.objects.create(
            store=other_store, product=other_product, concept="x",
        )
        self.assertEqual(self._take(script_id=theirs.pk).status_code, 404)


class MusicStateTests(TestCase):
    """What the video's own music panel reports back."""

    def setUp(self):
        self.owner = User.objects.create_user("music-state", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )
        self.script = VideoScript.objects.create(
            store=self.store, product=self.product, concept="تیزر",
            music_licence="by", music_attribution="by کسی — CC BY 4.0",
        )
        self.client.force_login(self.owner)

    def _body(self):
        return self.client.get(
            f"/api/v1/stores/{self.store.pk}"
            f"/video-scripts/{self.script.pk}/music/",
        ).json()

    def test_the_credit_line_comes_back_where_the_video_is_made(self):
        body = self._body()
        self.assertTrue(body["needs_credit"])
        self.assertIn("CC BY", body["attribution"])

    def test_a_cc0_track_needs_no_credit(self):
        self.script.music_licence = "cc0"
        self.script.music_attribution = ""
        self.script.save()
        self.assertFalse(self._body()["needs_credit"])

    def test_the_panel_is_told_we_do_not_ship_music(self):
        """Above the upload button, not in terms nobody reads — the strike
        lands on the shop's own account, weeks later."""
        self.assertIn("کپی‌رایت", self._body()["licence"])

    def test_the_loudness_ceiling_is_published_not_just_enforced(self):
        """A shop should be able to see the limit before they hit it."""
        from services.audio import music

        self.assertEqual(self._body()["ceiling_db"], music.MUSIC_CEILING)

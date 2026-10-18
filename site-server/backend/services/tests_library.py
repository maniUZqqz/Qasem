"""Free music, and the filtering that makes it safe to offer. §7

One property carries this file: **a track a shop may not use is never shown.**
Not shown with a warning, not shown greyed out — filtered out in the service
layer, because a caveat on a download button is a caveat nobody reads, and the
consequence lands weeks later as a copyright strike on the shop's own page.

`NC` is the one that catches people. It means non-commercial, and a shop's
advertising video is the definition of commercial use. Somebody scanning a list
of "free music" will not stop to work that out.
"""
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from services.audio import library


def row(**overrides) -> dict:
    base = {
        "id": "abc",
        "title": "یک آهنگ",
        "creator": "کسی",
        "duration": 60_000,
        "url": "https://example.com/a.mp3",
        "foreign_landing_url": "https://example.com/a",
        "license": "by",
        "attribution": '"یک آهنگ" by کسی is licensed under CC BY 4.0.',
        "source": "jamendo",
    }
    base.update(overrides)
    return base


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def answering(*rows, total=None):
    payload = {"results": list(rows), "result_count": total or len(rows)}
    return patch.object(library.requests, "get", return_value=FakeResponse(payload))


class LicenceTests(SimpleTestCase):
    def test_a_non_commercial_track_is_never_shown(self):
        """A shop's advertising video is the definition of commercial use, and
        somebody scanning a list of "free music" will not work that out."""
        with answering(row(license="by-nc"), row(license="by")):
            tracks = library.search("x")["tracks"]
        self.assertEqual([t["licence"] for t in tracks], ["by"])

    def test_a_no_derivatives_track_is_never_shown(self):
        """Ducking a track under narration is a derivative."""
        with answering(row(license="by-nd")):
            self.assertEqual(library.search("x")["tracks"], [])

    def test_share_alike_is_left_out_on_purpose(self):
        """It would arguably oblige the shop to license their own video under
        the same terms — not a decision a music picker makes for somebody."""
        with answering(row(license="by-sa")):
            self.assertEqual(library.search("x")["tracks"], [])

    def test_the_request_asks_the_api_to_filter_too(self):
        """Belt and braces: the local filter is the guarantee, but asking for
        the wrong thing and then discarding most of it wastes a page of
        results every time."""
        with answering(row()) as get:
            library.search("x")
        sent = get.call_args.kwargs["params"]["license"]
        for allowed in library.USABLE:
            self.assertIn(allowed, sent)

    def test_cc0_needs_no_credit(self):
        with answering(row(license="cc0")):
            track = library.search("x")["tracks"][0]
        self.assertFalse(track["needs_credit"])
        self.assertEqual(track["attribution"], "")

    def test_cc_by_carries_the_exact_wording_the_licence_wants(self):
        """Taken verbatim rather than assembled from parts — the required
        wording is a property of the licence, and our own phrasing is how a
        shop ends up with a credit that does not satisfy it."""
        with answering(row()):
            track = library.search("x")["tracks"][0]
        self.assertTrue(track["needs_credit"])
        self.assertIn("CC BY 4.0", track["attribution"])

    def test_a_by_track_with_no_attribution_still_gets_a_credit_line(self):
        with answering(row(attribution="")):
            track = library.search("x")["tracks"][0]
        self.assertIn("کسی", track["attribution"])


class ResultTests(SimpleTestCase):
    def test_milliseconds_become_seconds(self):
        with answering(row(duration=90_000)):
            self.assertEqual(library.search("x")["tracks"][0]["seconds"], 90.0)

    def test_a_sound_effect_is_not_offered_as_music(self):
        with answering(row(duration=3_000)):
            self.assertEqual(library.search("x")["tracks"], [])

    def test_an_hour_long_set_is_not_offered_either(self):
        with answering(row(duration=4_000_000)):
            self.assertEqual(library.search("x")["tracks"], [])

    def test_a_track_with_no_file_is_skipped(self):
        with answering(row(url=None)):
            self.assertEqual(library.search("x")["tracks"], [])

    def test_a_track_with_no_duration_is_kept(self):
        """Unknown length is not a reason to hide a usable track."""
        with answering(row(duration=None)):
            self.assertEqual(len(library.search("x")["tracks"]), 1)

    def test_an_empty_query_browses_rather_than_failing(self):
        """Most people opening a music picker do not arrive with a search term."""
        with answering(row()) as get:
            library.search("")
        self.assertTrue(get.call_args.kwargs["params"]["q"])

    def test_every_result_set_explains_what_free_means_here(self):
        with answering(row()):
            note = library.search("x")["note"]
        self.assertIn("CC-BY", note)


class FailureTests(SimpleTestCase):
    def test_a_dead_library_says_so_rather_than_returning_nothing(self):
        """"Nothing matched" and "we could not look" send a shop in opposite
        directions."""
        with patch.object(
            library.requests, "get", side_effect=requests.RequestException("down"),
        ):
            with self.assertRaises(library.LibraryUnavailable):
                library.search("x")

    def test_the_failure_points_at_the_way_out(self):
        with patch.object(
            library.requests, "get", side_effect=requests.RequestException("down"),
        ):
            try:
                library.search("x")
            except library.LibraryUnavailable as exc:
                self.assertIn("آپلود", str(exc))

    def test_a_broken_response_body_is_handled(self):
        class Rubbish(FakeResponse):
            def json(self):
                raise ValueError("not json")

        with patch.object(library.requests, "get", return_value=Rubbish({})):
            with self.assertRaises(library.LibraryUnavailable):
                library.search("x")


class DownloadTests(SimpleTestCase):
    class Streaming:
        def __init__(self, kind="audio/mpeg", chunks=(b"x" * 1024,)):
            self.headers = {"content-type": kind}
            self._chunks = chunks

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            return iter(self._chunks)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_an_html_page_is_refused_rather_than_handed_to_ffmpeg(self):
        """A URL returning HTML is a takedown page or a login wall, and ffmpeg
        would report a corrupt file rather than explain."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                library.requests, "get", return_value=self.Streaming("text/html"),
            ):
                with self.assertRaises(library.LibraryUnavailable) as caught:
                    library.fetch("https://x/a", Path(directory) / "a.mp3")
        self.assertIn("برداشته شده", str(caught.exception))

    def test_a_real_audio_response_is_saved(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "a.mp3"
            with patch.object(
                library.requests, "get", return_value=self.Streaming(),
            ):
                library.fetch("https://x/a", target)
            self.assertTrue(target.exists())
            self.assertGreater(target.stat().st_size, 0)

    def test_an_enormous_file_is_refused_mid_download(self):
        """Checked while streaming, not after: the point is not to write 2 GB
        to disk before deciding against it."""
        import tempfile
        from pathlib import Path

        huge = (b"x" * (1 << 20) for _ in range(40))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                library.requests, "get",
                return_value=self.Streaming(chunks=huge),
            ):
                with self.assertRaises(library.LibraryUnavailable):
                    library.fetch("https://x/a", Path(directory) / "a.mp3")


class DisclosureTests(SimpleTestCase):
    def test_the_panel_is_told_which_licences_are_excluded_and_why(self):
        about = library.available()
        self.assertIn("NC", about["excluded"])
        self.assertIn("تجاری", about["excluded"])

    def test_the_source_is_named(self):
        self.assertEqual(library.available()["source"], "Openverse")

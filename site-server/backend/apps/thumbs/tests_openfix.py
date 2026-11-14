"""Thumbnail maker, fixes of the review of 2026-11-13:

* the red/green safe-margin guides are a PREVIEW helper and must never be burned into the downloaded PNG/JPG;
* deleting a thumbnail that still waits for its AI background cancels the queued FLUX job (it would burn GPU time when the node comes back);
* the style sample thumbnails are not throttled like an anonymous API call (a format switch loads ~15 of them);
* the note about an AI background that could not be translated is a clean sentence: no jargon, never cut in the middle of a word.
"""
import hashlib
from unittest import mock

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from apps.compute.models import ComputeJob
from apps.photoedit import translate

from . import aibg, services, views
from .models import Thumbnail
from .tests_aibg import node
from .tests_api import SPEC, ThumbsApiBase


class GuidesStayInThePreviewTests(ThumbsApiBase):
    def png_of(self, item):
        t = Thumbnail.objects.get(pk=item["id"])
        return (self.media / t.files["png"]).read_bytes()

    def test_the_downloaded_file_is_identical_with_and_without_the_guide_checkbox(self):
        on = self.render({**SPEC, "guides": True})["items"][0]
        off = self.render({**SPEC, "guides": False})["items"][0]
        self.assertEqual(hashlib.sha1(self.png_of(on)).hexdigest(), hashlib.sha1(self.png_of(off)).hexdigest(),
                         "the guide lines were burned into the final PNG")

    def test_the_preview_still_shows_the_guides(self):
        a = self.api.post(f"{self.base}/preview/", {"spec": {**SPEC, "guides": True}}, format="json")
        b = self.api.post(f"{self.base}/preview/", {"spec": {**SPEC, "guides": False}}, format="json")
        self.assertEqual((a.status_code, b.status_code), (200, 200), (a.content, b.content))
        self.assertNotEqual(a.json()["image"], b.json()["image"], "the checkbox does nothing in the preview")


class DeleteWaitingThumbnailTests(ThumbsApiBase):
    def test_deleting_a_waiting_thumbnail_cancels_its_queued_job(self):
        node(online=False)
        item = self.render({**SPEC, "background": {"kind": "ai"}}, ai={"preset": "studio_light"})["items"][0]
        self.assertEqual(item["state"], "WAITING_BG")
        job = ComputeJob.objects.get(uid=item["bg_job"])
        self.assertFalse(job.final)
        r = self.api.delete(f"{self.base}/items/{item['id']}/")
        self.assertEqual(r.status_code, 204)
        job.refresh_from_db()
        self.assertTrue(job.final, "the FLUX job stayed queued after the thumbnail was deleted")
        self.assertEqual(job.state, ComputeJob.State.CANCELLED)

    def test_a_failing_cancel_never_blocks_the_delete(self):
        node(online=False)
        item = self.render({**SPEC, "background": {"kind": "ai"}})["items"][0]
        with mock.patch.object(aibg, "cancel", side_effect=RuntimeError("boom")):
            r = self.api.delete(f"{self.base}/items/{item['id']}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Thumbnail.objects.filter(pk=item["id"]).exists())


class SampleThrottleTests(SimpleTestCase):
    def test_the_sample_view_has_its_own_high_ceiling(self):
        self.assertEqual(views.StyleSampleView.throttle_classes, [views.SampleThrottle])
        rate = views.SampleThrottle().rate
        count, period = rate.split("/")
        self.assertGreaterEqual(int(count), 300)                     # 15 samples per format switch, several switches a minute
        self.assertTrue(period.startswith("min"))

    def test_many_samples_in_a_minute_are_not_refused(self):
        """30/min was DRF's anonymous default: the 3rd format switch got HTTP 429 and broken style thumbnails."""
        throttle = views.SampleThrottle()
        self.assertGreater(throttle.num_requests, 100)


class AiBackgroundNoteTests(ThumbsApiBase):
    LONG = ("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — لوکال: سرورِ پردازش خاموش است. API سازگار با OpenAI (پیش‌فرض .env) "
            "و متیس: سیاستِ داده‌ی این فروشگاه اجازه‌ی فرستادنِ این داده به سرویسِ بیرونی (متیس) را نمی‌دهد. " * 3)

    def test_the_note_is_short_clean_and_ends_at_a_word_boundary(self):
        with mock.patch("apps.photoedit.translate.translate", side_effect=translate.Failed(self.LONG)):
            _prompt, info = aibg.resolve_prompt(self.store, text="یک سالنِ ورزشیِ روشن", style="face_text")
        note = info["note"]
        self.assertTrue(note)
        self.assertLessEqual(len(note), 300)
        self.assertNotIn(".env", note)
        self.assertNotIn("OpenAI", note)
        self.assertNotRegex(note, r"[،؛:\-—]\s*$", "cut in the middle of a sentence")
        self.assertTrue(note.rstrip().endswith((".", "…", ")")), note)
        self.assertNotIn("%s", note)

    def test_the_other_failure_path_is_clean_too(self):
        with mock.patch("apps.photoedit.translate.translate", side_effect=ValueError(self.LONG)):
            _prompt, info = aibg.resolve_prompt(self.store, text="یک سالنِ ورزشیِ روشن", style="face_text")
        self.assertLessEqual(len(info["note"]), 300)
        self.assertNotIn(".env", info["note"])

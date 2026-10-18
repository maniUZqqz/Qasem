"""Call recording — صفحه ۷، the half that was held on a legal constraint.

The constraint was consent, and consent is a feature, not a reason to skip the
feature. So most of this file is one rule, checked from every direction:

> **No consent row, no recording.**

It is enforced in `Recording.save`, not in the view, because a rule that lives
in a view is a rule the next caller forgets — the admin, a management command,
a shell session during an incident.

The other held half is not tested here because it is not built: resolving a
stranger's social accounts from their phone number needs platform APIs abused
to work, and it is the mechanism behind doxxing. `match_known_contact` is the
legitimate neighbour, and its tests are the ones that pin it to the shop's own
rows.
"""
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.stores.models import Store

from .calls import CallConsent, Recording, match_known_contact
from .models import Customer
from .outreach import Prospect


#: Every uploaded file in this module goes here, not into the developer's
#: `media/`. Without it, running the suite leaves a pile of `call_*.m4a` in the
#: real media folder — which, since this repo commits its media, would end up
#: in git.
TEMP_MEDIA = tempfile.mkdtemp(prefix="upmarket-calls-test-")


def audio(name="call.m4a"):
    return SimpleUploadedFile(name, b"not-real-audio", content_type="audio/m4a")


class MediaIsolated(TestCase):
    """Base class: uploads land in a temp folder and are removed after."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ConsentGateTests(MediaIsolated):
    def setUp(self):
        owner = User.objects.create_user("call-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")
        self.prospect = Prospect.objects.create(store=self.store, company="شرکت الف")

    def grant(self):
        return CallConsent.objects.create(
            prospect=self.prospect, granted=True,
            obtained_how="اول تماس گفتم ضبط می‌کنم و گفت اشکالی ندارد",
        )

    def test_without_consent_a_recording_cannot_be_saved(self):
        with self.assertRaises(ValidationError):
            Recording.objects.create(
                store=self.store, prospect=self.prospect, audio=audio(),
            )
        self.assertEqual(Recording.objects.count(), 0)

    def test_consent_that_was_not_granted_is_not_consent(self):
        CallConsent.objects.create(
            prospect=self.prospect, granted=False, obtained_how="پرسیدم، گفت نه",
        )
        with self.assertRaises(ValidationError):
            Recording.objects.create(
                store=self.store, prospect=self.prospect, audio=audio(),
            )

    def test_with_consent_it_saves(self):
        self.grant()
        recording = Recording.objects.create(
            store=self.store, prospect=self.prospect, audio=audio(),
        )
        self.assertEqual(recording.status, Recording.Status.STORED)

    def test_revoking_stops_new_recordings_but_keeps_the_old_ones(self):
        consent = self.grant()
        Recording.objects.create(store=self.store, prospect=self.prospect, audio=audio())

        consent.revoked_at = timezone.now()
        consent.save()
        self.assertFalse(consent.is_active)

        with self.assertRaises(ValidationError):
            Recording.objects.create(
                store=self.store, prospect=self.prospect, audio=audio("second.m4a"),
            )
        # The one taken while consent stood is still there — it was lawful when
        # it was made, and deleting it would also delete the evidence of that.
        self.assertEqual(Recording.objects.count(), 1)

    def test_granting_without_saying_how_is_refused(self):
        consent = CallConsent(prospect=self.prospect, granted=True, obtained_how="  ")
        with self.assertRaises(ValidationError):
            consent.clean()

    def test_an_absurdly_long_call_is_refused(self):
        self.grant()
        with self.assertRaises(ValidationError):
            Recording.objects.create(
                store=self.store, prospect=self.prospect, audio=audio(),
                seconds=200 * 60,
            )


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class KnownContactTests(MediaIsolated):
    """The legitimate half of «از روی شماره»: the shop's own rows, nothing else."""

    def setUp(self):
        owner = User.objects.create_user("known-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")

    def test_an_unknown_number_is_simply_unknown(self):
        result = match_known_contact(self.store, "09121234567")
        self.assertFalse(result["known"])
        self.assertEqual(result["matches"], [])

    def test_a_number_we_already_have_is_found(self):
        Customer.objects.create(store=self.store, name="مهدی", phone="09121234567")
        result = match_known_contact(self.store, "09121234567")
        self.assertTrue(result["known"])
        self.assertEqual(result["matches"][0]["name"], "مهدی")

    def test_country_code_and_leading_zero_are_the_same_number(self):
        Customer.objects.create(store=self.store, name="مهدی", phone="09121234567")
        self.assertTrue(match_known_contact(self.store, "+989121234567")["known"])

    def test_another_shops_contacts_are_invisible(self):
        other_owner = User.objects.create_user("known-other", password="x")
        other = Store.objects.create(owner=other_owner, name="دیگری")
        Customer.objects.create(store=other, name="مال دیگری", phone="09121234567")
        self.assertFalse(match_known_contact(self.store, "09121234567")["known"])

    def test_a_too_short_number_matches_nothing(self):
        Customer.objects.create(store=self.store, name="مهدی", phone="09121234567")
        self.assertFalse(match_known_contact(self.store, "123")["known"])


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ApiTests(MediaIsolated):
    def setUp(self):
        self.owner = User.objects.create_user("call-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.prospect = Prospect.objects.create(
            store=self.store, company="شرکت الف", phone="09121234567",
        )
        self.base = f"/api/v1/stores/{self.store.pk}/prospects/{self.prospect.pk}"
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def grant(self):
        return self.client.post(f"{self.base}/consent/", {
            "granted": True, "how": "VERBAL",
            "obtained_how": "سر تماس گفتم و قبول کرد",
        }, format="json")

    def test_uploading_without_consent_is_refused_with_a_reason(self):
        res = self.client.post(
            f"{self.base}/recordings/", {"audio": audio()}, format="multipart",
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("رضایت", res.json()["error"])

    @patch("apps.customers.tasks.analyse_call.delay")
    def test_consent_then_upload_works_and_queues_the_analysis(self, delay):
        self.assertEqual(self.grant().status_code, 200)
        res = self.client.post(
            f"{self.base}/recordings/", {"audio": audio()}, format="multipart",
        )
        self.assertEqual(res.status_code, 201, res.content)
        delay.assert_called_once()

    def test_granting_without_saying_how_is_a_400(self):
        res = self.client.post(f"{self.base}/consent/", {
            "granted": True, "how": "VERBAL", "obtained_how": "   ",
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_the_consent_endpoint_states_the_rule(self):
        body = self.client.get(f"{self.base}/consent/").json()
        self.assertIsNone(body["consent"])
        self.assertIn("ذخیره نمی‌شود", body["rule"])

    def test_revoking_flips_may_record(self):
        self.grant()
        self.assertTrue(self.client.get(f"{self.base}/recordings/").json()["may_record"])
        self.client.delete(f"{self.base}/consent/")
        self.assertFalse(self.client.get(f"{self.base}/recordings/").json()["may_record"])

    def test_call_prep_gathers_what_to_read_before_dialling(self):
        self.prospect.last_outcome = "گفت بودجه ندارد"
        self.prospect.save()
        body = self.client.get(f"{self.base}/prep/").json()
        self.assertEqual(body["prospect"]["company"], "شرکت الف")
        self.assertEqual(body["prospect"]["last_outcome"], "گفت بودجه ندارد")
        self.assertIn("known", body)

    def test_call_prep_carries_previous_objections(self):
        self.grant()
        Recording.objects.create(
            store=self.store, prospect=self.prospect, audio=audio(),
            objections=["گران است"], commitments=["قیمت می‌فرستم"],
            summary="تماس اول", status=Recording.Status.ANALYSED,
        )
        body = self.client.get(f"{self.base}/prep/").json()
        self.assertEqual(body["objections"], ["گران است"])
        self.assertEqual(body["commitments"], ["قیمت می‌فرستم"])
        self.assertEqual(body["last_summary"], "تماس اول")

    def test_another_users_prospect_is_invisible(self):
        stranger = User.objects.create_user("call-stranger", password="x")
        client = APIClient()
        client.force_authenticate(stranger)
        self.assertIn(client.get(f"{self.base}/prep/").status_code, (403, 404))


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class AnalysisTests(MediaIsolated):
    def setUp(self):
        owner = User.objects.create_user("analysis-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")
        self.prospect = Prospect.objects.create(store=self.store, company="شرکت")
        CallConsent.objects.create(
            prospect=self.prospect, granted=True, obtained_how="گفت باشد",
        )
        self.recording = Recording.objects.create(
            store=self.store, prospect=self.prospect, audio=audio(),
        )

    @patch("services.research.call_analysis.transcribe")
    def test_a_missing_whisper_marks_the_row_rather_than_raising(self, transcribe):
        """A stuck row at «ذخیره شد» with nothing saying why looks exactly like
        the feature not working."""
        from services.audio.transcribe import TranscriptionUnavailable
        from services.research import call_analysis

        transcribe.side_effect = TranscriptionUnavailable("faster-whisper نصب نیست")
        call_analysis.run(self.recording)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.status, Recording.Status.FAILED)
        self.assertIn("faster-whisper", self.recording.error)

    @patch("services.research.call_analysis.recorded_json_call")
    @patch("services.research.call_analysis.transcribe")
    def test_a_good_call_is_transcribed_and_analysed(self, transcribe, call):
        from services.research import call_analysis

        transcribe.return_value = type(
            "T", (), {"text": "سلام. گران است. قیمت می‌فرستم.", "seconds": 42.0},
        )()
        call.return_value = ({
            "summary": "تماس اول",
            "objections": ["گران است"],
            "commitments": ["قیمت می‌فرستم"],
            "next": "قیمت را بفرست",
            "sentiment": "NEUTRAL",
        }, None)

        call_analysis.run(self.recording)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.status, Recording.Status.ANALYSED)
        self.assertEqual(self.recording.objections, ["گران است"])
        self.assertEqual(self.recording.suggested_next, "قیمت را بفرست")
        self.assertEqual(self.recording.seconds, 42)

    @patch("services.research.call_analysis.recorded_json_call")
    @patch("services.research.call_analysis.transcribe")
    def test_a_failed_analysis_keeps_the_transcript(self, transcribe, call):
        """The words are the expensive part and they are useful on their own."""
        from services.research import call_analysis

        transcribe.return_value = type("T", (), {"text": "چیزی گفته شد", "seconds": 5.0})()
        call.side_effect = RuntimeError("مدل جواب نداد")

        call_analysis.run(self.recording)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.status, Recording.Status.TRANSCRIBED)
        self.assertEqual(self.recording.transcript, "چیزی گفته شد")
        self.assertIn("تحلیل نشد", self.recording.error)

    @patch("services.research.call_analysis.transcribe")
    def test_a_silent_recording_says_so(self, transcribe):
        from services.research import call_analysis

        transcribe.return_value = type("T", (), {"text": "   ", "seconds": 3.0})()
        call_analysis.run(self.recording)
        self.recording.refresh_from_db()
        self.assertIn("حرفی شنیده نشد", self.recording.error)

    def test_a_long_transcript_keeps_both_ends(self):
        from services.research.call_analysis import _trimmed

        text = "A" * 5000 + "MIDDLE" * 2000 + "Z" * 5000
        out = _trimmed(text)
        self.assertLess(len(out), len(text))
        self.assertTrue(out.startswith("A"))
        self.assertTrue(out.endswith("Z"))

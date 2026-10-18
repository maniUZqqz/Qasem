"""The editor's API: who may use it, and what "suggest" is allowed to do.

The test that matters most here is the one proving `plan` renders nothing. §9's
«پیشنهادی» mode only means something if asking what the system would do leaves
the video untouched — otherwise the approval is decorative and a shop that
pressed "show me" finds their footage already changed.
"""
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.products.models import Product
from apps.stores.models import Membership, Store
from services.editing import preferences

from .models import EditDecision, UploadedVideo

TEMP_MEDIA = tempfile.mkdtemp()

#: What a measured video looks like once analysis has run: dark, with pauses.
DARK_AND_QUIET = {
    "readable": True, "duration": 60.0, "has_audio": True,
    "brightness": 40, "brightness_swing": 4, "colour_cast": 2, "motion": 3,
    "silence_count": 12, "silence_seconds": 18, "longest_silence": 3.1,
    "silences": [{"start": 4, "end": 7}], "clipped_pixels": 0,
}


@override_settings(MEDIA_ROOT=TEMP_MEDIA, CELERY_TASK_ALWAYS_EAGER=True)
class EditorAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("edit-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه ادیتور")
        self.product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self.client.force_login(self.owner)
        self.upload = UploadedVideo.objects.create(
            store=self.store,
            title="ویدیوی موبایل",
            video=SimpleUploadedFile("clip.mp4", b"not-really-a-video"),
            state=UploadedVideo.State.READY,
            duration=60.0,
            facts=DARK_AND_QUIET,
        )
        self.base = f"/api/v1/stores/{self.store.pk}/videos/"

    def _plan(self, **body):
        return self.client.post(
            f"{self.base}{self.upload.pk}/plan/", body or {"mode": "SUGGEST"},
            content_type="application/json",
        )

    # ----------------------------------------------------------- planning

    def test_planning_renders_nothing(self):
        """The whole meaning of «پیشنهادی». A plan endpoint that quietly
        rendered would make the approval decorative."""
        with patch("services.editing.edl.render") as render:
            response = self._plan()
        self.assertEqual(response.status_code, 200)
        render.assert_not_called()

    def test_the_plan_says_what_it_would_do_and_why(self):
        body = self._plan().json()
        self.assertTrue(body["operations"])
        for operation in body["operations"]:
            self.assertTrue(operation["reason"])
            self.assertTrue(operation["title"])

    def test_a_dark_and_pausey_video_gets_both_suggestions(self):
        proposed = {o["tool"] for o in self._plan().json()["operations"]}
        self.assertIn("brightness", proposed)
        self.assertIn("trim_silence", proposed)

    def test_manual_mode_does_only_what_it_was_told(self):
        body = self._plan(
            mode="MANUAL", operations=[{"tool": "contrast", "params": {"amount": 1.2}}],
        ).json()
        self.assertEqual([o["tool"] for o in body["operations"]], ["contrast"])

    def test_a_tool_that_does_not_exist_is_refused_by_name(self):
        body = self._plan(
            mode="MANUAL", operations=[{"tool": "shell", "params": {"cmd": "rm -rf /"}}],
        ).json()
        self.assertEqual(body["operations"], [])
        self.assertTrue(body["refusals"])

    def test_an_unknown_mode_is_refused(self):
        self.assertEqual(self._plan(mode="TURBO").status_code, 400)

    def test_a_video_that_was_never_analysed_cannot_be_planned(self):
        fresh = UploadedVideo.objects.create(
            store=self.store, video=SimpleUploadedFile("b.mp4", b"x"),
        )
        response = self.client.post(
            f"{self.base}{fresh.pk}/plan/", {"mode": "SUGGEST"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_an_unreadable_video_says_why_rather_than_planning(self):
        self.upload.state = UploadedVideo.State.FAILED
        self.upload.error = "فایل خراب است"
        self.upload.save()
        response = self._plan()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["message"], "فایل خراب است")

    # ----------------------------------------------------------- applying

    def test_suggest_cannot_be_applied(self):
        """It is the mode that means "do not apply". Accepting it here would
        make the two endpoints mean the same thing."""
        response = self.client.post(
            f"{self.base}{self.upload.pk}/edit/", {"mode": "SUGGEST"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_applying_queues_a_job(self):
        with patch("apps.content.views_editing.dispatch_job", return_value=None):
            response = self.client.post(
                f"{self.base}{self.upload.pk}/edit/", {"mode": "AUTO"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 202)
        self.assertIn("job_id", response.json())

    # ---------------------------------------------------------- rejecting

    def test_a_rejection_is_remembered(self):
        """§9's learning is mostly built from refusals, so they get their own
        endpoint rather than being inferred from silence."""
        response = self.client.post(
            f"{self.base}{self.upload.pk}/reject/",
            {"tools": [{"tool": "stabilize", "params": {}}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EditDecision.objects.filter(
                store=self.store, tool="stabilize", accepted=False,
            ).exists()
        )

    def test_rejecting_the_same_tool_repeatedly_stops_it_being_offered(self):
        for _ in range(5):
            self.client.post(
                f"{self.base}{self.upload.pk}/reject/",
                {"tools": ["trim_silence"]}, content_type="application/json",
            )
        proposed = {o["tool"] for o in self._plan().json()["operations"]}
        self.assertNotIn("trim_silence", proposed)

    def test_a_rejection_of_nothing_is_refused(self):
        response = self.client.post(
            f"{self.base}{self.upload.pk}/reject/", {"tools": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_an_invented_tool_cannot_be_rejected_into_existence(self):
        self.client.post(
            f"{self.base}{self.upload.pk}/reject/", {"tools": ["nonsense"]},
            content_type="application/json",
        )
        self.assertFalse(EditDecision.objects.filter(tool="nonsense").exists())

    # -------------------------------------------------------------- lists

    def test_the_list_carries_the_toolbox_and_the_modes(self):
        """A panel that had to hard-code either would drift from the backend
        the first time a tool changed."""
        body = self.client.get(self.base).json()
        self.assertTrue(body["tools"])
        self.assertEqual(
            {m["key"] for m in body["modes"]},
            {"MANUAL", "SUGGEST", "AUTO", "DIRECTED"},
        )

    def test_each_video_carries_what_was_found_in_it(self):
        found = self.client.get(self.base).json()["videos"][0]["findings"]
        self.assertIn("dark", [f["what"] for f in found])

    def test_the_shop_is_told_what_we_learned_about_them(self):
        preferences.save(
            self.store, {**preferences.DEFAULTS, "always_normalize_audio": True},
        )
        self.assertTrue(self.client.get(self.base).json()["habits"])

    # --------------------------------------------------------- permission

    def test_a_stranger_sees_nothing(self):
        stranger = User.objects.create_user("edit-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.base).status_code, 404)

    def test_a_support_member_cannot_edit_video(self):
        colleague = User.objects.create_user("edit-support", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.SUPPORT,
        )
        self.client.force_login(colleague)
        response = self.client.post(
            f"{self.base}{self.upload.pk}/edit/", {"mode": "AUTO"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_content_manager_can(self):
        colleague = User.objects.create_user("edit-content", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.CONTENT_MANAGER,
        )
        self.client.force_login(colleague)
        with patch("apps.content.views_editing.dispatch_job", return_value=None):
            response = self.client.post(
                f"{self.base}{self.upload.pk}/edit/", {"mode": "AUTO"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 202)

    def test_another_shops_video_is_invisible(self):
        other_owner = User.objects.create_user("edit-other", password="x")
        other = Store.objects.create(owner=other_owner, name="فروشگاه دیگر")
        foreign = UploadedVideo.objects.create(
            store=other, video=SimpleUploadedFile("c.mp4", b"x"), facts=DARK_AND_QUIET,
        )
        response = self.client.post(
            f"{self.base}{foreign.pk}/plan/", {"mode": "SUGGEST"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    # -------------------------------------------------------------- upload

    def test_an_oversized_file_is_refused_before_it_is_stored(self):
        # The limit is patched rather than the file: the test client re-parses
        # the multipart body, so the size the view sees comes from the real
        # bytes and cannot be faked from out here.
        with patch("apps.content.views_editing.MAX_UPLOAD_MB", 0):
            response = self.client.post(
                self.base, {"video": SimpleUploadedFile("big.mp4", b"xxxx")},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "too_big")
        self.assertFalse(UploadedVideo.objects.filter(title="big.mp4").exists())

    def test_a_file_that_is_not_a_video_is_refused(self):
        response = self.client.post(
            self.base, {"video": SimpleUploadedFile("notes.pdf", b"x")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "wrong_type")

    def test_uploading_nothing_is_refused(self):
        self.assertEqual(self.client.post(self.base, {}).status_code, 400)

    def test_a_good_upload_starts_the_measurement(self):
        with patch("apps.content.views_editing.dispatch_job", return_value=None) as go:
            response = self.client.post(
                self.base, {"video": SimpleUploadedFile("clip.mp4", b"x")},
            )
        self.assertEqual(response.status_code, 201)
        go.assert_called_once()

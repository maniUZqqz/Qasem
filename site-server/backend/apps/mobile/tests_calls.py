import os
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from . import asr, calls, notes, tasks
from .models import MobileCall, MobileCallConsent
from .tests_base import BASE, MobileTestCase

M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00M4A mp42isom" + b"\x00" * 64
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64


def audio(name="rec.m4a", data=M4A):
    return SimpleUploadedFile(name, data, content_type="audio/mp4")


class RegistrationTests(MobileTestCase):
    def live(self, c, **kw):
        return c.post(BASE + "calls/live/", {"number": "09121234567", "direction": "in", "started_at": timezone.now().isoformat(), **kw}, format="json")

    def test_live_then_call_log_reconciles_into_one_row(self):
        c = self.device_client()
        a = self.live(c)
        self.assertEqual((a.status_code, a.data["created"], a.data["normalized"]), (201, True, "989121234567"))
        b = self.live(c)                                       # phone-state fires several times
        self.assertEqual((b.status_code, b.data["created"], b.data["uid"]), (200, False, a.data["uid"]))
        started = (timezone.now() + timedelta(seconds=40)).isoformat()
        r = c.post(BASE + "calls/log/", {"calls": [{"client_id": "cl-77", "number": "+98 912 123 4567", "direction": "missed",
                                                    "started_at": started, "duration_s": 0, "contact_name": "علی"}]}, format="json")
        res = r.data["results"][0]
        self.assertEqual((res["uid"], res["created"]), (a.data["uid"], False))
        self.assertEqual(MobileCall.objects.count(), 1)
        call = MobileCall.objects.get()
        self.assertEqual((call.client_id, call.direction, call.contact_name, call.live), ("cl-77", "missed", "علی", False))
        # repeating the log is idempotent and still answers with the uid
        r2 = c.post(BASE + "calls/log/", {"calls": [{"client_id": "cl-77", "number": "09121234567", "direction": "missed", "started_at": started}]}, format="json")
        self.assertEqual(r2.data["results"][0]["uid"], a.data["uid"])
        self.assertEqual(MobileCall.objects.count(), 1)

    def test_log_creates_new_row_for_unrelated_call_and_rejects_bad_rows(self):
        c = self.device_client()
        r = c.post(BASE + "calls/log/", {"calls": [
            {"client_id": "x1", "number": "09121234567", "direction": "out", "started_at": "2026-11-01T10:00:00+03:30", "duration_s": 61},
            {"client_id": "", "number": "09121234567"}, {"client_id": "x3", "number": "1"}]}, format="json").data["results"]
        self.assertTrue(r[0]["created"])
        self.assertEqual(r[1]["error"], "bad_row")
        self.assertEqual(r[2]["error"], "bad_row")
        self.assertEqual(MobileCall.objects.get().duration_s, 61)

    def test_live_bad_number_and_list_filters(self):
        c = self.device_client()
        self.assertEqual(self.live(c, number="12").data["error"]["code"], "bad_number")
        self.live(c)
        r = c.get(BASE + "calls/?number=0912 123 4567")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(self.panel_client().get(BASE + "calls/?status=FAILED").data["count"], 0)

    def test_caller_label_comes_from_nm_customers(self):
        from apps.customers.models import Customer

        Customer.objects.create(store=self.store, name="رضا کریمی", phone="0912-123-4567")
        c = self.device_client()
        a = self.live(c)
        self.assertEqual(a.data["caller"], {"display": "رضا کریمی", "known": True})


class ConsentAndRecordingTests(MobileTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.device_client()
        self.uid = self.c.post(BASE + "calls/live/", {"number": "09121234567", "direction": "in"}, format="json").data["uid"]

    def upload(self, name="rec.m4a", data=M4A, **extra):
        return self.c.post(BASE + f"calls/{self.uid}/recording/", {"audio": audio(name, data), "source": "builtin_recorder", "duration_s": "42", **extra},
                           format="multipart")

    def grant(self):
        return self.c.post(BASE + "calls/consent/", {"number": "09121234567", "granted": True, "how": "verbal",
                                                      "obtained_how": "گفتم ضبط می‌شود و موافقت کرد"}, format="json")

    def test_no_consent_no_stored_recording(self):
        r = self.upload()
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "no_consent"))
        call = MobileCall.objects.get()
        self.assertEqual((call.status, call.audio_path), ("NO_CONSENT", ""))
        import glob

        self.assertEqual(glob.glob(os.path.join(str(calls.data_dir()), "calls", "**", f"{self.uid}*"), recursive=True), [])
        state = self.c.get(BASE + "calls/consent/?number=0912 123 4567").data
        self.assertFalse(state["granted"])

    def test_consent_requires_how_and_text_and_can_be_revoked(self):
        r = self.c.post(BASE + "calls/consent/", {"number": "09121234567", "how": "verbal", "obtained_how": " "}, format="json")
        self.assertEqual(r.data["error"]["code"], "missing_fields")
        self.assertEqual(self.c.post(BASE + "calls/consent/", {"number": "09121234567", "how": "telepathy", "obtained_how": "x"}, format="json").data["error"]["code"], "bad_how")
        self.assertTrue(self.grant().data["granted"])
        self.assertEqual(self.c.get(BASE + "calls/consent/?number=09121234567").data["source"], "mobile")
        self.assertFalse(self.c.post(BASE + "calls/consent/revoke/", {"number": "09121234567"}, format="json").data["granted"])
        self.assertEqual(self.upload().status_code, 403)             # revoked: new recordings refused
        self.assertEqual(MobileCallConsent.objects.count(), 1)       # the row stays as the record that consent once existed

    def test_upload_with_consent_runs_asr_and_notes(self):
        self.grant()
        fake_asr = {"text": "سلام قیمت این محصول چنده", "segments": [{"start": 0, "end": 2.5, "text": "سلام قیمت این محصول چنده"}], "engine": "node"}
        fake_notes = {"summary": "مشتری قیمت پرسید.", "sentiment": "POSITIVE", "objections": ["گران است"], "commitments": ["فردا زنگ می‌زنم"],
                      "next_steps": ["ارسال لیست قیمت"]}
        with mock.patch.object(asr, "transcribe", return_value=fake_asr) as t, mock.patch.object(notes, "analyse", return_value=fake_notes):
            r = self.upload()
        self.assertEqual((r.status_code, r.data["status"]), (201, "UPLOADED"))
        t.assert_called_once()
        d = self.c.get(BASE + f"calls/{self.uid}/").data
        self.assertEqual((d["status"], d["asr_engine"], d["sentiment"]), ("ANALYSED", "node", "POSITIVE"))
        self.assertEqual((d["summary"], d["next_steps"], d["objections"]), ("مشتری قیمت پرسید.", ["ارسال لیست قیمت"], ["گران است"]))
        self.assertEqual(d["transcript"], fake_asr["text"])
        self.assertTrue(d["has_audio"])
        self.assertEqual(MobileCall.objects.get().duration_s, 42)
        self.assertTrue(d["consent"]["granted"])

    def test_asr_failure_is_visible_not_silent(self):
        self.grant()
        with mock.patch.object(asr, "transcribe", side_effect=asr.AsrUnavailable("سرور پردازش خاموش است؛ متیس: اعتبار تمام شده")):
            self.assertEqual(self.upload().status_code, 201)
        d = self.c.get(BASE + f"calls/{self.uid}/").data
        self.assertEqual(d["status"], "FAILED")
        self.assertIn("متیس", d["error"])

    def test_notes_failure_keeps_the_transcript(self):
        self.grant()
        with mock.patch.object(asr, "transcribe", return_value={"text": "سلام", "segments": [], "engine": "metis"}), \
                mock.patch.object(notes, "analyse", side_effect=notes.NotesUnavailable("مدل در دسترس نیست")):
            self.upload()
        d = self.c.get(BASE + f"calls/{self.uid}/").data
        self.assertEqual((d["status"], d["transcript"]), ("TRANSCRIBED", "سلام"))
        self.assertIn("تحلیل نشد", d["error"])

    def test_empty_transcript(self):
        self.grant()
        with mock.patch.object(asr, "transcribe", return_value={"text": "  ", "segments": [], "engine": "node"}):
            self.upload()
        d = self.c.get(BASE + f"calls/{self.uid}/").data
        self.assertEqual((d["status"], d["error"]), ("TRANSCRIBED", "در این فایل حرفی شنیده نشد."))

    def test_bad_audio_and_size_and_switches(self):
        self.grant()
        self.assertEqual(self.upload("note.txt", b"hello world, not audio at all").data["error"]["code"], "bad_audio")
        self.assertEqual(self.upload("fake.m4a", b"not audio but named m4a, long enough").data["error"]["code"], "bad_audio")
        s = calls.MobileSettings.get()
        s.max_audio_mb = 0
        s.save()
        self.assertEqual(self.upload().data["error"]["code"], "too_large")
        s.max_audio_mb, s.calls_upload_enabled = 100, False
        s.save()
        r = self.upload()
        self.assertEqual((r.status_code, r.data["error"]["code"]), (409, "uploads_disabled"))

    def test_wav_accepted_and_audio_download_needs_staff(self):
        self.grant()
        with mock.patch.object(tasks.asr, "transcribe", side_effect=asr.AsrUnavailable("x")):
            self.assertEqual(self.upload("a.wav", WAV).status_code, 201)
        r = self.panel_client().get(BASE + f"calls/{self.uid}/audio/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), WAV)
        self.assertIn("private", r["Cache-Control"])
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(BASE + f"calls/{self.uid}/audio/").status_code, 401)
        self.assertEqual(self.panel_client(self.plain).get(BASE + f"calls/{self.uid}/audio/").status_code, 403)
        # stored outside any web-served folder and not world readable
        path = calls.audio_file(MobileCall.objects.get())
        self.assertTrue(str(path).startswith(str(calls.data_dir())))
        self.assertFalse(os.stat(path).st_mode & 0o007)

    def test_reprocess(self):
        self.grant()
        with mock.patch.object(asr, "transcribe", side_effect=asr.AsrUnavailable("down")):
            self.upload()
        self.assertEqual(MobileCall.objects.get().status, "FAILED")
        with mock.patch.object(asr, "transcribe", return_value={"text": "درست شد", "segments": [], "engine": "local"}), \
                mock.patch.object(notes, "analyse", return_value={"summary": "s", "sentiment": "", "objections": [], "commitments": [], "next_steps": []}):
            r = self.panel_client().post(BASE + f"calls/{self.uid}/reprocess/", {}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(MobileCall.objects.get().status, "ANALYSED")

    def test_asr_switch_off(self):
        self.grant()
        s = calls.MobileSettings.get()
        s.asr_enabled = False
        s.save()
        with mock.patch.object(asr, "transcribe") as t:
            self.upload()
        t.assert_not_called()
        self.assertEqual(MobileCall.objects.get().status, "UPLOADED")

    def test_consent_from_existing_prospect_module_counts(self):
        from apps.customers.calls import CallConsent
        from apps.customers.outreach import Prospect

        p = Prospect.objects.create(store=self.store, company="شرکت آزمون", phone="0912 123 4567")
        CallConsent.objects.create(prospect=p, granted=True, obtained_how="قرارداد")
        state = calls.consent_state("09121234567")
        self.assertEqual((state["granted"], state["source"]), (True, "prospect"))


class AsrRoutingTests(MobileTestCase):
    """The ASR order follows the owner's priority; engines are fakes, Metis is never reached."""

    def run_with(self, priority_value, local, metis):
        from services.ai import priority

        cfg = priority.Config(priority=priority_value)
        with mock.patch.object(priority, "config", return_value=cfg), mock.patch.object(asr, "_local", side_effect=local), \
                mock.patch.object(asr, "_metis", side_effect=metis):
            return asr.transcribe("/nonexistent.m4a", store=self.store)

    def test_local_first_uses_node_and_skips_metis(self):
        ok = {"text": "a", "segments": [], "engine": "node"}
        metis = mock.Mock(side_effect=AssertionError("must not be called"))
        from services.ai import priority

        cfg = priority.Config(priority=priority.LOCAL_FIRST)
        with mock.patch.object(priority, "config", return_value=cfg), mock.patch.object(asr, "_local", return_value=ok), mock.patch.object(asr, "_metis", metis):
            self.assertEqual(asr.transcribe("/x", self.store)["engine"], "node")
        metis.assert_not_called()

    def test_local_first_falls_back_to_metis(self):
        def boom(*a, **k):
            raise asr.AsrUnavailable("سرور پردازش خاموش است")

        out = self.run_with("local_first", boom, lambda *a, **k: {"text": "b", "segments": [], "engine": "metis"})
        self.assertEqual(out["engine"], "metis")

    def test_metis_first_and_both_failing_lists_every_reason(self):
        def bad(msg):
            def f(*a, **k):
                raise asr.AsrUnavailable(msg)
            return f

        order = []

        def rec(name, result=None, err=None):
            def f(*a, **k):
                order.append(name)
                if err:
                    raise asr.AsrUnavailable(err)
                return result
            return f

        from services.ai import priority

        with mock.patch.object(priority, "config", return_value=priority.Config(priority="metis_first")), \
                mock.patch.object(asr, "_local", side_effect=rec("local", err="گره خاموش")), \
                mock.patch.object(asr, "_metis", side_effect=rec("metis", err="اعتبار تمام شده")):
            with self.assertRaises(asr.AsrUnavailable) as cm:
                asr.transcribe("/x", self.store)
        self.assertEqual(order, ["metis", "local"])
        self.assertIn("اعتبار تمام شده", str(cm.exception))
        self.assertIn("گره خاموش", str(cm.exception))

    def test_metis_leg_is_blocked_by_store_data_policy_before_any_network(self):
        with mock.patch("requests.post", side_effect=AssertionError("network must not be touched")):
            with self.assertRaises(asr.AsrUnavailable) as cm:
                asr._metis(asr.Path("/x.m4a"), self.store)          # default policy: customer data may not leave
        self.assertIn("سیاست", str(cm.exception))

    def test_words_to_segments(self):
        words = [{"w": f"w{i}", "s": i, "e": i + 0.5} for i in range(23)]
        segs = asr.segments_from_words(words)
        self.assertEqual(len(segs), 3)
        self.assertEqual((segs[0]["start"], segs[0]["end"], segs[2]["text"]), (0.0, 9.5, "w20 w21 w22"))

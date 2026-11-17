"""«تلفظ»، دورِ سوم: نمونهٔ صدای تنظیماتِ فروشگاه با لایه عوض می‌شود، پیام و برچسب‌های صفحه، اضافهٔ جمع در API."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rest_framework.test import APIClient

from services.audio import node_audio

from . import services as svc
from . import views
from .tests import Base


class FakeProvider:
    """A voice provider that records what it was asked to say (no engine, no network)."""

    name = "piper"
    voice = "fa_IR-gyro-medium"
    is_local = True
    processor = "این سرور"
    use_pron = True

    def __init__(self, store):
        self.store = store
        self.calls = []

    def synthesize(self, text, out_path):
        self.calls.append(text)
        out = Path(out_path)
        out.write_bytes(b"RIFFfake" + text.encode("utf-8"))
        return out

    def describe(self):
        return {"engine": self.name, "voice": self.voice, "local": True, "processor": self.processor}


def fake_polish(raw, out):
    Path(out).write_bytes(Path(raw).read_bytes())
    return Path(out)


class VoicePreviewFollowsTheLayer(Base):
    """The voice-settings preview used to cache by text and voice only: turning the layer off or editing the store lexicon
    played the OLD sample from the same URL for a day."""

    TEXT = "سلام، برنامهٔ ۳ جلسه‌ای ۴۵۰.۰۰۰ تومان"

    def setUp(self):
        super().setUp()
        self.url = f"/api/v1/stores/{self.store.pk}/voice/preview/"
        self.provider = FakeProvider(self.store)
        for p in (mock.patch("services.audio.tts.get_tts_provider", return_value=self.provider),
                  mock.patch("services.audio.polish.maybe_polish", side_effect=fake_polish)):
            p.start()
            self.addCleanup(p.stop)

    def preview(self, text=None):
        r = self.api.post(self.url, {"text": text or self.TEXT}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_the_same_request_is_made_once(self):
        a, b = self.preview(), self.preview()
        self.assertEqual(a["url"], b["url"])
        self.assertEqual(len(self.provider.calls), 1)

    def test_a_store_word_makes_a_new_sample(self):
        a = self.preview()
        svc.save_entry(self.store, "سلام", "سَلام")
        b = self.preview()
        self.assertNotEqual(a["url"], b["url"], "the lexicon changed: the old sample must not come back")
        self.assertEqual(b["url"], self.preview()["url"], "and the new one is cached again")

    def test_switching_the_layer_off_and_on(self):
        a = self.preview()
        svc.save_settings(self.store, enabled=False)
        off = self.preview()
        self.assertNotEqual(a["url"], off["url"])
        svc.save_settings(self.store, enabled=True)
        self.assertEqual(self.preview()["url"], a["url"], "back to the first state: the first sample again")

    def test_the_depth_and_the_ezafe_switch_are_part_of_the_key(self):
        a = self.preview()
        svc.save_settings(self.store, depth={"piper": "full"})
        b = self.preview()
        svc.save_settings(self.store, ezafe=False)
        c = self.preview()
        self.assertEqual(len({a["url"], b["url"], c["url"]}), 3)

    def test_the_text_shown_is_what_the_voice_gets(self):
        out = self.preview()
        shown = out["spoken_text"]
        self.assertNotRegex(shown, r"[0-9۰-۹]", shown)
        self.assertIn("چهارصد و پنجاه هزار تومان", shown)
        self.assertIn("سه جلسه", shown)

    def test_with_the_layer_off_the_text_is_what_was_typed(self):
        svc.save_settings(self.store, enabled=False)
        shown = self.preview()["spoken_text"]
        self.assertRegex(shown, r"[0-9۰-۹]", "nothing is converted when the owner switched the layer off")


class PanelLabelsAndMessages(Base):
    def test_depth_labels_are_short_and_explained(self):
        d = self.api.get(f"{self.base}/").json()
        self.assertEqual(set(d["depths"]), {"normalize", "lexicon", "full"})
        self.assertEqual(set(d["depth_help"]), set(d["depths"]))
        for key, label in d["depths"].items():
            self.assertLessEqual(len(label), 24, f"{key}: a long label is cut off in a select box at phone width")
            self.assertGreater(len(d["depth_help"][key]), 60)

    def test_the_moss_waiting_message_says_why(self):
        job = SimpleNamespace(uid="22222222-2222-2222-2222-222222222222")
        for online, want in ((0, "خاموش"), (1, "چند ثانیه")):
            with mock.patch.object(node_audio, "enqueue", return_value=job), \
                    mock.patch.object(views, "_node_state", return_value={"known": 1, "online": online, "names": []}):
                r = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "moss", "variant": "after"}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertIn(want, r.json()["message"])
            if not online:
                self.assertIn("صفِ ماندگار", r.json()["message"])

    def test_the_preview_of_a_plural_ezafe_is_one_syllable(self):
        for text in ("برنامه‌های تمرینی", "ورزش‌های سنگین", "غذای سالم"):
            r = self.api.post(f"{self.base}/preview/", {"text": text, "depth": "lexicon"}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            d = r.json()
            ipa = d["engines"]["piper"]["ipa"]
            self.assertNotIn("jeje", ipa, text)
            self.assertNotIn("ɑjije", ipa, text)
            self.assertTrue(d["words"][0]["ezafe"], text)
            self.assertNotIn("ایه", d["engines"]["moss"]["text"], text)

    def test_the_predicate_is_not_linked(self):
        d = self.api.post(f"{self.base}/preview/", {"text": "برنامه عالی است", "depth": "lexicon"}, format="json").json()
        self.assertFalse(d["words"][0]["ezafe"])
        self.assertNotIn("eje", d["engines"]["piper"]["ipa"])

    def test_the_shipped_thousands_sentence_is_read_right(self):
        d = self.api.post(f"{self.base}/preview/", {"text": "هزینه ماهانه ۱٫۲۰۰٫۰۰۰ ریال می‌شود.", "depth": "normalize"}, format="json").json()
        self.assertIn("یک میلیون و دویست هزار ریال", d["normalized"])


class SamplesAreForSignedInUsersOnly(Base):
    """The before/after samples live in the server's data folder and are served by an authenticated endpoint (MEDIA_ROOT is public)."""

    def setUp(self):
        super().setUp()
        self.folder = Path(self.data) / "pron-samples" / "r3"
        self.folder.mkdir(parents=True)
        (self.folder / "r00_gyro_before.mp3").write_bytes(b"ID3before")
        (self.folder / "r00_gyro_after.mp3").write_bytes(b"ID3after")
        (self.folder / "manifest.json").write_text(json.dumps({
            "title": "نمونهٔ آزمایشی", "note": "n", "created": "2026-11-17", "layer_version": "x",
            "variants": [{"key": "before", "label": "پیش"}, {"key": "after", "label": "پس"}],
            "voices": [{"key": "gyro", "label": "گیرو"}],
            "lines": [{"group": "g", "text": "برنامه‌های تمرینی", "spoken": "برنامه‌های تمرینی",
                       "files": {"gyro": {"before": "r00_gyro_before.mp3", "after": "r00_gyro_after.mp3",
                                          "lexicon": "r00_gyro_missing.mp3", "evil": "../../etc/passwd"}}}],
        }, ensure_ascii=False), encoding="utf-8")

    def test_the_owner_sees_the_set_and_can_play_the_files(self):
        r = self.api.get(f"{self.base}/samples/")
        self.assertEqual(r.status_code, 200, r.content)
        sets = r.json()["sets"]
        self.assertEqual([s["id"] for s in sets], ["r3"])
        files = sets[0]["lines"][0]["files"]["gyro"]
        self.assertEqual(set(files), {"before", "after"}, "a missing file and a path outside the folder are not offered")
        got = self.api.get("/api/v1" + files["before"])
        self.assertEqual(got.status_code, 200)
        self.assertEqual(b"".join(got.streaming_content), b"ID3before")
        self.assertEqual(got["Content-Type"], "audio/mpeg")

    def test_nobody_without_a_login_can_listen(self):
        anon = APIClient()
        self.assertIn(anon.get(f"{self.base}/samples/").status_code, (401, 403))
        self.assertIn(anon.get(f"{self.base}/samples/r3/r00_gyro_before.mp3").status_code, (401, 403))

    def test_another_store_owner_cannot_use_this_store(self):
        other = APIClient()
        other.force_authenticate(self.other)
        self.assertIn(other.get(f"{self.base}/samples/").status_code, (403, 404))

    def test_bad_names_are_404(self):
        for name in ("..%2Fmanifest.json", "manifest.json", "x.exe", "r00_gyro_missing.mp3"):
            self.assertEqual(self.api.get(f"{self.base}/samples/r3/{name}").status_code, 404, name)
        self.assertEqual(self.api.get(f"{self.base}/samples/..%2Fr3/r00_gyro_before.mp3").status_code, 404)
        self.assertEqual(self.api.get(f"{self.base}/samples/r3/r00_gyro_before.mp3").status_code, 200)

    def test_no_samples_is_an_empty_list(self):
        for f in self.folder.iterdir():
            f.unlink()
        self.folder.rmdir()
        self.assertEqual(self.api.get(f"{self.base}/samples/").json(), {"sets": []})

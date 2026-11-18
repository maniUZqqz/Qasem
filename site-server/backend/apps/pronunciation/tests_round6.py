"""«تلفظ»، دورِ ششم (رفعِ سریع پس از بازبینیِ v3.54): «بهتر / بهترین» یک واژه‌اند (نه «به» + «تر»)، نویسهٔ کنترلی (NUL) به Piper نمی‌رسد، «دکتر تغذیه» «تغذیهٔ» نمی‌گیرد."""
from unittest import mock

from services.audio import tts

from .tests import Base


class PreviewRound6(Base):
    def preview(self, text, depth="lexicon"):
        r = self.api.post(f"{self.base}/preview/", {"text": text, "depth": depth}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_behtarin_and_behtar_keep_their_h_for_every_engine(self):
        for text, word, ipa_part, respelled in (("این برنامه بهترین انتخاب است", "بهترین", "behtarin", "بِهتَرین"),
                                                ("حالت بهتر می‌شود", "بهتر", "behtar", "بِهتَر")):
            d = self.preview(text)
            piper = d["engines"]["piper"]["ipa"].replace("ˈ", "")
            self.assertIn(ipa_part, piper, text)
            self.assertNotIn("betar", piper, text)
            row = next(w for w in d["words"] if w["text"] == word)
            self.assertEqual(row["source"], "shared", row)
            self.assertEqual(row["heard_as"], respelled, row)
            # the text engines at the depth that respells («try another depth» in the test box): the he is there
            d = self.preview(text, depth="full")
            for engine in ("edge", "moss"):
                self.assertIn(respelled, d["engines"][engine]["text"], (engine, text))
                self.assertNotIn("بِتَر", d["engines"][engine]["text"], (engine, text))

    def test_a_title_and_its_field_take_no_ezafe(self):
        d = self.preview("دکتر تغذیه برنامه می‌نویسد")
        self.assertFalse(next(w for w in d["words"] if w["text"] == "تغذیه")["ezafe"])
        self.assertNotIn("taq1zijeje", d["engines"]["piper"]["ipa"])

    def test_a_nul_in_the_text_is_not_in_the_normalised_text_or_the_phonemes(self):
        d = self.preview("سلام\x00 برنامه\x01 بهترین")
        self.assertNotIn("\x00", d["normalized"])
        self.assertEqual(d["normalized"], "سلام برنامه بهترین")
        for engine in d["engines"].values():
            for value in engine.values():
                if isinstance(value, str):
                    self.assertFalse([c for c in value if ord(c) < 0x20 and c not in "\n\t"], repr(value))


class ListenWithControlCharacters(Base):
    def listen(self, text, engine="piper", variant="after"):
        return self.api.post(f"{self.base}/listen/", {"text": text, "engine": engine, "variant": variant}, format="json")

    def test_only_a_nul_is_the_same_clear_422(self):
        for engine in ("piper", "edge", "moss"):
            r = self.listen("\x00\x00", engine)
            self.assertEqual(r.status_code, 422, (engine, r.content))
            self.assertIn("متنی برای خواندن نیست", r.content.decode())
            self.assertNotIn("null", r.content.decode().lower())

    def test_the_engine_is_given_the_text_without_the_nul_in_both_variants(self):
        seen = []

        class Spy(tts.PiperProvider):
            def synthesize(self, text, out_path):          # the guard of the base class has already cleaned the text by now
                seen.append(text)
                out_path.write_bytes(b"RIFF")
                return out_path

        with mock.patch("services.audio.tts.PiperProvider", Spy):
            for variant in ("after", "before"):
                r = self.listen("سلام\x00 برنامه تمرینی", variant=variant)
                self.assertEqual(r.status_code, 200, (variant, r.content))
        self.assertEqual(seen, ["سلام برنامه تمرینی", "سلام برنامه تمرینی"])

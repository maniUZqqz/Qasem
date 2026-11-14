"""دورِ دومِ آزمونِ چغر: رقم‌های نتیجهٔ تدوینِ خودکار فارسی‌اند («۲۰ سکوت، روی‌هم ۱۵ ثانیه»؛ پنل پیش‌تر نیمی را لاتین نشان می‌داد)."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from services.editing import agent, analysis


class FarsiDigitsInEditNotes(SimpleTestCase):
    def test_silence_note_uses_persian_digits(self):
        found = analysis.obvious_problems({
            "readable": True, "duration": 98, "has_audio": True, "silence_count": 20, "silence_seconds": 15.3, "brightness": 128,
        })
        note = next(f["note"] for f in found if f["what"] == "silence")
        self.assertEqual(note, "۲۰ سکوت، روی‌هم ۱۵ ثانیه")
        self.assertFalse(any(ch in note for ch in "0123456789"), note)

    def test_effect_detail_uses_persian_digits(self):
        op = SimpleNamespace(tool="denoise_audio", spec=SimpleNamespace(title="حذف نویز"), params={})
        ok, effects = agent.judge({"snr_db": 36.2}, {"snr_db": 39.4}, [op])
        self.assertTrue(ok)
        self.assertEqual(effects[0]["detail"], "فاصله‌ی صدا از نویز ۳۶ → ۳۹ دسی‌بل")

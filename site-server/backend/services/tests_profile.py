"""Voice Profile — and the three settings that do not exist. §22

The feature as specified asked for gender, age, accent, pitch and emotion. The
voice engine has two Persian voices, both adult, both Tehran-standard, both
tagged with one personality — so three of the five cannot be built, and the
tests below pin that they are **named and explained** rather than shipped as
dropdowns that quietly do nothing.

That is the load-bearing behaviour here. A shop who sets "emotion: excited",
hears no difference, and works out that our settings are decorative has learned
something that costs more than the missing feature did.
"""
from django.test import SimpleTestCase

from services.audio.profile import (
    MAX_PITCH,
    MAX_RATE,
    PERSIAN_VOICES,
    UNAVAILABLE,
    ProfileError,
    VoiceProfile,
    options,
)


class CatalogueTests(SimpleTestCase):
    def test_there_are_exactly_two_persian_voices(self):
        """Not an arbitrary limit — it is the entire Persian catalogue, and
        every decision in this module follows from it."""
        self.assertEqual(set(PERSIAN_VOICES), {"male", "female"})

    def test_gender_picks_a_real_voice_id(self):
        self.assertEqual(
            VoiceProfile(gender="female").voice_id(), "fa-IR-DilaraNeural",
        )
        self.assertEqual(
            VoiceProfile(gender="male").voice_id(), "fa-IR-FaridNeural",
        )

    def test_an_unknown_gender_says_what_is_available(self):
        with self.assertRaises(ProfileError) as caught:
            VoiceProfile(gender="robot").voice_id()
        self.assertIn("male", str(caught.exception))

    def test_english_has_its_own_voices(self):
        profile = VoiceProfile(gender="female", language="en")
        self.assertTrue(profile.voice_id().startswith("en-"))


class ProsodyTests(SimpleTestCase):
    def test_an_untouched_profile_sends_nothing(self):
        """A default profile must produce the same request as no profile at
        all, or "I changed nothing" would still change the audio."""
        self.assertEqual(VoiceProfile().as_kwargs(), {})
        self.assertTrue(VoiceProfile().is_default)

    def test_rate_is_formatted_the_way_edge_tts_wants(self):
        self.assertEqual(VoiceProfile(rate=-15).as_kwargs()["rate"], "-15%")
        self.assertEqual(VoiceProfile(rate=10).as_kwargs()["rate"], "+10%")

    def test_pitch_is_in_hertz(self):
        self.assertEqual(VoiceProfile(pitch=8).as_kwargs()["pitch"], "+8Hz")

    def test_only_the_settings_that_changed_are_sent(self):
        sent = VoiceProfile(rate=5).as_kwargs()
        self.assertEqual(list(sent), ["rate"])

    def test_an_extreme_rate_is_refused_with_the_reason(self):
        """Past about ±20% the neural voice stops sounding like a person, and
        a video whose voice sounds synthetic makes exactly the impression the
        product exists to avoid."""
        with self.assertRaises(ProfileError) as caught:
            VoiceProfile(rate=MAX_RATE + 5).as_kwargs()
        self.assertIn("شبیه آدم", str(caught.exception))

    def test_an_extreme_pitch_is_refused(self):
        with self.assertRaises(ProfileError):
            VoiceProfile(pitch=MAX_PITCH + 1).as_kwargs()

    def test_the_boundary_itself_is_allowed(self):
        VoiceProfile(rate=MAX_RATE, pitch=-MAX_PITCH).as_kwargs()


class DescriptionTests(SimpleTestCase):
    def test_a_profile_reads_back_in_words_not_numbers(self):
        """«سرعت: ۱۵-» means nothing to a shop owner."""
        said = VoiceProfile(gender="female", rate=-10, pitch=5).describe()
        self.assertIn("دلارا", said)
        self.assertIn("کندتر", said)
        self.assertIn("زیرتر", said)

    def test_an_untouched_profile_describes_only_the_voice(self):
        self.assertEqual(VoiceProfile().describe(), PERSIAN_VOICES["male"]["label"])


class HonestyTests(SimpleTestCase):
    """The part that matters most: what we say we cannot do."""

    def test_age_accent_and_emotion_are_all_declared_unavailable(self):
        self.assertEqual({u["key"] for u in UNAVAILABLE}, {"age", "accent", "emotion"})

    def test_each_refusal_explains_itself(self):
        for entry in UNAVAILABLE:
            self.assertTrue(entry["why"], entry["key"])
            self.assertGreater(len(entry["why"]), 30, entry["key"])

    def test_the_emotion_refusal_offers_what_to_use_instead(self):
        emotion = next(u for u in UNAVAILABLE if u["key"] == "emotion")
        self.assertIn("زیروبمی", emotion["why"])

    def test_the_panel_gets_the_refusals_alongside_the_controls(self):
        """Shown on the same page, not hidden in a help article nobody opens."""
        panel = options("fa")
        self.assertEqual(len(panel["unavailable"]), 3)
        self.assertEqual(len(panel["sliders"]), 3)
        self.assertEqual(len(panel["voices"]), 2)

    def test_every_slider_says_which_way_to_move_it(self):
        for slider in options("fa")["sliders"]:
            self.assertTrue(slider["hint"], slider["key"])


class StoreTests(SimpleTestCase):
    class Store:
        class profile:
            voice_profile = {"gender": "female", "rate": -10}

    def test_a_saved_profile_is_read_back(self):
        profile = VoiceProfile.from_store(self.Store(), "fa")
        self.assertEqual(profile.gender, "female")
        self.assertEqual(profile.rate, -10)

    def test_a_shop_with_no_saved_profile_gets_the_default(self):
        class Bare:
            pass

        self.assertTrue(VoiceProfile.from_store(Bare(), "fa").is_default)

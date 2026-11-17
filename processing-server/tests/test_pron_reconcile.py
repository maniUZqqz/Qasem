"""The node worker's copy of the Piper reconciliation must equal the site's (backend/services/audio/fa_pron/phones.py).

    python tests/test_pron_reconcile.py
"""
import importlib.util
import os
import sys
import unittest

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)

import pron_synth_worker as W  # noqa: E402

PHONES = os.path.join(os.path.dirname(PROC), "backend", "services", "audio", "fa_pron", "phones.py")

CASES = [
    ("barnɑme", "barnˈɑmeː"),                 # same segments (length mark aside): the voice's own string
    ("kuːʃti", "keʃtˈi"),                     # different segments: ours with the voice's stress
    ("tamrini", "tamrˈini"),
    ("xɑne", ""),                             # no native: ours as it is
    ("aʔzɑ", "ˈaʔzɑ"),
    ("sɑlem", "sɑlem"),                       # the voice wrote no stress at all
    ("ʔali", "ʔɑːli"),
    ("modirijat", "modiriːjat"),              # a different number of syllables
    ("pi", "ˈpiː"),
]


@unittest.skipUnless(os.path.isfile(PHONES), "the site's phones.py is not next to this folder (a node install)")
class SameAsTheSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("fa_phones_for_test", PHONES)
        cls.P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.P)

    def test_reconcile_is_identical(self):
        for ours, native in CASES:
            self.assertEqual(W.reconcile_ipa(ours, native), self.P.reconcile_ipa(ours, native), (ours, native))

    def test_helpers_are_identical(self):
        for ours, native in CASES:
            self.assertEqual(W.ipa_stress_index(native), self.P.ipa_stress_index(native))
            self.assertEqual(W.with_stress_like(ours, native), self.P.with_stress_like(ours, native))
            self.assertEqual(W.ipa_skeleton(native), self.P.ipa_skeleton(native))


class Pieces(unittest.TestCase):
    def test_a_plain_piece_is_the_voices_own(self):
        self.assertEqual(W.resolve_piece("کتاب", lambda w: "ketˈɑb"), "ketˈɑb")

    def test_a_lexicon_piece_is_reconciled(self):
        self.assertEqual(W.resolve_piece("کشتی|kuːʃti", lambda w: "keʃtˈi"), "kuːʃtˈi")
        self.assertEqual(W.resolve_piece("برنامه|barnɑme", lambda w: "barnˈɑmeː"), "barnˈɑmeː")

    def test_the_piece_regex(self):
        m = W.NATIVE.findall("a{{کتاب|ketɑb}}je b{{x}}")
        self.assertEqual(m, ["کتاب|ketɑb", "x"])


if __name__ == "__main__":
    unittest.main()

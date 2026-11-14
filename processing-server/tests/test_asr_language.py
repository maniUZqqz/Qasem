"""The node's speech language (review of 2026-11-13): Persian default, English, and "auto" (language detection).

    python -m unittest tests/test_asr_language.py        (from the processing folder; Windows and Linux)
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
import asr_jobs  # noqa: E402


class WorkerLanguageTests(unittest.TestCase):
    def test_persian_is_the_default(self):
        self.assertEqual(asr_jobs.worker_language(None), "fa")
        self.assertEqual(asr_jobs.worker_language("fa"), "fa")
        self.assertEqual(asr_jobs.worker_language(" FA "), "fa")

    def test_english_and_other_whisper_codes_pass_through_lower_case(self):
        self.assertEqual(asr_jobs.worker_language("en"), "en")
        self.assertEqual(asr_jobs.worker_language("EN"), "en")
        self.assertEqual(asr_jobs.worker_language("ar"), "ar")

    def test_auto_detect_is_an_empty_language(self):
        for v in ("", "auto", "AUTO", "detect"):
            self.assertEqual(asr_jobs.worker_language(v), "", v)

    def test_the_worker_command_carries_the_language(self):
        cmd = asr_jobs.worker_command("py", "a.wav", "models", "out.json", asr_jobs.worker_language("en"), True, True)
        self.assertEqual(cmd[cmd.index("--language") + 1], "en")
        cmd = asr_jobs.worker_command("py", "a.wav", "models", "out.json", asr_jobs.worker_language("auto"), True, True)
        self.assertEqual(cmd[cmd.index("--language") + 1], "")            # asr_worker.py: language=args.language or None -> Whisper detects

    def test_the_agent_can_advertise_what_it_understands(self):
        self.assertEqual(set(asr_jobs.LANGUAGES), {"fa", "en", "auto"})
        src = open(os.path.join(PROC, "agent.py"), encoding="utf-8").read()
        self.assertIn('caps["asr_languages"] = list(asr_jobs.LANGUAGES)', src)


class AbagramIndexTests(unittest.TestCase):
    def test_the_dead_runflare_mirror_is_not_asked_for_wheels(self):
        """Review of 2026-11-13: runflare answers /simple but returns HTTP 402 for every wheel; it only cost pip a retry cycle."""
        import abagram_jobs

        self.assertEqual(abagram_jobs.INDEX_URLS[0], "https://pypi.org/simple")
        self.assertFalse([u for u in abagram_jobs.INDEX_URLS if "runflare" in u], abagram_jobs.INDEX_URLS)
        self.assertGreaterEqual(len(abagram_jobs.INDEX_URLS), 2, "at least one mirror besides pypi.org")


if __name__ == "__main__":
    unittest.main()

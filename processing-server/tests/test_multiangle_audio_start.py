"""multiangle_engine.read_audio honours --start (review of 2026-11-13: the cut plan listened to the first seconds whatever --start said).

    python -m unittest tests/test_multiangle_audio_start.py        (from the processing folder)
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)

try:
    import numpy  # noqa: F401
    import multiangle_engine as ma
except Exception:  # noqa: BLE001 - the engine needs numpy; the node has it, a bare CI box may not
    ma = None


@unittest.skipIf(ma is None, "numpy / the engine is not importable here")
class ReadAudioStartTests(unittest.TestCase):
    def run_read(self, **kw):
        seen = {}

        def fake_run(cmd, **k):
            seen["cmd"] = list(cmd)
            return SimpleNamespace(returncode=0, stdout=b"\x00" * (16000 * 4), stderr=b"")

        with mock.patch.object(ma.subprocess, "run", fake_run):
            pcm = ma.read_audio("ffmpeg", "main.mp4", 10, **kw)
        return seen["cmd"], pcm

    def test_without_start_the_command_is_the_old_one(self):
        cmd, pcm = self.run_read()
        self.assertNotIn("-ss", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], "main.mp4")
        self.assertEqual(len(pcm), 16000)

    def test_start_seeks_before_the_input_so_the_window_matches_the_video(self):
        cmd, _pcm = self.run_read(start=40.0)
        self.assertIn("-ss", cmd)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "40.000")
        self.assertLess(cmd.index("-ss"), cmd.index("-i"), "-ss before -i = a fast, exact input seek")
        self.assertEqual(cmd[cmd.index("-t") + 1], "10.00")

    def test_two_starts_give_two_different_commands(self):
        a, _ = self.run_read(start=1.0)
        b, _ = self.run_read(start=40.0)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()

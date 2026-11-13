"""agent 2.11: autostart.py - the user's Startup folder shortcut (no admin), idempotent, switch-off honoured."""
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import autostart as au  # noqa: E402


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.appdata = os.path.join(self.tmp, "AppData", "Roaming")
        self.here = os.path.join(self.tmp, "processing-server")
        self.data = os.path.join(self.tmp, "NMarketing-data")
        os.makedirs(self.here)
        os.makedirs(self.data)
        open(os.path.join(self.here, "START.bat"), "w").write("@echo off\n")
        self.env = {"APPDATA": self.appdata}
        self.ps_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_powershell(self, works=True):
        def run(cmd, **kw):
            self.ps_calls.append(cmd)
            if works:
                m = re.search(r"CreateShortcut\('((?:[^']|'')*)'\)", cmd[-1])
                open(m.group(1).replace("''", "'"), "w").write("lnk")
            return None
        return run

    def ensure(self, **kw):
        kw.setdefault("run", self.fake_powershell())
        return au.ensure(self.here, self.data, env=self.env, plat_windows=True, **kw)

    def test_first_run_writes_a_minimized_shortcut_in_the_users_startup_folder(self):
        res = self.ensure()
        self.assertEqual(res["state"], "registered")
        self.assertTrue(res["path"].endswith("NMarketing Node.lnk"))
        self.assertIn("Start Menu", res["path"])
        self.assertTrue(os.path.isfile(res["path"]))
        ps = self.ps_calls[0][-1]
        self.assertIn("WindowStyle=7", ps)                                  # minimized
        self.assertIn("START.bat", ps)
        self.assertNotIn("runas", " ".join(self.ps_calls[0]).lower())      # no administrator rights asked
        self.assertTrue(au.status(self.here, self.data, self.env)["registered"])

    def test_second_run_changes_nothing(self):
        self.ensure()
        n = len(self.ps_calls)
        self.assertEqual(self.ensure()["state"], "unchanged")
        self.assertEqual(len(self.ps_calls), n)

    def test_a_moved_folder_rewrites_the_shortcut(self):
        self.ensure()
        new_here = os.path.join(self.tmp, "moved")
        os.makedirs(new_here)
        open(os.path.join(new_here, "START.bat"), "w").write("x")
        res = au.ensure(new_here, self.data, env=self.env, plat_windows=True, run=self.fake_powershell())
        self.assertEqual(res["state"], "registered")
        self.assertEqual(len(self.ps_calls), 2)

    def test_powershell_failing_falls_back_to_a_small_cmd_file(self):
        res = self.ensure(run=self.fake_powershell(works=False))
        self.assertEqual(res["state"], "registered")
        self.assertTrue(res["path"].endswith("NMarketing Node.cmd"))
        text = open(res["path"], encoding="utf-8").read()
        self.assertIn("start", text)
        self.assertIn("/min", text)
        self.assertIn("START.bat", text)

    def test_the_panel_setting_switches_it_off_and_back_on(self):
        path = self.ensure()["path"]
        res = self.ensure(enabled=False)
        self.assertIn(res["state"], ("removed", "disabled"))
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isfile(os.path.join(self.data, "autostart.off")))
        self.assertEqual(self.ensure(enabled=True)["state"], "disabled")   # the marker file keeps it off by default ...
        self.assertEqual(self.ensure(enabled=True, force=True)["state"], "registered")   # ... the panel's explicit «on» beats it
        self.assertFalse(os.path.isfile(os.path.join(self.data, "autostart.off")))

    def test_environment_switch(self):
        self.env["NM_AUTOSTART"] = "0"
        res = self.ensure()
        self.assertEqual(res["state"], "disabled")
        self.assertFalse(os.path.isdir(os.path.join(self.appdata, "Microsoft")))

    def test_other_systems_do_nothing(self):
        res = au.ensure(self.here, self.data, env=self.env, plat_windows=False)
        self.assertEqual(res["state"], "unsupported")
        res = au.ensure(self.here, self.data, env={}, plat_windows=True)
        self.assertEqual(res["state"], "unsupported")

    def test_a_missing_start_bat_is_reported(self):
        os.remove(os.path.join(self.here, "START.bat"))
        self.assertEqual(self.ensure()["state"], "failed")

    def test_apostrophes_in_paths_survive_the_powershell_quoting(self):
        here = os.path.join(self.tmp, "O'Brien")
        os.makedirs(here)
        open(os.path.join(here, "START.bat"), "w").write("x")
        res = au.ensure(here, self.data, env=self.env, plat_windows=True, run=self.fake_powershell())
        self.assertEqual(res["state"], "registered")
        self.assertIn("O''Brien", self.ps_calls[0][-1])


if __name__ == "__main__":
    unittest.main()

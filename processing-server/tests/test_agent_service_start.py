"""agent 2.8 (1405/08/17): services start through cmd.exe into a UTF-8 log, a .bat runs in its own folder, old UTF-16 logs read."""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402

PS_NOISE = ("\ufeffpython.exe : Traceback (most recent call last):\r\n"
            "At line:1 char:1\r\n"
            "+ & 'C:\\N\\ComfyUI_windows_portable\\run_nvidia_gpu.bat'  2>&1 | Tee-Object -FilePath 'x.log'\r\n"
            "+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\r\n"
            "    + CategoryInfo          : NotSpecified: (Traceback:String) [], RemoteException\r\n"
            "    + FullyQualifiedErrorId : NativeCommandError\r\n"
            " \r\n"
            "'.\\python_embeded\\python.exe' is not recognized as an internal or external command,\r\n")


class DecodeLogTests(unittest.TestCase):
    def test_an_old_utf16_powershell_log_reads_as_text(self):
        text = agent.decode_log(PS_NOISE.encode("utf-16-le"))
        self.assertIn("is not recognized as an internal or external command", text)
        self.assertNotIn("FullyQualifiedErrorId", text)
        self.assertNotIn("CategoryInfo", text)
        self.assertNotIn("\x00", text)

    def test_a_tail_that_starts_mid_character(self):
        raw = PS_NOISE.encode("utf-16-le")
        self.assertIn("is not recognized", agent.decode_log(raw[7:]))

    def test_utf8_is_unchanged(self):
        self.assertEqual(agent.decode_log("خطا: no module\nline 2".encode("utf-8")), "خطا: no module\nline 2")

    def test_tail_lines_uses_it(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "service-comfyui.log")
            with open(p, "wb") as fh:
                fh.write(PS_NOISE.encode("utf-16-le"))
            lines = agent.tail_lines(p, 40)
            self.assertTrue(any("is not recognized" in ln for ln in lines), lines)


class StartWindowsTests(unittest.TestCase):
    def _start(self, cmd, logf):
        fake = types.SimpleNamespace(_program_of=agent.ServiceManager._program_of)
        with mock.patch.object(agent.subprocess, "Popen") as popen:
            popen.return_value = "proc"
            out = agent.ServiceManager._start_windows(fake, "comfyui", cmd, logf, {"PATH": "x"})
        self.assertEqual(out, "proc")
        return popen.call_args

    def test_a_bat_runs_in_its_own_folder_through_cmd_not_powershell(self):
        with tempfile.TemporaryDirectory() as d:
            bat = os.path.join(d, "Comfy UI", "run_nvidia_gpu.bat")
            os.makedirs(os.path.dirname(bat))
            open(bat, "w").close()
            logf = os.path.join(d, "service-comfyui.log")
            with open(logf, "wb") as fh:
                fh.write(b"old run")
            args, kw = self._start('"%s"' % bat, logf)
            self.assertEqual(args[0], 'cmd.exe /d /s /c ""%s""' % bat)
            self.assertNotIn("powershell", args[0].lower())
            self.assertEqual(kw["cwd"], os.path.dirname(bat))
            self.assertIs(kw["stderr"], subprocess.STDOUT)
            self.assertIs(kw["stdin"], subprocess.DEVNULL)
            self.assertEqual(kw["env"]["PYTHONIOENCODING"], "utf-8")
            with open(logf, "rb") as fh:
                head = fh.read().decode("utf-8")
            self.assertIn("start comfyui", head)
            with open(logf[:-4] + ".prev.log", "rb") as fh:
                self.assertEqual(fh.read(), b"old run")          # the previous run's log is kept

    def test_other_programs_keep_the_code_folder(self):
        with tempfile.TemporaryDirectory() as d:
            args, kw = self._start('"C:\\data\\venvs\\moss-tts\\Scripts\\python.exe" audio\\moss_tts_server.py --port 5640',
                                   os.path.join(d, "service-moss.log"))
            self.assertEqual(kw["cwd"], agent.HERE)
            args, kw = self._start("ollama serve", os.path.join(d, "service-ollama.log"))
            self.assertEqual(kw["cwd"], agent.HERE)
            self.assertEqual(args[0], 'cmd.exe /d /s /c "ollama serve"')

    def test_start_no_longer_builds_a_powershell_tee(self):
        import inspect
        src = inspect.getsource(agent.ServiceManager.start)
        self.assertNotIn("Tee-Object", src)
        self.assertIn("_start_windows", src)


class MossDtypeTests(unittest.TestCase):
    def test_the_moss_worker_runs_under_autocast(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio", "moss_tts_server.py")
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("torch.autocast(device_type=\"cuda\", dtype=amp_dtype)", src)
        self.assertIn("with torch.inference_mode(), self.amp():", src)
        self.assertIn("NM_MOSS_DTYPE", src)


if __name__ == "__main__":
    unittest.main()

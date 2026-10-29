"""agent.py 1.8: the voice-model switches, the benchmark («تست»), downloads asked from the panel, the background
downloader and the start-up checklist - without a GPU (the worker scripts in --fake mode, a stand-in downloader).

    python tests\\test_agent_setup.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import agent  # noqa: E402
from test_agent_audio import AceHandler, AgentAudioTests, FakeSite, Proc, wav  # noqa: E402,F401

FAKE_DOWNLOADER = textwrap.dedent('''
    import json, sys, time
    args = sys.argv[1:]
    if "--status" in args:
        print(json.dumps({"version": "1.1", "running": False, "packages": {
            "moss-tts": {"installed": False, "optional": False, "bytes_missing": 15000000000, "bytes_total": 15500000000},
            "fun-inp": {"installed": False, "optional": True, "bytes_missing": 4000000000, "bytes_total": 4000000000}}}))
        sys.exit(0)
    path = args[args.index("--status-file") + 1]
    only = args[args.index("--only") + 1].split(",") if "--only" in args else ["moss-tts"]
    for i in range(3):
        json.dump({"state": "running", "packages": only, "bytes_done": i * 10, "bytes_total": 30, "items_done": i,
                   "items_total": 3, "current": {"id": "x", "done": i, "total": 3}}, open(path, "w"))
        time.sleep(0.3)
    json.dump({"state": "done", "packages": only, "bytes_done": 30, "bytes_total": 30}, open(path, "w"))
''')


class AgentSetupTests(AgentAudioTests):
    """Reuses AgentAudioTests' fake workers (moss / sfx in --fake mode, the fake ACE-Step API) and fixtures."""

    def setUp(self):
        super().setUp()
        agent.STATE["desired"] = {}
        agent.STATE["auto_switch"] = True

    # ------------------------------------------------------------ switches
    def test_switches_default_on_and_per_purpose(self):
        s = agent.audio_settings()
        self.assertTrue(all(s[k] for k in ("speech", "clone", "sfx", "music")))
        self.assertEqual(s["idle_min"], 15)
        agent.STATE["desired"] = {"audio": {"speech": False, "music": False, "idle_min": 5}}
        self.assertFalse(agent.audio_allowed("moss", "speech"))
        self.assertTrue(agent.audio_allowed("moss", "clone"), "cloning keeps MOSS allowed")
        self.assertTrue(agent.audio_allowed("moss"))
        self.assertFalse(agent.audio_allowed("music"))
        self.assertEqual(agent.audio_settings()["idle_min"], 5)
        self.assertEqual(agent.audio_purpose("voice.tts", {"engine": "moss-fa", "reference": "r.wav"}), "clone")
        self.assertEqual(agent.audio_purpose("voice.tts", {"engine": "moss-fa", "voice": "mana"}), "speech")

    def test_switched_off_model_never_starts_and_stops_at_once(self):
        self.install("moss", "music")
        m, calls = self.manager(running={"music"})
        m.procs["music"] = Proc()
        agent.STATE["desired"] = {"audio": {"music": False, "speech": False}}
        with self.assertRaises(agent.JobError) as ctx:
            m.prepare_audio("moss", True, purpose="speech")
        self.assertIn("DISABLED", str(ctx.exception))
        self.assertIn("خاموش", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)
        m.prepare_audio("moss", True, purpose="clone")            # cloning still on
        m.apply(agent.STATE["desired"])
        self.assertIn(("stop", "music"), calls, "a model switched off in the panel is stopped at once (VRAM freed)")

    def test_disabled_job_is_reported_as_final(self):
        self.install("sfx")
        agent.STATE["desired"] = {"audio": {"sfx": False}}
        site = FakeSite({"prompt": "rain", "seconds": 5})
        with mock.patch.object(agent, "MANAGER", self.manager()[0]):
            agent.run_job(site, {"uid": "sfx-off", "kind": "voice.sfx", "payload": site.payload})
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        self.assertFalse(finish["ok"])
        self.assertIn("DISABLED", finish["error"])
        self.assertIs(finish["meta"]["retryable"], False)

    def test_idle_minutes_come_from_the_panel(self):
        with mock.patch.object(agent, "find_comfy_start", lambda: None):
            m = agent.ServiceManager()
        stopped = []
        m.stop = lambda key: stopped.append(key) or True
        m.procs["sfx"] = Proc()
        agent.AUDIO_USE["sfx"] = time.time() - 4 * 60
        agent.STATE["desired"] = {"audio": {"idle_min": 5}}
        with mock.patch.dict(os.environ, {"NM_AUDIO_IDLE_S": ""}):
            m.reap_audio()
            self.assertEqual(stopped, [])
            agent.STATE["desired"] = {"audio": {"idle_min": 3}}
            m.reap_audio()
        self.assertEqual(stopped, ["sfx"])

    # ------------------------------------------------------------ benchmark
    def bench(self, model, running=()):
        self.install("moss", "sfx", "music")
        site = FakeSite({"model": model})
        m, calls = self.manager(running=set(running))
        for k in running:
            m.procs[k] = Proc()
        with mock.patch.object(agent, "MANAGER", m), mock.patch.object(agent.time, "sleep", lambda s: None), \
                mock.patch.object(agent, "vram_mb", lambda: (1500, 12288)):
            agent.run_job(site, {"uid": "bench-" + model, "kind": "node.bench", "payload": site.payload})
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        return finish, calls, site

    def test_bench_speech_measures_a_cold_load(self):
        finish, calls, site = self.bench("speech", running={"moss"})
        self.assertTrue(finish["ok"], finish)
        b = finish["meta"]["bench"]
        self.assertTrue(b["cold"])
        self.assertIn(("stop", "moss"), calls, "the engine is restarted so the model load is measured")
        for k in ("load_s", "gen_s", "audio_s", "rtf", "vram_total_mb"):
            self.assertIsNotNone(b[k], k)
        self.assertGreater(b["audio_s"], 1)
        self.assertEqual(site.uploads, [["file_bench.json", "file_bench.wav"]])

    def test_bench_music_and_clone(self):
        finish, _calls, _site = self.bench("music")
        self.assertTrue(finish["ok"], finish)
        self.assertEqual(finish["meta"]["bench"]["model"], "music")
        finish, _calls, _site = self.bench("clone")
        self.assertTrue(finish["ok"], finish)

    def test_bench_refuses_a_switched_off_model(self):
        agent.STATE["desired"] = {"audio": {"sfx": False}}
        finish, calls, _site = self.bench("sfx")
        self.assertFalse(finish["ok"])
        self.assertIn("DISABLED", finish["error"])
        self.assertNotIn(("start", "sfx"), calls)

    # ------------------------------------------------------------ downloads
    def test_panel_download_starts_the_downloader(self):
        fake = mock.Mock()
        fake.start.return_value = "started"
        fake.caps.return_value = {"running": True}
        site = FakeSite({"action": "download", "packages": ["fun-inp", "wan22-4step"]})
        with mock.patch.object(agent, "DOWNLOADS", fake), mock.patch.object(agent, "MANAGER", None):
            agent.run_job(site, {"uid": "models-1", "kind": "node.models", "payload": site.payload})
        fake.start.assert_called_once()
        self.assertEqual(fake.start.call_args[0][0], ["fun-inp", "wan22-4step"])
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        self.assertTrue(finish["ok"])

    def test_download_manager_with_a_stand_in_downloader(self):
        script = os.path.join(self.home, "download_models.py")
        open(script, "w").write(FAKE_DOWNLOADER)
        os.makedirs(os.path.join(self.home, "logs"), exist_ok=True)
        with mock.patch.object(agent, "DOWNLOADER", script):
            dm = agent.DownloadManager()
            dm.status_file = os.path.join(self.home, "logs", "download-status.json")
            self.assertEqual(dm.missing_default(), ["moss-tts"], "the optional package is not in the default set")
            self.assertEqual(dm.start(None), "started")
            self.assertEqual(dm.start(["fun-inp"]), "queued")
            self.assertTrue(dm.downloading("moss-tts"))
            caps = dm.caps()
            self.assertTrue(caps["running"])
            self.assertFalse(caps["packages"]["moss-tts"]["installed"])
            deadline = time.time() + 30
            while time.time() < deadline:
                dm.poll()
                pr = dm.progress() or {}
                if pr.get("packages") == ["fun-inp"] and pr.get("state") == "done":
                    break
                time.sleep(0.2)
            self.assertEqual(dm.progress()["packages"], ["fun-inp"], "the queued package runs when the first run ends")

    def test_jobs_wait_while_their_model_downloads(self):
        fake = mock.Mock()
        fake.downloading.return_value = True
        fake.percent_text.return_value = "45%"
        m, _calls = self.manager()
        with mock.patch.object(agent, "DOWNLOADS", fake):
            with self.assertRaises(agent.JobError) as ctx:
                m.prepare_audio("music", True, purpose="music")
        self.assertIn("DOWNLOADING", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable, "a job for a model that is still downloading is tried again later")

    # ------------------------------------------------------------ start-up checklist
    def test_checklist(self):
        lines = []
        fake = mock.Mock()
        fake.available.return_value = True
        fake.refresh.return_value = {"running": False, "packages": {
            "moss-tts": {"installed": False, "optional": False, "bytes_missing": 15e9},
            "fun-inp": {"installed": False, "optional": True, "bytes_missing": 4e9}}}
        site = mock.Mock()
        site.post.return_value = {"name": "TEST-NODE"}
        with mock.patch.object(agent, "DOWNLOADS", fake), mock.patch.object(agent, "find_comfy_start", lambda: '"C:\\c\\run_nvidia_gpu.bat"'), \
                mock.patch.object(agent, "gpu_names", lambda: ["NVIDIA GeForce RTX 3060, 12288 MiB"]), \
                mock.patch.object(agent, "nvidia_driver", lambda: "560.94"), \
                mock.patch.object(agent, "find_dotnet", lambda: None), \
                mock.patch.object(agent, "editor_published", lambda k: True), \
                mock.patch.object(agent, "ffmpeg_ok", lambda: True):
            rows = agent.preflight({"site": "http://x", "name": "TEST-NODE"}, site, out=lines.append)
        keys = {r["key"]: r for r in rows}
        for k in ("python", "git", "site", "ffmpeg", "dotnet", "editors", "comfyui", "gpu", "models", "disk"):
            self.assertIn(k, keys)
        self.assertTrue(keys["gpu"]["ok"])
        self.assertIsNone(keys["models"]["ok"])
        self.assertIn("downloading in the background", keys["models"]["detail"])
        self.assertIn("ready-built", keys["dotnet"]["detail"])
        self.assertTrue(all(ord(ch) < 128 or ch in "\u2713\u2717" for line in lines for ch in line),
                        "the console checklist is English (the Windows console garbles Persian)")
        self.assertEqual(agent.STATE["preflight"][0]["key"], "python")

    def test_no_nuget_means_no_build(self):
        agent._NUGET["ok"] = False
        built = []
        with mock.patch.object(agent, "editor_published", side_effect=[False, False, True]), \
                mock.patch.object(agent, "find_dotnet", lambda: "C:\\dotnet\\dotnet.exe"), \
                mock.patch.object(agent, "run_logged", lambda *a, **k: built.append(a) or True), \
                mock.patch.object(agent, "fetch_pack", lambda name, tick=None: 1) as _fp, \
                mock.patch.object(agent, "voice_models_ok", lambda: True):
            agent.ensure_editor("voice")
        self.assertEqual(built, [], "no dotnet build is started when nuget.org is unreachable")
        agent._NUGET.clear()


if __name__ == "__main__":
    unittest.main(defaultTest="AgentSetupTests")

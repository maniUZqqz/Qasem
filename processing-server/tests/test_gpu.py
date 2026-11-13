"""agent 2.11: gpu.py - GPU-first helpers (nvidia-smi samples, device verdict, ffmpeg NVENC choice, Ollama context size)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gpu  # noqa: E402


class R:
    """A fake subprocess result (text or bytes stdout)."""

    def __init__(self, out="", rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


def smi(line):
    return lambda cmd, **kw: R(line)


class SnapshotTests(unittest.TestCase):
    def test_parses_one_line_of_nvidia_smi(self):
        s = gpu.snapshot(run=smi("37, 4096, 12288, 61, 118.52, NVIDIA GeForce RTX 3060\n"), which=lambda n: "nvidia-smi")
        self.assertEqual(s["util"], 37)
        self.assertEqual(s["vram_used_mb"], 4096)
        self.assertEqual(s["vram_total_mb"], 12288)
        self.assertEqual(s["temp_c"], 61)
        self.assertEqual(s["power_w"], 118.5)
        self.assertIn("3060", s["name"])

    def test_no_driver_means_none_not_an_error(self):
        self.assertIsNone(gpu.snapshot(which=lambda n: None))
        self.assertIsNone(gpu.snapshot(run=smi(""), which=lambda n: "x"))
        self.assertIsNone(gpu.snapshot(run=smi("garbage"), which=lambda n: "x"))

    def test_not_supported_fields_do_not_break_it(self):
        s = gpu.snapshot(run=smi("5, 900, 12288, [N/A], [N/A], RTX\n"), which=lambda n: "x")
        self.assertEqual(s["util"], 5)
        self.assertIsNone(s["temp_c"])
        self.assertIsNone(s["power_w"])

    def test_compute_apps(self):
        apps = gpu.compute_apps(run=smi("123, C:\\Windows\\python.exe, 2048\n456, ollama.exe, [N/A]\n"), which=lambda n: "x")
        self.assertEqual([a["name"] for a in apps], ["python.exe", "ollama.exe"])
        self.assertEqual(apps[0]["vram_mb"], 2048)
        self.assertIsNone(apps[1]["vram_mb"])


class SamplerTests(unittest.TestCase):
    def test_summary_of_samples(self):
        seq = iter([{"util": 2, "vram_used_mb": 1000, "vram_total_mb": 12288, "temp_c": 50, "power_w": 40.0, "name": "RTX"},
                    {"util": 90, "vram_used_mb": 9000, "vram_total_mb": 12288, "temp_c": 70, "power_w": 150.0, "name": "RTX"},
                    {"util": 60, "vram_used_mb": 8000, "vram_total_mb": 12288, "temp_c": 72, "power_w": 140.0, "name": "RTX"}])
        smp = gpu.GpuSampler(interval=60, snap=lambda: next(seq))
        smp.sample()
        smp.sample()
        smp.sample()
        sm = smp.summary()
        self.assertEqual(sm["samples"], 3)
        self.assertEqual(sm["util_max"], 90)
        self.assertAlmostEqual(sm["util_avg"], 50.7, places=1)
        self.assertEqual(sm["vram_max_mb"], 9000)
        self.assertEqual(sm["vram_start_mb"], 1000)
        self.assertEqual(sm["temp_max_c"], 72)
        self.assertEqual(sm["vram_total_mb"], 12288)
        self.assertEqual(len(sm["series"]), 3)

    def test_series_is_thinned(self):
        rows = [(i, 10, 1000 + i, 50, 40.0) for i in range(500)]
        sm = gpu.summarize(rows, 12288, "x", max_points=40)
        self.assertLessEqual(len(sm["series"]), 40)

    def test_background_thread_samples_and_stops(self):
        smp = gpu.GpuSampler(interval=0.2, snap=lambda: {"util": 50, "vram_used_mb": 5000, "vram_total_mb": 12288, "temp_c": 1, "power_w": 1.0, "name": "x"})
        smp.start()
        import time
        time.sleep(0.7)
        sm = smp.stop()
        self.assertGreaterEqual(sm["samples"], 3)

    def test_no_samples_is_an_empty_summary(self):
        self.assertEqual(gpu.GpuSampler(snap=lambda: None).summary(), {})


class DeviceVerdictTests(unittest.TestCase):
    BUSY = {"util_max": 88, "vram_start_mb": 1000, "vram_max_mb": 8000}
    IDLE = {"util_max": 3, "vram_start_mb": 1000, "vram_max_mb": 1050}

    def test_busy_gpu_means_cuda(self):
        self.assertEqual(gpu.classify("comfy.graph", {}, {}, self.BUSY)[0], "cuda")

    def test_idle_gpu_for_a_gpu_kind_is_a_cpu_warning_with_a_reason(self):
        device, note, warning = gpu.classify("comfy.graph", {}, {}, self.IDLE)
        self.assertEqual(device, "cpu")
        self.assertIn("idle", note)
        self.assertIn("پردازنده", warning)

    def test_idle_gpu_for_a_cpu_kind_is_no_warning(self):
        device, _n, warning = gpu.classify("photo.edit", {}, {}, self.IDLE)
        self.assertEqual(device, "cpu")
        self.assertEqual(warning, "")

    def test_handler_knowledge_wins_over_samples(self):
        d, note, w = gpu.classify("ollama.generate", {}, {"device": "mixed", "device_note": "qwq:32b: 40% of the model in VRAM"}, self.BUSY)
        self.assertEqual(d, "mixed")
        self.assertIn("40%", note)
        self.assertTrue(w)                                  # part of a GPU job on the CPU is a warning too

    def test_onnx_provider_and_encoder(self):
        self.assertEqual(gpu.classify("edit.matte", {}, {"provider": "Dml"}, {})[0], "directml")
        self.assertEqual(gpu.classify("edit.matte", {}, {"provider": "CUDA"}, {})[0], "cuda")
        d, _n, w = gpu.classify("edit.matte", {}, {"provider": "CPU"}, {})
        self.assertEqual(d, "cpu")
        self.assertTrue(w)
        self.assertEqual(gpu.classify("edit.render", {}, {"encoder": "NVENC H.264"}, {})[0], "nvenc")
        d, _n, w = gpu.classify("edit.render", {}, {"encoder": "H.264"}, {})
        self.assertEqual(d, "cpu")
        self.assertTrue(w)

    def test_device_words_are_normalised(self):
        for word, want in (("dml", "directml"), ("DirectML", "directml"), ("cuda bfloat16 (codec float32)", "cuda"),
                           ("cpu", "cpu"), ("CPUExecutionProvider", "cpu"), ("nvenc", "nvenc"), ("", ""), ("tpu", "")):
            self.assertEqual(gpu.norm_device(word), want, word)
        self.assertEqual(gpu.classify("photo.matting", {}, {"device": "dml"}, {})[0], "directml")

    def test_unknown_without_samples(self):
        self.assertEqual(gpu.classify("comfy.graph", {}, {}, {})[0], "unknown")

    def test_only_moss_tts_is_expected_on_the_gpu(self):
        self.assertTrue(gpu.expects_gpu("voice.tts", {"engine": "moss-fa"}))
        self.assertFalse(gpu.expects_gpu("voice.tts", {"engine": "piper"}))
        self.assertTrue(gpu.expects_gpu("comfy.profile"))
        self.assertTrue(gpu.expects_gpu("asr.transcribe"))
        self.assertFalse(gpu.expects_gpu("echo"))

    def test_stamp_meta_adds_the_fields_and_keeps_the_handlers_device(self):
        meta = gpu.stamp_meta({"device": "cuda", "primary": "x.png"}, "comfy.graph", {}, {"util_max": 1, "vram_start_mb": 1, "vram_max_mb": 2})
        self.assertEqual(meta["device"], "cuda")
        self.assertIn("gpu", meta)
        self.assertNotIn("device_warning", meta)
        meta = gpu.stamp_meta({}, "comfy.graph", {}, self.IDLE)
        self.assertEqual(meta["device"], "cpu")
        self.assertIn("device_warning", meta)


class FfmpegTests(unittest.TestCase):
    """A fake ffmpeg: `run(cmd, timeout)` answers like ffmpeg -version / -encoders / -hwaccels / an encode."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        gpu._FF.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def exe(self, name):
        p = os.path.join(self.tmp, name)
        open(p, "wb").write(b"x")
        return p

    def fake_run(self, nvenc_ok=True, encoders=" V....D h264_nvenc NVENC H.264\n V....D hevc_nvenc NVENC hevc\n", cuda=True,
                 decode_ok=True):
        calls = []

        def run(cmd, timeout=60):
            calls.append(cmd)
            if "-version" in cmd:
                return R(b"ffmpeg version 7.1-test\n")
            if "-encoders" in cmd:
                return R(encoders.encode())
            if "-hwaccels" in cmd:
                return R(("Hardware acceleration methods:\n" + ("cuda\n" if cuda else "")).encode())
            if "-c:v" in cmd:                           # the NVENC test encode
                codec = cmd[cmd.index("-c:v") + 1]
                if nvenc_ok:
                    open(cmd[-1], "wb").write(b"mp4")
                    return R(b"", 0)
                return R(b"", 1, b"OpenEncodeSessionEx failed: no capable devices found (%s)" % codec.encode())
            if "-hwaccel" in cmd:                       # the NVDEC test decode
                return R(b"", 0 if decode_ok else 1)
            return R(b"", 0)
        run.calls = calls
        return run

    def test_report_proves_nvenc_with_a_real_encode_and_nvdec_with_a_real_decode(self):
        ff = self.exe("ffmpeg")
        rep = gpu.ffmpeg_report(ff, self.fake_run())
        self.assertTrue(rep["nvenc_h264"] and rep["nvenc_hevc"])
        self.assertTrue(rep["cuda_decode"])
        self.assertEqual(rep["version"], "7.1-test")
        self.assertEqual(gpu.hwaccel_args(rep), ["-hwaccel", "cuda"])

    def test_compiled_in_but_broken_nvenc_is_not_nvenc(self):
        rep = gpu.ffmpeg_report(self.exe("ffmpeg"), self.fake_run(nvenc_ok=False))
        self.assertFalse(rep["nvenc_h264"])
        self.assertFalse(rep["cuda_decode"])
        self.assertIn("no capable devices", rep["nvenc_error"])
        self.assertEqual(gpu.hwaccel_args(rep), [])

    def test_no_nvenc_encoder_compiled_in(self):
        rep = gpu.ffmpeg_report(self.exe("ffmpeg"), self.fake_run(encoders=" V..... libx264 H.264\n"))
        self.assertFalse(rep["nvenc_h264"])

    def test_report_is_cached(self):
        ff = self.exe("ffmpeg")
        run = self.fake_run()
        gpu.ffmpeg_report(ff, run)
        n = len(run.calls)
        gpu.ffmpeg_report(ff, run)
        self.assertEqual(len(run.calls), n)

    def test_the_ffmpeg_with_working_nvenc_wins(self):
        os.makedirs(os.path.join(self.tmp, "vendor", "ffmpeg", "bin"))
        kit = os.path.join(self.tmp, "vendor", "ffmpeg", "bin", "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
        open(kit, "wb").write(b"kit")
        owner = self.exe("owner-ffmpeg")

        def run(cmd, timeout=60):
            if cmd[0] == owner:                         # the owner's own ffmpeg: no NVENC
                return self.fake_run(nvenc_ok=False, encoders=" V..... libx264 x\n")(cmd, timeout)
            return self.fake_run()(cmd, timeout)
        os.environ["NM_FFMPEG"] = owner
        try:
            best, rep = gpu.best_ffmpeg(self.tmp, run)
        finally:
            os.environ.pop("NM_FFMPEG")
        self.assertEqual(best, kit)
        self.assertTrue(rep["nvenc_h264"])

    def test_without_nvenc_anywhere_the_first_working_ffmpeg_is_used(self):
        owner = self.exe("owner-ffmpeg")
        os.environ["NM_FFMPEG"] = owner
        try:
            best, rep = gpu.best_ffmpeg(self.tmp, self.fake_run(nvenc_ok=False))
        finally:
            os.environ.pop("NM_FFMPEG")
        self.assertEqual(best, owner)
        self.assertFalse(rep.get("nvenc_h264"))

    def test_cached_mode_never_starts_ffmpeg(self):
        owner = self.exe("owner-ffmpeg")
        os.environ["NM_FFMPEG"] = owner
        try:
            run = self.fake_run()
            best, rep = gpu.best_ffmpeg(self.tmp, run, probe="cached")
            self.assertEqual(best, owner)
            self.assertEqual(run.calls, [])
            gpu.ffmpeg_report(owner, run)
            self.assertTrue(gpu.best_ffmpeg(self.tmp, run, probe="cached")[1]["nvenc_h264"])
        finally:
            os.environ.pop("NM_FFMPEG")

    def test_no_hwaccel_switch(self):
        os.environ["NM_NO_HWACCEL"] = "1"
        try:
            self.assertEqual(gpu.hwaccel_args({"cuda_decode": True}), [])
        finally:
            os.environ.pop("NM_NO_HWACCEL")


class OllamaPolicyTests(unittest.TestCase):
    def test_env_defaults_and_the_owners_own_values_win(self):
        env = gpu.ollama_env({"PATH": "x"})
        self.assertEqual(env["OLLAMA_FLASH_ATTENTION"], "1")
        self.assertEqual(env["OLLAMA_KV_CACHE_TYPE"], "q8_0")
        self.assertEqual(env["OLLAMA_MAX_LOADED_MODELS"], "1")
        self.assertEqual(env["OLLAMA_NUM_PARALLEL"], "1")
        self.assertEqual(gpu.ollama_env({"OLLAMA_NUM_PARALLEL": "4"})["OLLAMA_NUM_PARALLEL"], "4")

    def test_small_model_gets_a_big_context_big_model_a_small_one(self):
        ctx8, fits8 = gpu.num_ctx_for(5.2e9, 12288)             # qwen3:8b on a 12 GB card
        self.assertTrue(fits8)
        self.assertGreaterEqual(ctx8, 16384)
        self.assertLessEqual(ctx8, 32768)
        ctx32, fits32 = gpu.num_ctx_for(19.9e9, 12288)          # qwq:32b does not fit at all
        self.assertFalse(fits32)
        self.assertEqual(ctx32, 4096)

    def test_a_long_prompt_raises_the_context_and_says_it_may_spill(self):
        ctx, fits = gpu.num_ctx_for(5.2e9, 12288, prompt_chars=120000)
        self.assertEqual(ctx, 32768)
        small_ctx, _ = gpu.num_ctx_for(5.2e9, 12288, prompt_chars=100)
        self.assertGreaterEqual(ctx, small_ctx)

    def test_unknown_card_keeps_the_default(self):
        self.assertEqual(gpu.num_ctx_for(5e9, None), (4096, None))

    def test_ps_reports_how_much_sits_on_the_card(self):
        full = {"models": [{"name": "qwen3:8b", "size": 6000, "size_vram": 6000}]}
        part = {"models": [{"name": "qwq:32b", "size": 20000, "size_vram": 8000}]}
        none = {"models": [{"name": "x", "size": 20000, "size_vram": 0}]}
        self.assertEqual(gpu.ollama_device(full)[0], "cuda")
        d, note = gpu.ollama_device(part)
        self.assertEqual(d, "mixed")
        self.assertIn("40%", note)
        self.assertEqual(gpu.ollama_device(none)[0], "cpu")
        self.assertEqual(gpu.ollama_device({"models": []})[0], "unknown")


class VramHandOverTests(unittest.TestCase):
    def test_waits_until_memory_comes_back(self):
        used = iter([9000, 9000, 4000, 1500])
        clock = []
        freed = gpu.settle_vram(9000, wait_s=10, snap=lambda: {"vram_used_mb": next(used)}, sleep=lambda s: clock.append(s))
        self.assertGreaterEqual(freed, 5000)

    def test_nothing_to_wait_for(self):
        freed = gpu.settle_vram(500, wait_s=3, snap=lambda: {"vram_used_mb": 500}, sleep=lambda s: None)
        self.assertEqual(freed, 0)
        self.assertEqual(gpu.settle_vram(None), 0)

    def test_peers_are_asked_and_a_dead_one_is_ignored(self):
        tmp = tempfile.mkdtemp()
        try:
            open(os.path.join(tmp, "gpu-peers.json"), "w").write(
                '[{"name": "instai", "free": "http://127.0.0.1:1/free"}, {"name": "other", "free": "http://127.0.0.1:2/free"}, {"bad": 1}]')
            seen = []

            def post(url):
                seen.append(url)
                if url.endswith(":2/free"):
                    raise OSError("refused")
            self.assertEqual(gpu.free_peers(tmp, post), ["instai"])
            self.assertEqual(len(seen), 2)
            self.assertEqual(gpu.free_peers(tempfile.gettempdir() + "/nope-nm", post), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CudaDllTests(unittest.TestCase):
    def test_nvidia_wheel_folders_are_found_and_put_on_path(self):
        tmp = tempfile.mkdtemp()
        try:
            sp = os.path.join(tmp, "Lib", "site-packages")
            for name in ("cublas", "cudnn"):
                os.makedirs(os.path.join(sp, "nvidia", name, "bin"))
            os.makedirs(os.path.join(sp, "nvidia", "other"))
            dirs = gpu.nvidia_dll_dirs(sp)
            self.assertEqual(len(dirs), 2)
            env = gpu.env_with_cuda_dlls(tmp, {"PATH": "C:\\x"})
            self.assertTrue(env["PATH"].startswith(dirs[0]))
            self.assertTrue(env["PATH"].endswith("C:\\x"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_probes_report_instead_of_raising(self):
        self.assertIn("error", gpu.torch_report("/no/python"))
        self.assertIn("error", gpu.ort_report(""))


if __name__ == "__main__":
    unittest.main()

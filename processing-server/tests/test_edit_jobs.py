"""agent 2.2: the video editor's jobs on the node - edit.render (resumable download + upload, cache, NVENC -> CPU fallback,
cancel, the Persian-title self-test, caps), edit.track (OpenCV) and edit.matte (through a stand-in photo kit) -
against a fake site (stdlib HTTP server) and the real ffmpeg. Runs on Windows and Linux.

    python -m unittest tests/test_edit_jobs.py        (from the processing folder)
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import agent  # noqa: E402
import edit_jobs  # noqa: E402
import edit_render  # noqa: E402

FF = edit_render.ffmpeg_exe(agent)
HAVE_FF = bool(FF)
FONTS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "backend", "services", "imaging", "fonts")
TRACK_COPY = os.path.join(os.path.dirname(HERE), "edit_track.py")
SITE_COPY = os.path.join(os.path.dirname(os.path.dirname(HERE)), "backend", "services", "editing", "tracking.py")


def run_ff(*args):
    subprocess.run([FF, "-v", "error", "-y", *args], check=True, stdin=subprocess.DEVNULL, capture_output=True)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Site:
    """The site's side of the transfer protocol (compute/transfer.py), with faults on demand."""

    def __init__(self):
        self.files = {}
        self.received = {}
        self.gets = []
        self.puts = []
        self.cancel = False
        self.progress = []
        self.cut_first_get_after = 0
        self.fail_put_numbers = set()       # 1-based PUT numbers answered with 500 BEFORE storing
        self.lose_ack_put_numbers = set()   # stored, but answered with 500 (the node must ask how much arrived)
        self.put_count = 0
        self.get_count = 0


SITE = Site()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        m = re.match(r"^/api/v1/compute/jobs/([^/]+)/files/([^/]+)/$", u.path)
        if m:
            data = SITE.files.get(m.group(2))
            if data is None:
                return self._send(404, {"error": "no"})
            SITE.get_count += 1
            SITE.gets.append(self.headers.get("Range"))
            start = 0
            rng = self.headers.get("Range")
            if rng:
                start = int(re.match(r"bytes=(\d+)-", rng).group(1))
            part = data[start:]
            code = 206 if rng else 200
            hdrs = {"Accept-Ranges": "bytes", "X-NM-SHA256": hashlib.sha256(data).hexdigest()}
            if rng:
                hdrs["Content-Range"] = "bytes %d-%d/%d" % (start, len(data) - 1, len(data))
            self.send_response(code)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(part)))
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.end_headers()
            if SITE.get_count == 1 and SITE.cut_first_get_after:
                self.wfile.write(part[: SITE.cut_first_get_after])
                self.wfile.flush()
                self.close_connection = True
                return
            self.wfile.write(part)
            return
        m = re.match(r"^/api/v1/compute/jobs/([^/]+)/chunks/([^/]+)/$", u.path)
        if m:
            have = len(SITE.received.get(m.group(2), b""))
            return self._send(200, {"size": have, "complete": False})
        return self._send(404, {"error": "no"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if self.path.endswith("/progress/"):
            try:
                SITE.progress.append(json.loads(body.decode() or "{}"))
            except ValueError:
                pass
            return self._send(200, {"cancel": SITE.cancel})
        return self._send(200, {"ok": True})

    def do_PUT(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        m = re.match(r"^/api/v1/compute/jobs/([^/]+)/chunks/([^/]+)/$", u.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        SITE.put_count += 1
        SITE.puts.append((int(q["offset"]), len(body)))
        name = m.group(2)
        have = SITE.received.setdefault(name, bytearray())
        if SITE.put_count in SITE.fail_put_numbers:
            return self._send(500, {"error": "boom"})
        if int(q["offset"]) != len(have):
            return self._send(409, {"size": len(have), "error": "offset"})
        have.extend(body)
        if SITE.put_count in SITE.lose_ack_put_numbers:
            return self._send(500, {"error": "ack lost"})
        done = len(have) == int(q["total"])
        if done and q.get("sha256") and hashlib.sha256(bytes(have)).hexdigest() != q["sha256"]:
            SITE.received[name] = bytearray()
            return self._send(422, {"size": 0, "error": "sha256"})
        return self._send(200, {"size": len(have), "complete": done})


class Node:
    """agent.Job / agent.Site pointed at the fake site, with the data folder in a temp dir."""

    @classmethod
    def start(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.tmp = tempfile.mkdtemp(prefix="nm-edit-node-")
        cls.patches = [
            mock.patch.object(agent, "DATA", cls.tmp), mock.patch.object(agent, "WORK", os.path.join(cls.tmp, "work")),
            mock.patch.object(agent, "CONFIG", {"name": "TEST-NODE", "token": "tok", "site": cls.base}),
            mock.patch.object(agent, "site_base", lambda: cls.base), mock.patch.object(agent, "MANAGER", None),
        ]
        for p in cls.patches:
            p.start()

    @classmethod
    def stop(cls):
        for p in cls.patches:
            p.stop()
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def job(cls, uid, kind, payload):
        site = agent.Site(cls.base, "tok")
        job = agent.Job(site, {"uid": uid, "kind": kind, "payload": payload})
        shutil.rmtree(job.dir, ignore_errors=True)
        os.makedirs(job.inputs, exist_ok=True)
        os.makedirs(job.outputs, exist_ok=True)
        return job


@unittest.skipUnless(HAVE_FF, "ffmpeg is not installed")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Node.start()
        cls.src = os.path.join(Node.tmp, "a.mp4")
        run_ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.src)
        cls.data = open(cls.src, "rb").read()

    @classmethod
    def tearDownClass(cls):
        Node.stop()

    def setUp(self):
        SITE.__init__()
        SITE.files = {"f0": self.data}
        edit_render._INFO.clear()
        shutil.rmtree(edit_render.cache_dir(agent), ignore_errors=True)

    def payload(self, **extra):
        p = {
            "v": 1, "graph": "[0:v]scale=160:120,format=yuv420p[vout];[0:a]anull[aout]", "inputs": [{"file": "f0", "args": []}], "texts": {},
            "assets": {}, "fonts": [], "audio": True, "audio_args": ["-c:a", "aac", "-b:a", "96k"], "length": 3.0, "out": "render.mp4",
            "encode": {"cpu": ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"],
                       "nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-pix_fmt", "yuv420p"], "codec": "h264"},
            "files": {"f0": {"name": "a.mp4", "size": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}},
        }
        p.update(extra)
        return p

    def run_job(self, uid, payload=None):
        job = Node.job(uid, "edit.render", payload or self.payload())
        with mock.patch.object(edit_render, "caps", lambda *_a, **_k: {"nvenc": {"h264": False, "h265": False}}):
            return job, edit_render.run(job, agent)

    def test_download_resumes_after_a_cut_and_the_upload_survives_a_lost_ack_and_a_failed_chunk(self):
        SITE.cut_first_get_after = 20_000
        SITE.fail_put_numbers = {2}
        SITE.lose_ack_put_numbers = {3}
        with mock.patch.object(edit_render, "CHUNK", 8 * 1024):
            job, meta = self.run_job("t-resume")
        self.assertGreaterEqual(SITE.get_count, 2, "the cut download was asked again")
        self.assertIsNone(SITE.gets[0])
        self.assertTrue(SITE.gets[1] and SITE.gets[1].startswith("bytes="), "…with a Range from where it stopped")
        got = bytes(SITE.received["render.mp4"])
        self.assertEqual(hashlib.sha256(got).hexdigest(), meta["sha256"])
        self.assertEqual(len(got), meta["bytes"])
        self.assertEqual(meta["encoder"], "H.264")
        out = os.path.join(Node.tmp, "got.mp4")
        open(out, "wb").write(got)
        info = json.loads(subprocess.run([FF.replace("ffmpeg", "ffprobe") if os.path.exists(FF.replace("ffmpeg", "ffprobe")) else "ffprobe", "-v", "error", "-show_streams", "-of", "json", out],
                                         capture_output=True, text=True).stdout)
        kinds = {s["codec_type"] for s in info["streams"]}
        self.assertEqual(kinds, {"video", "audio"})
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((v["width"], v["height"]), (160, 120))
        offsets = [o for o, _n in SITE.puts]
        self.assertEqual(offsets[0], 0)
        self.assertEqual(len(offsets), len(set(offsets)) + SITE.put_count - len(set(offsets)))   # chunks are re-sent, never skipped
        self.assertEqual(max(o + n for o, n in SITE.puts), len(got))

    def test_the_second_export_of_the_same_files_downloads_nothing(self):
        self.run_job("t-cache-1")
        first = SITE.get_count
        self.assertGreaterEqual(first, 1)
        SITE.received.clear()
        self.run_job("t-cache-2")
        self.assertEqual(SITE.get_count, first, "the originals are cached by sha256")
        self.assertIn("render.mp4", SITE.received)

    def test_a_corrupt_download_is_refused_by_the_checksum(self):
        bad = self.payload()
        bad["files"]["f0"]["sha256"] = "0" * 64
        with mock.patch.object(nm_fetch_stall(), "STALL_DEFAULT", 1):
            with self.assertRaises(Exception) as ctx:
                with mock.patch.object(edit_render, "STALL_S", 2):
                    self.run_job("t-bad", bad)
        self.assertRegex(str(ctx.exception).lower(), "checksum|sha|download")

    def test_cancel_stops_ffmpeg_and_raises_cancelled(self):
        long_src = os.path.join(Node.tmp, "long.mp4")
        run_ff("-f", "lavfi", "-i", "testsrc2=size=640x480:rate=25:duration=40", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", long_src)
        data = open(long_src, "rb").read()
        SITE.files["f1"] = data
        payload = self.payload(inputs=[{"file": "f1", "args": []}], graph="[0:v]hqdn3d=10:10:10:10,hqdn3d=10:10:10:10,hqdn3d=10:10:10:10,scale=640:480,format=yuv420p[vout]",
                               audio=False, length=40.0,
                               files={"f1": {"name": "long.mp4", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}})
        job = Node.job("t-cancel", "edit.render", payload)
        calls = {"n": 0}
        real = job.site.post

        def post(path, data=None, timeout=60):
            calls["n"] += 1
            if "render|" in json.dumps(data or {}):
                SITE.cancel = True
            return real(path, data, timeout)

        job.site.post = post
        before = subprocess.run(["pgrep", "-f", "hqdn3d"], capture_output=True, text=True).stdout.split() if os.name != "nt" else []
        with mock.patch.object(edit_render, "caps", lambda *_a, **_k: {"nvenc": {}}):
            with self.assertRaises(agent.Cancelled):
                edit_render.run(job, agent)
        if os.name != "nt":
            after = subprocess.run(["pgrep", "-f", "hqdn3d"], capture_output=True, text=True).stdout.split()
            self.assertEqual(sorted(after), sorted(before), "the ffmpeg of the cancelled job is gone")
        self.assertNotIn("render.mp4", SITE.received)

    def test_nvenc_that_fails_falls_back_to_the_cpu_encoder(self):
        warned = []
        with mock.patch.object(agent, "warn", lambda m: warned.append(m)), \
                mock.patch.object(edit_render, "caps", lambda *_a, **_k: {"nvenc": {"h264": True, "h265": False}}):
            job = Node.job("t-nvenc", "edit.render", self.payload())
            meta = edit_render.run(job, agent)
        if "h264_nvenc" in edit_render.ffmpeg_info(FF)["encoders"] and not edit_render.nvenc_works(FF):
            self.assertTrue(any("NVENC failed" in w for w in warned), warned)
        self.assertIn(meta["encoder"], ("H.264", "NVENC H.264"))
        self.assertTrue(SITE.received["render.mp4"])
        if not edit_render.nvenc_works(FF):
            self.assertEqual(meta["encoder"], "H.264", "no GPU here: the CPU encoder made the file")

    def test_a_filter_the_ffmpeg_lacks_is_reported_and_refused(self):
        fake = {"version": (8, 0), "filters": {"scale"}, "encoders": {"libx264"}}
        with mock.patch.object(edit_render, "ffmpeg_info", lambda ff: fake):
            with self.assertRaises(agent.JobError) as ctx:
                self.run_job("t-missing")
        self.assertIn("lacks filters", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)
        with mock.patch.object(edit_render, "ffmpeg_info", lambda ff: fake):
            edit_render._CAPS["state"] = None
            c = edit_render.caps(agent, wait=True)
        self.assertFalse(c["render"])
        self.assertIn("ass", c["missing"])
        edit_render._CAPS["state"] = None

    def test_caps_report_the_filters_the_editor_needs_and_nvenc(self):
        edit_render._CAPS["state"] = None
        c = edit_render.caps(agent, wait=True)
        self.assertEqual(c["v"], 1)
        self.assertIn("nvenc", c)
        self.assertEqual(set(c["nvenc"]), {"h264", "h265"})
        self.assertEqual(c["render"], not c["missing"] and "libx264" in edit_render.ffmpeg_info(FF)["encoders"])
        self.assertIsInstance(c["track"], bool)
        self.assertIn(c["matte_engine"], ("rvm", "birefnet", "rvm-pending", ""))
        self.assertEqual(set(c["rvm"]), {"runtime", "model", "provider", "ort"})
        self.assertIsInstance(c["cache"], list)
        edit_render._CAPS["state"] = None


def nm_fetch_stall():
    import nm_fetch

    return nm_fetch


@unittest.skipUnless(HAVE_FF and os.path.isdir(FONTS), "ffmpeg or the bundled fonts are missing")
class SelftestTests(unittest.TestCase):
    ASS = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 120\n\n[V4+ Styles]\n"
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
           "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           "Style: T,Vazirmatn,52,&HFFFFFF&,&HFFFFFF&,&H000000&,&H000000&,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,-1\n\n"
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:00.00,0:00:01.00,T,,0,0,0,,سلام دنیا ABC\n")

    def measure(self, fonts):
        work = tempfile.mkdtemp(prefix="nm-st-")
        try:
            f = os.path.join(work, "t.ass")
            open(f, "w", encoding="utf-8").write(self.ASS)
            r = subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x120:r=10:d=1", "-vf",
                                "ass=filename=%s:fontsdir=%s,format=gray" % (edit_render.filter_path(f), edit_render.filter_path(fonts)),
                                "-ss", "0.3", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, stdin=subprocess.DEVNULL)
            return edit_render.count_ink(r.stdout, 320, 120)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_the_same_fonts_pass_and_a_different_layout_is_refused(self):
        want = self.measure(FONTS)
        self.assertGreater(want["count"], 500, "the Persian line was drawn")
        test = {"ass": self.ASS, "w": 320, "h": 120, "expect": want, "count_tol": 0.12, "width_tol": 0.04, "at": 0.3}
        work = tempfile.mkdtemp(prefix="nm-st2-")
        try:
            self.assertIsNone(edit_render.selftest(FF, test, FONTS, work))
            wrong = dict(test, expect={**want, "count": want["count"] * 2, "x1": want["x1"] + 80})
            why = edit_render.selftest(FF, wrong, FONTS, work)
            self.assertIn("would not look like the site's", why)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_a_render_with_titles_checks_itself_and_succeeds(self):
        Node.start()
        try:
            SITE.__init__()
            src = os.path.join(Node.tmp, "t.mp4")
            run_ff("-f", "lavfi", "-i", "color=c=0x303030:s=320x120:r=25:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", src)
            data = open(src, "rb").read()
            fonts = {}
            for i, name in enumerate(sorted(n for n in os.listdir(FONTS) if n.endswith(".ttf"))):
                blob = open(os.path.join(FONTS, name), "rb").read()
                fonts["g%d" % i] = {"name": name, "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "data": blob}
            SITE.files = {"f0": data, **{k: v["data"] for k, v in fonts.items()}}
            want = self.measure(FONTS)
            graph = "[0:v]ass=filename='__FILE_0__':fontsdir='__FONTSDIR__',format=yuv420p[vout]"
            payload = {
                "v": 1, "graph": graph, "inputs": [{"file": "f0", "args": []}], "texts": {"__FILE_0__": self.ASS}, "assets": {}, "fonts": list(fonts),
                "audio": False, "audio_args": [], "length": 2.0, "out": "render.mp4",
                "encode": {"cpu": ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"], "nvenc": [], "codec": "h264"},
                "files": {"f0": {"name": "t.mp4", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                          **{k: {x: v[x] for x in ("name", "size", "sha256")} for k, v in fonts.items()}},
                "selftest": {"ass": self.ASS, "w": 320, "h": 120, "expect": want, "count_tol": 0.12, "width_tol": 0.04, "at": 0.3},
            }
            job = Node.job("t-titles", "edit.render", payload)
            with mock.patch.object(edit_render, "caps", lambda *_a, **_k: {"nvenc": {}}):
                meta = edit_render.run(job, agent)
            self.assertTrue(meta["bytes"] > 1000)
            out = os.path.join(Node.tmp, "titles.mp4")
            open(out, "wb").write(bytes(SITE.received["render.mp4"]))
            frame = subprocess.run([FF, "-v", "error", "-ss", "0.5", "-i", out, "-vf", "format=gray", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True).stdout
            self.assertGreater(sum(1 for b in frame if b > 200), 300, "the title is in the rendered file")
            # the same job with a wrong expectation is refused BEFORE anything is rendered
            SITE.received.clear()
            payload["selftest"]["expect"] = {**want, "count": want["count"] * 3}
            with self.assertRaises(agent.JobError) as ctx:
                edit_render.run(Node.job("t-titles2", "edit.render", payload), agent)
            self.assertIn("SELFTEST", str(ctx.exception))
            self.assertFalse(SITE.received)
        finally:
            Node.stop()


@unittest.skipUnless(HAVE_FF, "ffmpeg is not installed")
class TrackAndMatteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Node.start()
        cls.has_cv = bool(__import__("importlib").util.find_spec("cv2") and __import__("importlib").util.find_spec("numpy"))
        if cls.has_cv:
            import numpy as np

            rng = np.random.default_rng(5)
            W, H, N, FPS = 320, 240, 45, 15
            bg = (rng.random((H, W)) * 60 + 40).astype(np.uint8)
            patch = (rng.random((40, 40)) * 200 + 30).astype(np.uint8)
            cls.truth = []
            cls.video = os.path.join(Node.tmp, "move.mp4")
            proc = subprocess.Popen([FF, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
                                     "-c:v", "libx264", "-pix_fmt", "yuv420p", cls.video], stdin=subprocess.PIPE)
            for i in range(N):
                x, y = 40 + i * 4, 100 + int(15 * math.sin(i / 7))
                frame = bg.copy()
                frame[y:y + 40, x:x + 40] = patch
                cls.truth.append((x + 20, y + 20))
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait()
        cls.clip = os.path.join(Node.tmp, "clip.mp4")
        run_ff("-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", cls.clip)

    @classmethod
    def tearDownClass(cls):
        Node.stop()

    def test_tracking_runs_on_the_node_and_the_copy_is_the_sites_file(self):
        if not self.has_cv:
            self.skipTest("cv2/numpy are not in this Python (the site tracks instead)")
        job = Node.job("t-track", "edit.track", {"video": "clip.mp4", "region": {"x": 40 / 320, "y": 100 / 240, "w": 40 / 320, "h": 40 / 240}, "fps": 15,
                                                 "size": [320, 240], "duration": 3.0})
        shutil.copy(self.video, os.path.join(job.inputs, "clip.mp4"))
        meta = edit_jobs.run_track(job, agent)
        self.assertEqual(meta["primary"], "track.json")
        out = json.load(open(job.out("track.json"), encoding="utf-8"))
        self.assertGreaterEqual(len(out["samples"]), 35)
        worst = max(math.hypot(s["x"] * 320 - self.truth[min(round(s["s"] * 15), len(self.truth) - 1)][0],
                               s["y"] * 240 - self.truth[min(round(s["s"] * 15), len(self.truth) - 1)][1]) for s in out["samples"])
        self.assertLess(worst, 6.0)
        if os.path.exists(SITE_COPY):
            self.assertEqual(open(TRACK_COPY, "rb").read(), open(SITE_COPY, "rb").read(), "edit_track.py must stay identical to services/editing/tracking.py")

    def test_matte_goes_frame_by_frame_through_the_photo_kit(self):
        import http.server

        mask = os.path.join(Node.tmp, "mask.png")
        run_ff("-f", "lavfi", "-i", "color=c=black:s=160x120:d=0.1", "-vf", "drawbox=x=0:y=0:w=80:h=120:color=white:t=fill,format=gray", "-frames:v", "1", mask)
        seen = {"docs": 0, "masks": 0, "deleted": 0, "methods": []}

        class Kit(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                body = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/health":
                    return self._send(200, {"background": {"ai": {"installed": True, "enabled": True, "canRun": True}}})
                if re.match(r"^/api/docs/d\d+/mask$", self.path):
                    seen["masks"] += 1
                    return self._send(200, open(mask, "rb").read(), "image/png")
                self._send(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                if self.path.startswith("/api/docs?"):
                    seen["docs"] += 1
                    return self._send(200, {"id": "d%d" % seen["docs"], "name": "f"})
                if re.match(r"^/api/docs/d\d+/background", self.path):
                    seen["methods"].append(self.path.split("?", 1)[1])
                    return self._send(200, {"seconds": 0.1})
                self._send(404, {})

            def do_DELETE(self):
                seen["deleted"] += 1
                self._send(200, {"ok": True})

        kit = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Kit)
        threading.Thread(target=kit.serve_forever, daemon=True).start()
        models = os.path.join(Node.tmp, "tools", "PersianAiKit", "Photo", "models", "background")
        os.makedirs(models, exist_ok=True)
        rvm_off = mock.patch.dict(os.environ, {"NM_RVM": "0"})      # this test is the older per-frame path (tests/test_edit_rvm.py covers RVM)
        rvm_off.start()
        self.addCleanup(rvm_off.stop)
        try:
            job = Node.job("t-matte", "edit.matte", {"video": "clip.mp4", "fps": 6, "duration": 2.0, "size": [160, 120]})
            shutil.copy(self.clip, os.path.join(job.inputs, "clip.mp4"))
            with mock.patch.object(agent, "service_url", lambda key: "http://127.0.0.1:%d" % kit.server_address[1]):
                with self.assertRaises(agent.JobError) as ctx:                         # the model is not there yet: exactly what is needed
                    edit_jobs.run_matte(job, agent)
                self.assertIn("photo-background", str(ctx.exception))
                self.assertIn("224", str(ctx.exception))
                self.assertFalse(ctx.exception.retryable)
                open(os.path.join(models, "birefnet-lite.onnx"), "wb").write(b"fake")
                meta = edit_jobs.run_matte(job, agent)
            self.assertEqual((meta["primary"], meta["frames"]), ("matte.mp4", 12))
            self.assertEqual(meta["model"], "birefnet-lite")
            self.assertIn("NM_RVM=0", meta["rvm_skipped"])
            self.assertEqual((seen["docs"], seen["masks"], seen["deleted"]), (12, 12, 12), "every frame went up, came back and was cleaned up")
            self.assertTrue(all("method=ai" in m for m in seen["methods"]))
            out = job.out("matte.mp4")
            pix = subprocess.run([FF, "-v", "error", "-ss", "0.5", "-i", out, "-vf", "scale=2:1,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True).stdout
            self.assertTrue(pix[0] > 200 and pix[1] < 60, "left half white, right half black: %r" % list(pix))
        finally:
            kit.shutdown()


if __name__ == "__main__":
    unittest.main()

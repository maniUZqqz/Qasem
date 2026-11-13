"""agent 2.11: a finished result is never lost to a bad line - outbox, resumable chunks, connectivity state, log spool."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import outbox as ob  # noqa: E402


class SiteError(Exception):
    pass


class JobLost(Exception):
    pass


class FakeAgent:
    SiteError = SiteError
    JobLost = JobLost

    def __init__(self):
        self.logs, self.warnings = [], []

    def log(self, m, level="INFO"):
        self.logs.append(m)

    def warn(self, m):
        self.warnings.append(m)


class FakeSite:
    """The site as a flaky line sees it. `down` = how many of the next calls fail with 'site unreachable'; `lost` = a 403 for
    this job; `refuse` = HTTP 4xx; `drop_after_chunks` = break the line after N accepted chunks."""

    def __init__(self):
        self.down = 0
        self.lost = False
        self.refuse = None
        self.server_error = False
        self.uploaded = {}
        self.finished = []
        self.parts = {}
        self.chunk_calls = 0
        self.drop_after_chunks = None
        self.accepted_chunks = 0
        self.upload_calls = 0

    def _maybe_fail(self):
        if self.down > 0:
            self.down -= 1
            raise SiteError("site unreachable (http://x): <urlopen error [WinError 10060] timed out>")
        if self.lost:
            raise JobLost("the site gave this job to another attempt")
        if self.refuse:
            raise SiteError("POST x -> HTTP %d no" % self.refuse)
        if self.server_error:
            raise SiteError("POST x -> HTTP 502 bad gateway")

    def upload(self, path, files, timeout=1800, attempts=8, sleep=None):
        self.upload_calls += 1
        self._maybe_fail()
        for k, (name, data) in files.items():
            self.uploaded[name] = data
        return {"ok": True}

    def post(self, path, data=None, timeout=60):
        self._maybe_fail()
        self.finished.append((path, data))
        return {"ok": True}

    def get_json(self, path, timeout=30):
        self._maybe_fail()
        name = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[1])
        return {"size": len(self.parts.get(name, b""))}

    def _req(self, method, path, data=None, headers=None, timeout=60, raw=False):
        assert method == "PUT"
        self._maybe_fail()
        self.chunk_calls += 1
        base, qs = path.split("?", 1)
        q = dict(urllib.parse.parse_qsl(qs))
        name = urllib.parse.unquote(base.rstrip("/").rsplit("/", 1)[1])
        have = self.parts.get(name, b"")
        if int(q["offset"]) != len(have):
            raise SiteError("PUT x -> HTTP 409 {\"size\": %d}" % len(have))
        self.parts[name] = have + data
        self.accepted_chunks += 1
        if len(self.parts[name]) == int(q["total"]):
            self.uploaded[name] = self.parts.pop(name)
            return {"size": int(q["total"]), "complete": True}
        if self.drop_after_chunks is not None and self.accepted_chunks >= self.drop_after_chunks:
            self.drop_after_chunks = None
            self.down = 1
        return {"size": len(self.parts[name]), "complete": False}


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.agent = FakeAgent()
        self.box = ob.Outbox(os.path.join(self.tmp, "outbox"), self.agent)
        self.site = FakeSite()
        self.old = (ob.SMALL_FILE, ob.CHUNK)

    def tearDown(self):
        ob.SMALL_FILE, ob.CHUNK = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_outputs(self, **files):
        d = os.path.join(self.tmp, "job-outputs")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        for name, data in files.items():
            with open(os.path.join(d, name), "wb") as fh:
                fh.write(data)
        return d

    def test_a_result_is_delivered_and_the_entry_is_removed(self):
        self.box.stash("u1", "comfy.graph", True, "", {"device": "cuda"}, self.make_outputs(**{"a.png": b"PNG", "b.json": b"{}"}))
        self.assertEqual(self.box.count(), 1)
        self.assertEqual(self.box.deliver(self.site, "u1"), "done")
        self.assertEqual(self.site.uploaded, {"a.png": b"PNG", "b.json": b"{}"})
        path, body = self.site.finished[0]
        self.assertTrue(path.endswith("/jobs/u1/finish/"))
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["meta"], {"device": "cuda"})
        self.assertEqual(self.box.count(), 0)

    def test_a_dead_line_keeps_the_result_and_it_arrives_later(self):
        self.box.stash("u2", "voice.tts", True, "", {"x": 1}, self.make_outputs(**{"speech.wav": b"RIFF"}))
        self.site.down = 3
        self.assertEqual(self.box.deliver(self.site, "u2"), "retry")
        self.assertEqual(self.box.count(), 1)                       # still here, not lost
        self.assertEqual(self.box.deliver(self.site, "u2"), "retry")
        self.assertEqual(self.box.deliver(self.site, "u2"), "retry")
        self.assertEqual(self.box.deliver(self.site, "u2"), "done")
        self.assertEqual(self.site.uploaded["speech.wav"], b"RIFF")
        self.assertEqual(self.box.count(), 0)

    def test_what_already_reached_the_site_is_not_sent_again(self):
        ob.SMALL_FILE = 1000
        outs = self.make_outputs(**{"a.bin": b"A" * 10, "b.bin": b"B" * 10, "c.bin": b"C" * 10, "d.bin": b"D" * 10, "e.bin": b"E" * 10})
        self.box.stash("u3", "x", True, "", {}, outs)
        calls = {"n": 0}
        real = self.site.upload

        def upload(path, files, timeout=1800, attempts=8, sleep=None):
            calls["n"] += 1
            if calls["n"] == 2:                                       # the second batch (e.bin) hits a dead line
                raise SiteError("site unreachable")
            return real(path, files, timeout, attempts, sleep)
        self.site.upload = upload
        self.assertEqual(self.box.deliver(self.site, "u3"), "retry")
        self.assertEqual(sorted(self.site.uploaded), ["a.bin", "b.bin", "c.bin", "d.bin"])
        manifest = json.load(open(os.path.join(self.box.entry_dir("u3"), "manifest.json")))
        self.assertEqual(manifest["uploaded"], ["a.bin", "b.bin", "c.bin", "d.bin"])
        self.assertEqual(self.box.deliver(self.site, "u3"), "done")
        self.assertEqual(calls["n"], 3)                               # only e.bin went again
        self.assertEqual(len(self.site.uploaded), 5)

    def test_a_big_file_resumes_from_where_the_site_has_it(self):
        ob.SMALL_FILE, ob.CHUNK = 10, 8
        data = bytes(range(60))
        self.box.stash("u4", "edit.render", True, "", {}, self.make_outputs(**{"big.mp4": data}))
        self.site.drop_after_chunks = 3                               # the line breaks after 24 bytes arrived
        self.assertEqual(self.box.deliver(self.site, "u4"), "retry")
        self.assertEqual(len(self.site.parts["big.mp4"]), 24)
        calls_before = self.site.chunk_calls
        self.assertEqual(self.box.deliver(self.site, "u4"), "done")
        self.assertEqual(self.site.uploaded["big.mp4"], data)
        self.assertEqual(self.site.chunk_calls - calls_before, 5)    # only the missing 36 bytes: 5 chunks of 8 (the last is 4)
        self.assertEqual(self.site.finished[-1][1]["ok"], True)

    def test_a_409_makes_it_continue_from_the_sites_size(self):
        ob.SMALL_FILE, ob.CHUNK = 10, 8
        data = bytes(range(40))
        self.box.stash("u5", "x", True, "", {}, self.make_outputs(**{"f.bin": data}))
        self.site.parts["f.bin"] = data[:16]                          # an earlier try left 16 bytes there
        self.assertEqual(self.box.deliver(self.site, "u5"), "done")
        self.assertEqual(self.site.uploaded["f.bin"], data)

    def test_a_job_that_belongs_to_somebody_else_is_dropped_not_retried_forever(self):
        self.box.stash("u6", "x", True, "", {}, self.make_outputs(**{"a": b"1"}))
        self.site.lost = True
        self.assertEqual(self.box.deliver(self.site, "u6"), "dropped")
        self.assertEqual(self.box.count(), 0)
        self.assertTrue(any("another attempt" in w for w in self.agent.warnings))

    def test_a_refusal_is_dropped_but_a_server_error_is_retried(self):
        self.box.stash("u7", "x", False, "boom", {}, None)
        self.site.refuse = 400
        self.assertEqual(self.box.deliver(self.site, "u7"), "dropped")
        self.box.stash("u8", "x", False, "boom", {}, None)
        self.site.refuse, self.site.server_error = None, True
        self.assertEqual(self.box.deliver(self.site, "u8"), "retry")
        self.assertEqual(self.box.count(), 1)

    def test_a_failure_report_is_delivered_too(self):
        self.box.stash("u9", "ollama.generate", False, "RuntimeError: x", {"retryable": False}, None)
        self.assertEqual(self.box.deliver(self.site, "u9"), "done")
        body = self.site.finished[0][1]
        self.assertEqual((body["ok"], body["error"], body["meta"]), (False, "RuntimeError: x", {"retryable": False}))

    def test_an_entry_older_than_three_days_is_dropped(self):
        self.box.stash("old", "x", True, "", {}, self.make_outputs(**{"a": b"1"}))
        m = os.path.join(self.box.entry_dir("old"), "manifest.json")
        d = json.load(open(m))
        d["created"] = time.time() - 4 * 86400
        json.dump(d, open(m, "w"))
        self.assertEqual(self.box.deliver(self.site, "old"), "dropped")

    def test_flush_stops_at_the_first_dead_line_and_delivers_the_rest_later(self):
        for i in range(3):
            self.box.stash("f%d" % i, "x", True, "", {}, self.make_outputs(**{"a%d" % i: b"1"}))
        self.site.down = 1
        done, left = self.box.flush(self.site)
        self.assertEqual((done, left), (0, 3))
        done, left = self.box.flush(self.site)
        self.assertEqual((done, left), (3, 0))

    def test_the_flusher_backs_off_and_then_empties_the_outbox(self):
        self.box.stash("g1", "x", True, "", {}, self.make_outputs(**{"a": b"1"}))
        fl = ob.Flusher(self.box, self.site)
        self.site.down = 2
        waits = []
        for _ in range(2):
            waits.append(fl.once())
        self.assertEqual(waits, [30, 60])
        self.assertGreater(waits[1], waits[0])
        fl.once()
        self.assertEqual(self.box.count(), 0)
        self.assertEqual(fl.step, 0)

    def test_the_flusher_ships_spooled_log_lines_when_the_line_is_back(self):
        spool = ob.LogSpool(os.path.join(self.tmp, "unsent.jsonl"))
        spool.add([{"level": "ERROR", "message": "a"}, {"level": "WARNING", "message": "b"}])
        sent = []
        fl = ob.Flusher(self.box, self.site, spool=spool, ship_logs=lambda lines: sent.extend(lines))
        fl.once()
        self.assertEqual([x["message"] for x in sent], ["a", "b"])
        self.assertEqual(spool.read_all(), [])


class ConnectivityTests(unittest.TestCase):
    def test_one_message_when_it_drops_a_reminder_each_minute_and_the_downtime_when_back(self):
        now = [1000.0]
        c = ob.Connectivity(now=lambda: now[0], rnd=lambda: 0.5)
        wait, msg = c.fail("WinError 10060")
        self.assertTrue(msg and "unreachable" in msg and "WinError 10060" in msg)
        self.assertEqual(wait, 5.0)
        self.assertTrue(c.offline)
        silent = 0
        for _ in range(5):
            now[0] += 10
            wait, msg = c.fail("WinError 10060")
            silent += msg is None
        self.assertGreaterEqual(silent, 4)                              # no message flood
        self.assertEqual(wait, 60.0)                                    # 5 -> 10 -> 20 -> 40 -> 60 (cap)
        now[0] += 30
        _w, msg = c.fail("again")
        self.assertIn("still unreachable", msg)
        now[0] += 100
        self.assertAlmostEqual(c.ok(), now[0] - 1000.0)
        self.assertFalse(c.offline)
        self.assertIsNone(c.ok())
        wait, msg = c.fail("new drop")
        self.assertEqual(wait, 5.0)
        self.assertTrue(msg)

    def test_waits_have_jitter(self):
        a = ob.Connectivity(rnd=lambda: 0.0).fail("x")[0]
        b = ob.Connectivity(rnd=lambda: 1.0).fail("x")[0]
        self.assertLess(a, b)


class LogSpoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.spool = ob.LogSpool(os.path.join(self.tmp, "logs", "unsent.jsonl"), max_lines=5)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lines_survive_and_the_spool_is_capped(self):
        self.spool.add([{"message": str(i)} for i in range(8)])
        self.assertEqual([x["message"] for x in self.spool.read_all()], ["3", "4", "5", "6", "7"])

    def test_drain_sends_in_batches_and_clears(self):
        self.spool.add([{"message": str(i)} for i in range(5)])
        batches = []
        self.assertEqual(self.spool.drain(batches.append, batch=2), 5)
        self.assertEqual([len(b) for b in batches], [2, 2, 1])
        self.assertEqual(self.spool.read_all(), [])

    def test_a_failing_drain_keeps_everything(self):
        self.spool.add([{"message": "a"}])

        def boom(lines):
            raise OSError("down")
        with self.assertRaises(OSError):
            self.spool.drain(boom)
        self.assertEqual(len(self.spool.read_all()), 1)


if __name__ == "__main__":
    unittest.main()

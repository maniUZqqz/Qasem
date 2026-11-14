"""agent 2.23 - the owner's morning, node side: a standby window must not run old code after an update (found by the 11/13 review), and the
shipped requirement files are consistent with what the site mirrors and the self-tests wait for."""
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-readiness-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import agent  # noqa: E402
import instance_lock as il  # noqa: E402


class StartupStampTests(unittest.TestCase):
    def test_the_baseline_is_the_code_as_it_was_when_this_process_loaded_it(self):
        self.assertEqual(agent.STARTUP_STAMP, agent.code_stamp())
        self.assertFalse(agent.code_changed_since_start())

    def test_a_standby_that_wakes_after_an_update_sees_that_the_files_are_new(self):
        """The standby loaded its code, waited in take_instance_lock(), the other agent was updated and stopped. The baseline must still be
        the old one - a baseline taken after the wait would equal the new files and the standby would run the old code for ever."""
        new_files = tuple((name, (size or 0) + 7, mtime) for name, size, mtime in agent.STARTUP_STAMP)
        with mock.patch.object(agent, "code_stamp", return_value=new_files):
            self.assertTrue(agent.code_changed_since_start())

    def test_main_uses_the_import_time_baseline_and_no_later_one(self):
        src = inspect.getsource(agent.main)
        self.assertIn("code_changed_since_start()", src)
        self.assertNotRegex(src, r"stamp\s*=\s*code_stamp\(\)")
        self.assertIn("take_instance_lock()", src)

    def test_the_lock_hands_over_to_a_waiting_standby_and_the_standby_restarts_on_the_new_code(self):
        d = tempfile.mkdtemp(prefix="nm-standby-")
        path = os.path.join(d, "agent.lock")
        first, standby = il.InstanceLock(path), il.InstanceLock(path)
        self.assertTrue(first.acquire())
        said = []
        polls = {"n": 0}

        def sleep(_s):
            polls["n"] += 1
            if polls["n"] == 2:
                first.release()                                   # the first agent stopped for the update

        new_files = tuple((name, (size or 0) + 1, mtime) for name, size, mtime in agent.STARTUP_STAMP)
        got = il.wait_for_turn(standby, say=said.append, poll_s=0, sleep=sleep)
        self.assertTrue(got)
        try:
            with mock.patch.object(agent, "code_stamp", return_value=new_files):        # the update replaced the files meanwhile
                self.assertTrue(agent.code_changed_since_start())
        finally:
            standby.release()


class ShippedRequirementsTests(unittest.TestCase):
    def specs(self):
        out = {}
        for name in sorted(os.listdir(os.path.join(HERE, "requirements.d"))):
            if name.endswith(".json"):
                with open(os.path.join(HERE, "requirements.d", name), encoding="utf-8") as fh:
                    spec = json.load(fh)
                out[spec["feature"]] = spec
        return out

    def test_every_feature_has_a_persian_title_and_a_known_order(self):
        for name, spec in self.specs().items():
            self.assertTrue(spec.get("title_fa"), name)
            self.assertIsInstance(spec.get("order"), int, name)

    def test_nothing_requires_a_feature_that_does_not_exist_and_nothing_loops(self):
        specs = self.specs()
        for name, spec in specs.items():
            for dep in spec.get("requires") or []:
                self.assertIn(dep, specs, "%s requires %s" % (name, dep))
                self.assertLess(specs[dep]["order"], spec["order"], "%s must come after %s" % (name, dep))

    def test_every_site_mirrored_source_has_a_public_fallback_or_is_a_pinned_pack(self):
        """Iran: a file the site mirrors is the first choice; the archive items also name the public origin so a lost mirror file is not fatal."""
        for name, spec in self.specs().items():
            for item in spec["items"]:
                if item["type"] != "archive":
                    continue
                sources = item.get("sources") or []
                self.assertTrue(sources and "site" in sources[0], "%s/%s: the site mirror must come first" % (name, item["id"]))

    def test_the_agent_advertises_the_kinds_the_requirements_hold_back(self):
        for name, spec in self.specs().items():
            for kind in spec.get("kinds") or []:
                self.assertIn(kind, agent.HANDLERS, "%s holds jobs of kind %s which this agent does not serve" % (name, kind))

    def test_big_optional_downloads_come_after_everything_a_job_waits_for(self):
        """One installer thread works through the features in order: 1.6 GB of a better speech model must not hold up Blender or Abagram."""
        specs = self.specs()
        last_needed = max(s["order"] for s in specs.values() if s.get("kinds"))
        for name in ("asr-large", "blender-3d-presenters"):
            self.assertGreater(specs[name]["order"], last_needed, name)

    def test_the_bootstrap_ctx_the_agent_builds_asks_the_sites_window(self):
        src = inspect.getsource(agent.start_bootstrap)
        self.assertIn("download_allowed=lambda: download_allowed()", src)


class RenderFallbackTests(unittest.TestCase):
    """edit_render.render_with_fallbacks: the final render of the automatic edit must not die because one hardware path of the card fails."""

    def go(self, errors, nvenc=True, hw=("-hwaccel", "cuda")):
        import edit_render
        calls, warned = [], []

        def build(ff, p, local, work, used_nvenc, hw_args):
            calls.append((used_nvenc, tuple(hw_args)))
            return ["ffmpeg"], "/out.mp4"

        def run(cmd, total, report):
            if errors:
                raise RuntimeError(errors.pop(0))
        result = edit_render.render_with_fallbacks("ff", {}, {}, "w", nvenc, list(hw), 1.0, None, warn=warned.append, build=build, run=run)
        return result, calls, warned

    def test_a_card_that_decodes_and_encodes_is_used_as_it_is(self):
        result, calls, warned = self.go([])
        self.assertEqual((result, calls, warned), (("/out.mp4", True, ["-hwaccel", "cuda"]), [(True, ("-hwaccel", "cuda"))], []))

    def test_nvdec_failing_decodes_on_the_cpu(self):
        result, calls, _ = self.go(["Impossible to convert between the formats supported by the filter (cuvid hwaccel failed)"])
        self.assertEqual(calls, [(True, ("-hwaccel", "cuda")), (True, ())])
        self.assertEqual((result[1], result[2]), (True, []))

    def test_nvenc_failing_encodes_with_x264(self):
        result, calls, warned = self.go(["OpenEncodeSession failed: No capable devices found"])
        self.assertEqual(calls, [(True, ("-hwaccel", "cuda")), (False, ("-hwaccel", "cuda"))])
        self.assertEqual(result[1], False)
        self.assertTrue(any("NVENC failed" in w for w in warned))

    def test_nvdec_then_nvenc_both_fall_back_in_a_row(self):
        """The 11/13 review: after the decoder fallback an NVENC failure used to end the job."""
        result, calls, warned = self.go(["hwaccel cuda decode failed", "OpenEncodeSession failed: No capable devices found"])
        self.assertEqual(calls, [(True, ("-hwaccel", "cuda")), (True, ()), (False, ())])
        self.assertEqual((result[1], result[2]), (False, []))
        self.assertEqual(len(warned), 2)

    def test_a_real_error_is_raised_and_each_fallback_happens_at_most_once(self):
        with self.assertRaises(RuntimeError):
            self.go(["Invalid data found when processing input"])
        with self.assertRaises(RuntimeError):
            self.go(["NVENC failed"] * 3)


if __name__ == "__main__":
    unittest.main()
